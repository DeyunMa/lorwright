"""截图 → GameState：把界面上的数字与手牌读成结构化状态。

拆成独立对象而不是塞进 Engine，是因为感知层最难调：
`lorwright state` 可以直接调它，不用起整个主循环。
"""

from __future__ import annotations

import numpy as np

from lorwright.models import GameState, Layout, UIState
from lorwright.perceive import hand as hand_perceive
from lorwright.perceive.digits import DigitReader
from lorwright.perceive.ui_state import UIStateDetector
from lorwright.util.logger import logger

#: 读不到血量时的初值（LoR 标准 20，英雄之路起始更高，会被第一次成功读取覆盖）
DEFAULT_NEXUS_HP = 20


class StateParser:
    def __init__(
        self,
        layout: Layout,
        ui: UIStateDetector,
        digits: DigitReader | None = None,
        threshold: float = 0.85,
    ) -> None:
        self.layout = layout
        self.ui = ui
        self.digits = digits or DigitReader()
        self.threshold = threshold
        #: 上次读成功的血量。数字被特效遮住时沿用旧值，比跳回默认值安全。
        self._my_hp = DEFAULT_NEXUS_HP
        self._enemy_hp = DEFAULT_NEXUS_HP

    def load(self) -> None:
        self.ui.load()
        self.digits.load()

    def parse(self, image: np.ndarray) -> GameState:
        lay = self.layout
        state = GameState(ui_state=self.ui.detect(image))

        mana = self._read(image, lay.mana)
        if mana is not None:
            state.mana = mana
            # 法力上限暂时跟着当前法力走：出牌判定只用到 mana，
            # 真正的宝石计数要等 pips 模板（见 docs/handoff.md §2）
            state.max_mana = mana

        enemy_hp = self._read(image, lay.enemy_hp)
        if enemy_hp is not None:
            self._enemy_hp = enemy_hp
        state.enemy_nexus_hp = self._enemy_hp

        my_hp = self._read(image, lay.my_hp)
        if my_hp is not None:
            self._my_hp = my_hp
        state.nexus_hp = self._my_hp

        if lay.hand_region is not None:
            # 徽章阈值是 hand 模块自己的常量，不要传 perception.match_threshold：
            # 0.85 是卡面模板的阈值，用在这里会把上百个圆形装饰都当成徽章
            state.hand = hand_perceive.recognize(image, lay.hand_region, self.digits)

        if state.ui_state is not UIState.MULLIGAN and mana is None:
            logger.debug("法力读不出来（区域 {}），本帧按 0 处理", lay.mana)
        return state

    def _read(self, image: np.ndarray, rect) -> int | None:
        if rect is None:
            return None
        return self.digits.read(image, rect)
