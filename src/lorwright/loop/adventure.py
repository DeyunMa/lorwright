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
from lorwright.decide.rewards import pick_card_reward, pick_reward
from lorwright.decide.support import pick_support_group
from lorwright.device.base import Device
from lorwright.models import Action, ActionType, GameState, UIState
from lorwright.perceive.adventure_scene import (
    button_is,
    find_home_adventure_entry,
    find_resume_adventure_button,
    is_battle_detail,
    is_completed_panel,
    is_map,
    shop_leave_button,
)
from lorwright.perceive.buttons import find_continue_button
from lorwright.perceive.healer import healer_heal_button, is_healer_screen
from lorwright.perceive.mapnav import (
    _current_completed_node_visible,
    empty_point,
    next_node,
    panel_open,
)
from lorwright.perceive.normalize import Normalizer
from lorwright.perceive.panels import action_button
from lorwright.perceive.reward_screen import (
    card_reward_confirm_button,
    card_reward_selection,
    card_reward_target,
    is_card_reward_screen,
    is_power_screen,
    recognize_card_rewards,
    recognize_powers,
)
from lorwright.perceive.support_screen import (
    is_support_screen,
    recognize_support_choices,
    same_support_choices,
    support_confirm_button,
    support_selection,
)
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
        self.normalizer = Normalizer((settings.screen.width, settings.screen.height))
        self.rng = random.Random()

    def run(self, max_nodes: int = 30) -> None:
        self.engine.parser.load()
        last_continue = None
        last_continue_view = None
        for _ in range(max_nodes):
            image = self._frame()
            if shop_leave_button(image) is not None:
                if not self._handle_shop(image):
                    return
                continue
            if self._is_healer(image):
                if not self._handle_healer(image):
                    return
                continue
            if self._is_support(image):
                if not self._handle_support(image):
                    return
                continue
            if self._is_card_reward(image):
                if not self._handle_card_reward(image):
                    return
                continue
            normalized = self._reward_design(image)
            design = normalized[0] if normalized is not None else image
            ui = self.engine.parser.ui.detect(design)
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
            if is_battle_detail(image):
                if not self._handle_node_panel(image):
                    return
                continue
            # 主页属于独立识别场景，不把战斗 UNKNOWN 当作点击授权。
            height, width = image.shape[:2]
            if width and height and abs(width / height - 16 / 9) <= 0.02:
                design_image, scale = self.normalizer.fit(image)
                resume = find_resume_adventure_button(design_image)
                if resume is not None:
                    selected = getattr(self.pack, "recognize_selected_hero", None)
                    if selected is None or not selected(design_image):
                        logger.warning("adventure: 无法确认所选英雄，停止")
                        snapshot.save_snapshot(
                            image, self.settings.perception.snapshot_dir, tag="resume_hero_unknown"
                        )
                        return
                    self.device.tap(*scale.to_device(*resume.center))
                    for _ in range(6):
                        time.sleep(2)
                        after = self._frame()
                        if is_map(after):
                            logger.info("adventure: 已继续冒险，返回地图")
                            break
                    else:
                        snapshot.save_snapshot(
                            after, self.settings.perception.snapshot_dir,
                            tag="resume_transition_unverified",
                        )
                        return
                    continue
                entry = find_home_adventure_entry(design_image)
                if entry is not None:
                    self.device.tap(*scale.to_device(*entry.center))
                    time.sleep(3)
                    next_image = self._frame()
                    snapshot.save_snapshot(
                        next_image, self.settings.perception.snapshot_dir, tag="home_entry_after"
                    )
                    logger.info("adventure: 已点击英雄之路入口，等待下一场景识别")
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

    def _reward_design(self, image):
        height, width = image.shape[:2]
        if not width or not height or abs(width / height - 16 / 9) > 0.02:
            return None
        if (self.settings.screen.width, self.settings.screen.height) != (1920, 1080):
            return None
        return self.normalizer.fit(image)

    def _is_card_reward(self, image) -> bool:
        normalized = self._reward_design(image)
        return normalized is not None and is_card_reward_screen(normalized[0])

    def _is_support(self, image) -> bool:
        normalized = self._reward_design(image)
        return normalized is not None and is_support_screen(normalized[0])

    def _is_healer(self, image) -> bool:
        normalized = self._reward_design(image)
        return normalized is not None and is_healer_screen(normalized[0])

    def _handle_shop(self, image) -> bool:
        """按当前通用规则离开商店，核实返回地图后继续。"""
        button = shop_leave_button(image)
        if button is None:
            return False
        self.device.tap(*button.center)
        time.sleep(3)
        after = self._frame()
        if is_map(after) and not panel_open(after):
            logger.info("adventure: 已离开商店，继续寻找下一节点")
            return True
        snapshot.save_snapshot(after, self.settings.perception.snapshot_dir, tag="shop_leave_unverified")
        return False

    def _handle_healer(self, image) -> bool:
        """点一次免费治疗，确认回到地图且节点完成后继续冒险。"""
        normalized = self._reward_design(image)
        button = healer_heal_button(normalized[0]) if normalized is not None else None
        if normalized is None or button is None:
            logger.warning("adventure: 治疗师选项或按钮无法确认，停止")
            snapshot.save_snapshot(
                image, self.settings.perception.snapshot_dir, tag="healer_unknown"
            )
            return False
        _, scale = normalized
        self.device.tap(*scale.to_device(*button.center))
        logger.info("adventure: 已点击治疗，等待核对结果")
        time.sleep(3)
        after = self._frame()
        if self._is_healer(after):
            logger.warning("adventure: 治疗后仍在治疗师页面，停止")
            tag = "healer_unchanged"
        elif is_map(after) and not panel_open(after):
            recognize_hero = getattr(self.pack, "recognize_map_hero", None)
            hero = recognize_hero(after) if recognize_hero is not None else None
            if hero is not None and _current_completed_node_visible(after, hero):
                logger.info("adventure: 治疗节点已完成，继续冒险")
                snapshot.save_snapshot(
                    after, self.settings.perception.snapshot_dir, tag="healer_completed"
                )
                return True
            logger.warning("adventure: 治疗后回到地图，但无法确认节点完成")
            tag = "healer_map_unverified"
        else:
            logger.warning("adventure: 治疗后状态无法确认，停止")
            tag = "healer_after_unknown"
        snapshot.save_snapshot(after, self.settings.perception.snapshot_dir, tag=tag)
        return False

    def _handle_support(self, image) -> bool:
        """选择援军并核对选中状态；确认后无法验证到账则停止。"""
        normalized = self._reward_design(image)
        if normalized is None:
            return False
        design, scale = normalized
        choices = recognize_support_choices(design)
        if choices is None:
            snapshot.save_snapshot(
                image, self.settings.perception.snapshot_dir, tag="support_unknown"
            )
            return False
        index = pick_support_group([choice.group for choice in choices])
        if index is None:
            logger.warning("adventure: 辅助英雄费用不足以排序，停止")
            snapshot.save_snapshot(
                image, self.settings.perception.snapshot_dir, tag="support_undecided"
            )
            return False
        logger.info("adventure: 选择第 {} 组辅助英雄（英雄 {} 费）", index + 1,
                    choices[index].group.hero_cost)
        self.device.tap(*scale.to_device(*choices[index].target.center))
        time.sleep(3)
        selected_image = self._frame()
        selected = self._reward_design(selected_image)
        if (selected is None or support_selection(selected[0]) != index
                or not same_support_choices(design, selected[0], index)):
            snapshot.save_snapshot(
                selected_image, self.settings.perception.snapshot_dir, tag="support_selection_failed"
            )
            return False
        button = support_confirm_button(selected[0])
        if button is None:
            snapshot.save_snapshot(
                selected_image, self.settings.perception.snapshot_dir, tag="support_confirm_missing"
            )
            return False
        self.device.tap(*selected[1].to_device(*button.center))
        time.sleep(3)
        next_image = self._frame()
        next_design = self._reward_design(next_image)
        if next_design is None or is_support_screen(next_design[0]):
            snapshot.save_snapshot(
                next_image, self.settings.perception.snapshot_dir, tag="support_confirm_unchanged"
            )
            return False
        if not is_map(next_design[0]):
            snapshot.save_snapshot(
                next_image, self.settings.perception.snapshot_dir, tag="support_after_unknown"
            )
            return False
        logger.warning("adventure: 辅助英雄确认后已转场，但尚无法验证卡牌到账，停止")
        snapshot.save_snapshot(
            next_image, self.settings.perception.snapshot_dir, tag="support_reward_unverified"
        )
        return False

    def _handle_card_reward(self, image) -> bool:
        """逐步选牌并核对转场；到账尚不可验证时停止。"""
        normalized = self._reward_design(image)
        if normalized is None:
            return False
        design, scale = normalized
        candidates = recognize_card_rewards(design)
        if candidates is None:
            logger.warning("adventure: 卡牌奖励信息不完整或已选中，停止")
            snapshot.save_snapshot(image, self.settings.perception.snapshot_dir, tag="card_reward_unknown")
            return False
        champion_pick = getattr(self.pack, "pick_card_reward", None)
        picked = champion_pick(candidates) if champion_pick is not None else pick_card_reward(
            candidates, getattr(self.pack, "card_preferences", ()),
            getattr(self.pack, "item_preferences", ()),
        )
        if picked is None:
            logger.warning("adventure: 卡牌奖励无法安全排序，停止")
            snapshot.save_snapshot(image, self.settings.perception.snapshot_dir, tag="card_reward_undecided")
            return False
        index = candidates.index(picked.candidate)
        logger.info("adventure: 选择奖励 {}（{}）", picked.candidate.card.name, picked.reason)
        target = card_reward_target(design, index, picked.candidate.card.name)
        if target is None:
            snapshot.save_snapshot(
                image, self.settings.perception.snapshot_dir, tag="card_reward_target_obscured"
            )
            return False
        self.device.tap(*scale.to_device(*target.center))
        time.sleep(3)
        selected_image = self._frame()
        selected = self._reward_design(selected_image)
        if selected is None or card_reward_selection(selected[0]) != index:
            snapshot.save_snapshot(
                selected_image, self.settings.perception.snapshot_dir, tag="card_reward_selection_failed"
            )
            return False
        button = card_reward_confirm_button(selected[0])
        if button is None:
            snapshot.save_snapshot(
                selected_image, self.settings.perception.snapshot_dir, tag="card_reward_confirm_missing"
            )
            return False
        self.device.tap(*selected[1].to_device(*button.center))
        time.sleep(3)
        next_image = self._frame()
        next_design = self._reward_design(next_image)
        if next_design is None or is_card_reward_screen(next_design[0]):
            snapshot.save_snapshot(
                next_image, self.settings.perception.snapshot_dir, tag="card_reward_confirm_unchanged"
            )
            return False
        if not (is_map(next_design[0]) or is_power_screen(next_design[0])):
            snapshot.save_snapshot(
                next_image, self.settings.perception.snapshot_dir, tag="card_reward_after_unknown"
            )
            return False
        # 回到地图或进入能力页不代表服务端已把奖励加入牌组。
        logger.warning("adventure: 奖励确认后已转场，但尚无法验证卡牌到账，停止")
        snapshot.save_snapshot(
            next_image, self.settings.perception.snapshot_dir, tag="card_reward_unverified"
        )
        return False

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

    def _handle_node_panel(self, image=None) -> bool:
        """节点面板：点金色「旅行」→「戰鬥」；找不到按钮就停下存快照。"""
        if image is None:
            image = self._frame()
        if shop_leave_button(image) is not None:
            return self._handle_shop(image)
        if self._is_healer(image):
            return self._handle_healer(image)
        if self._is_support(image):
            return self._handle_support(image)
        if self._is_card_reward(image):
            return self._handle_card_reward(image)
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
            # 旅行或战斗可能先出现载入画面。只等待新帧，绝不重复点击；
            # 看到可识别的场景再交给对应处理，超时仍未知则停止。
            for attempt in range(11):
                image = self._frame()
                if shop_leave_button(image) is not None:
                    return self._handle_shop(image)
                if self._is_healer(image):
                    return self._handle_healer(image)
                if self._is_support(image):
                    return self._handle_support(image)
                if self._is_card_reward(image):
                    return self._handle_card_reward(image)
                ui = self.engine.parser.ui.detect(image)
                if ui in self.BATTLE_STATES or ui is UIState.BATTLE_END:
                    return True
                if is_power_screen(image):
                    self._preview_power(image)
                    return False
                if is_map(image) or is_battle_detail(image):
                    break
                if attempt < 10:
                    time.sleep(2)
            else:
                logger.warning("adventure: 节点转场后画面仍无法识别，停止")
                snapshot.save_snapshot(
                    image, self.settings.perception.snapshot_dir, tag="panel_transition_timeout"
                )
                return False
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
