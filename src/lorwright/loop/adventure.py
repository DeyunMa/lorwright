"""对局外地图自动循环：点节点 → 处理事件 → 进战斗 → 回地图。

用户规则（2026-11-05 确认）：
- 沿发光线找带蓝色指向标的下一节点（已完成节点带绿色对勾，自动跳过）；
- 商店节点：旅行 → 离开（购买后续细化）；
- 战斗节点：战斗按钮 → Engine 接管；
- 休息节点（加号）：点第一个选项加血，满血点不动就离开；
- 节点内操作完成后英雄不自动离开，必须点击下一节点移动；
- 分叉多条线时随机选一条（mapnav 已实现）。

坐标空间：1920×1080 设计尺寸。mapnav 直接吃设计帧，点击不再 x2。
节点面板的金色按钮（旅行／战斗）由 perceive.panels.action_button 动态检测，
不再依赖固定坐标；2026-11-07 实机校准。
"""

from __future__ import annotations

import random
import time

import cv2
import numpy as np

from lorwright.act.translate import ActionTranslator
from lorwright.decide.rewards import pick_reward
from lorwright.device.base import Device
from lorwright.models import Action, ActionType, GameState, UIState
from lorwright.perceive.adventure_scene import (
    button_is,
    is_battle_detail,
    is_completed_panel,
    is_map,
)
from lorwright.perceive.buttons import find_continue_button
from lorwright.perceive.mapnav import empty_point, next_node, panel_open
from lorwright.perceive.panels import action_button
from lorwright.perceive.reward_screen import is_power_screen, recognize_powers
from lorwright.util import snapshot
from lorwright.util.logger import logger


def _continue_view(image):
    """记录按钮上方的内容，用于区分同位置的连续结果页。"""
    height, width = image.shape[:2]
    content = image[int(height * 0.15):int(height * 0.8),
                    int(width * 0.2):int(width * 0.8)]
    return cv2.resize(content, (100, 60), interpolation=cv2.INTER_AREA)


