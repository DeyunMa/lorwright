"""对局外地图自动循环：点节点 → 处理事件 → 进战斗 → 回地图。

用户规则（2026-11-05 确认）：
- 沿发光线找带蓝色指向标的下一节点（已完成节点带绿色对勾，自动跳过）；
- 商店节点：旅行 → 离开（购买后续细化）；
- 战斗节点：战斗按钮 → Engine 接管；
- 休息节点（加号）：点第一个选项加血，满血点不动就离开；
- 节点内操作完成后英雄不自动离开，必须点击下一节点移动；
- 分叉多条线时随机选一条（mapnav 已实现）。

坐标空间：本类在 960x540 半尺寸图上跑 mapnav，点击时 x2 回真实分辨率。
节点面板按钮坐标来自 settings.adventure，实机校准后更新。
"""

from __future__ import annotations

import random
import time

import cv2

from lorwright.device.base import Device
from lorwright.models import UIState
from lorwright.perceive.mapnav import next_node
from lorwright.util.logger import logger


class AdventureLoop:
    BATTLE_STATES = {
        UIState.MULLIGAN,
        UIState.MY_TURN_IDLE,
        UIState.BLOCKING,
        UIState.TARGETING,
        UIState.COMBAT_RESOLVING,
        UIState.ENEMY_TURN,
    }

    def __init__(self, settings, engine, device: Device) -> None:
        self.settings = settings
        self.engine = engine
        self.device = device
        self.coords = settings.adventure.to_coords()
        self.rng = random.Random()

    def run(self, max_nodes: int = 30) -> None:
        self.engine.parser.load()
        for _ in range(max_nodes):
            image = self._frame()
            ui = self.engine.parser.ui.detect(image)
            if ui in self.BATTLE_STATES:
                logger.info("adventure: 进入战斗，引擎接管")
                self.engine.run(max_ticks=self.coords.battle_max_ticks)
                continue
            if ui is UIState.BATTLE_END:
                self._tap_rect(self.coords.victory_continue)
                time.sleep(3)
                continue
            nxt = self._find_next(image)
            if nxt is None:
                logger.warning("adventure: 地图上找不到下一节点，停止（保存快照）")
                from lorwright.util.snapshot import save_snapshot
                save_snapshot(image, self.settings.perception.snapshot_dir, tag="map_no_next")
                return
            # mapnav 坐标在半尺寸图上，点击 x2 回真实分辨率
            self.device.tap(nxt.x * 2, nxt.y * 2)
            time.sleep(3)
            self._handle_node_panel()

    def _find_next(self, image):
        small = image
        if image.shape[1] >= 1920:
            small = cv2.resize(image, (960, 540))
        return next_node(small, rng=self.rng)

    def _handle_node_panel(self) -> None:
        """节点面板：旅行 → 按类型处理；处理不了的存快照停下。"""
        image = self._frame()
        ui = self.engine.parser.ui.detect(image)
        if ui in self.BATTLE_STATES or ui is UIState.BATTLE_END:
            return  # 有些节点直接进战斗
        # 面板上的「旅行」「戰鬥」按钮共用一个区域（实测 2026-11-05）
        self._tap_rect(self.coords.travel)
        time.sleep(4)
        image = self._frame()
        ui = self.engine.parser.ui.detect(image)
        if ui in self.BATTLE_STATES:
            return
        if ui is UIState.BATTLE_END:
            return
        # 旅行后不是战斗 → 商店或休息：先点第一个选项（休息=加血；
        # 商店界面点这里多半是空白/第一件商品，下面的离开兜底）。
        self._tap_rect(self.coords.rest_first_option)
        time.sleep(2)
        self._tap_rect(self.coords.shop_leave)
        time.sleep(3)

    def _tap_rect(self, rect) -> None:
        if rect is None:
            return
        x, y = rect.center
        self.device.tap(x, y)
        logger.info("adventure: tap ({}, {})", x, y)

    def _frame(self):
        frame = self.device.screencap()
        return frame.image