class AdventureLoop:
    BATTLE_STATES = {
        UIState.MULLIGAN,
        UIState.MY_TURN_IDLE,
        UIState.BLOCKING,
        UIState.TARGETING,
        UIState.COMBAT_RESOLVING,
        UIState.ENEMY_TURN,
    }

    def __init__(self, settings, engine, device: Device, *, pack) -> None:
        self.settings = settings
        self.engine = engine
        self.device = device
        self.pack = pack
        self.coords = settings.adventure.to_coords()
        self.translator = ActionTranslator(settings.layout.to_layout())
        self.rng = random.Random()

    def run(self, max_nodes: int = 30) -> None:
        self.engine.parser.load()
        last_continue = None
        last_continue_view = None
        for _ in range(max_nodes):
            image = self._frame()
            ui = self.engine.parser.ui.detect(image)
            if ui in self.BATTLE_STATES:
                last_continue = None
                logger.info("adventure: 进入战斗，引擎接管")
                self.engine.run(max_ticks=self.coords.battle_max_ticks)
                continue
            if ui is UIState.BATTLE_END:
                button = find_continue_button(image)
                if button is None:
                    snapshot.save_snapshot(
                        image, self.settings.perception.snapshot_dir, tag="continue_missing"
                    )
                    return
                x, y = button.center
                if last_continue is not None and (
                    abs(x - last_continue[0]) <= 40 and abs(y - last_continue[1]) <= 40
                ) and last_continue_view is not None and (
                    np.mean(cv2.absdiff(_continue_view(image), last_continue_view)) < 15
                ):
                    snapshot.save_snapshot(
                        image, self.settings.perception.snapshot_dir, tag="continue_unchanged"
                    )
                    return
                plan = self.translator.translate(
                    Action(ActionType.CONTINUE), GameState(continue_button=button)
                )
                if plan is None:
                    return
                self.device.tap(*plan.points[0])
                last_continue = (x, y)
                last_continue_view = _continue_view(image)
                time.sleep(3)
                continue
            last_continue = None
            if is_power_screen(image):
                self._preview_power(image)
                return
            if not is_map(image):
                logger.warning("adventure: 未识别地图画面，停止（保存快照）")
                snapshot.save_snapshot(image, self.settings.perception.snapshot_dir, tag="unknown_scene")
                return
            nxt = self._find_next(image)
            if nxt is None:
                if is_completed_panel(image):
                    if self._close_panel(image):
                        continue
                    logger.warning("adventure: 面板打开但找不到空白点，停止")
                    snapshot.save_snapshot(
                        image, self.settings.perception.snapshot_dir, tag="panel_no_empty_point"
                    )
                    return
                logger.warning("adventure: 地图上找不到下一节点，停止（保存快照）")
                from lorwright.util.snapshot import save_snapshot
                save_snapshot(image, self.settings.perception.snapshot_dir, tag="map_no_next")
                return
            # mapnav 返回的是输入帧像素坐标；_find_next 已统一换算到设计尺寸。
            self.device.tap(nxt.x, nxt.y)
            time.sleep(3)
            if not self._handle_node_panel():
                return

    def _find_next(self, image):
        recognize_hero = getattr(self.pack, "recognize_map_hero", None)
        if recognize_hero is not None:
            hero = recognize_hero(image)
            if hero is None:
                return None
            return next_node(image, rng=self.rng, hero=hero)
        return next_node(image, rng=self.rng)

    def _preview_power(self, image) -> None:
        candidates = recognize_powers(image)
        if candidates is not None:
            picked = pick_reward(candidates, self.pack.power_preferences)
            if picked is not None:
                logger.info("adventure: 能力推荐 {}（{}），等待确认流程素材",
                            picked.candidate.name, picked.reason)
        else:
            logger.warning("adventure: 能力候选无法完整识别，停止")
        snapshot.save_snapshot(image, self.settings.perception.snapshot_dir, tag="power_choice")

    def _close_panel(self, image) -> bool:
        # 动态找“非节点”的空白区域，不固定某个坐标。
        point = empty_point(image)
        if point is None:
            return False
        for _ in range(2):
            self.device.tap(*point)
            logger.info("adventure: 点击空白处关闭面板 ({}, {})", *point)
            time.sleep(4)
            image = self._frame()
            if is_map(image) and not panel_open(image):
                return True
            if not is_completed_panel(image):
                return False
        return False

    def _handle_node_panel(self) -> bool:
        """节点面板：点金色「旅行」→「戰鬥」；找不到按钮就停下存快照。"""
        image = self._frame()
        ui = self.engine.parser.ui.detect(image)
        if ui in self.BATTLE_STATES or ui is UIState.BATTLE_END:
            return True  # 有些节点直接进战斗
        if is_power_screen(image):
            self._preview_power(image)
            return False
        if not is_map(image) and not is_battle_detail(image):
            logger.warning("adventure: 未识别节点面板，停止（保存快照）")
            snapshot.save_snapshot(image, self.settings.perception.snapshot_dir, tag="panel_unknown")
            return False
        # 点了节点但还在地图：说明这次点击没打开面板（坐标/动画/网络问题）。
        # 此时不能再盲点「旅行」，否则会把地图上的空白当成按钮。
        if is_map(image) and self._find_next(image) is not None:
            logger.warning("adventure: 节点点击后仍在地图，停止盲点（保存快照）")
            snapshot.save_snapshot(
                image, self.settings.perception.snapshot_dir, tag="map_panel_not_open"
            )
            return False
        # 每个阶段只点一次；下一帧必须进入下一阶段，不能重复点同一按钮。
        last_action = None
        for _ in range(2):
            button = action_button(image)
            if button is not None and last_action is None and is_map(image) and button_is(
                image, button, "travel"
            ):
                action = "travel"
            elif (button is not None and last_action != "battle" and is_battle_detail(image)
                  and button_is(image, button, "battle")):
                action = "battle"
            else:
                break
            self.device.tap(*button.center)
            last_action = action
            logger.info("adventure: 面板按钮 ({}, {})", *button.center)
            time.sleep(4)
            image = self._frame()
            ui = self.engine.parser.ui.detect(image)
            if ui in self.BATTLE_STATES or ui is UIState.BATTLE_END:
                return True
            if is_power_screen(image):
                self._preview_power(image)
                return False
            if not is_map(image) and not is_battle_detail(image):
                break
        # 旅行后回到地图：说明这个节点只是移动，继续下一轮找节点。
        if last_action == "travel" and is_map(image) and self._find_next(image) is not None:
            return True
        # 没有金色按钮（能力三选一／商店／信息面板）：不盲点，存快照停下。
        logger.warning("adventure: 面板未进入预期的下一阶段，停止（保存快照）")
        snapshot.save_snapshot(
            image, self.settings.perception.snapshot_dir,
            tag="panel_no_action_button" if last_action else "panel_unknown",
        )
        return False

    def _frame(self):
        frame = self.device.screencap()
        return frame.image
