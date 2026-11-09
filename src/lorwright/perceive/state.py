"""截图 → GameState：把界面上的数字与手牌读成结构化状态。

拆成独立对象而不是塞进 Engine，是因为感知层最难调：
`lorwright state` 可以直接调它，不用起整个主循环。
"""

from __future__ import annotations

import numpy as np

from lorwright.models import GameState, Layout, Reading, UIState
from lorwright.perceive import attack_token
from lorwright.perceive import hand as hand_perceive
from lorwright.perceive import units as units_perceive
from lorwright.perceive.buttons import find_continue_button
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
        card_recognizer=None,
        mulligan_recognizer=None,
    ) -> None:
        self.layout = layout
        self.ui = ui
        self.digits = digits or DigitReader()
        self.threshold = threshold
        self.card_recognizer = card_recognizer
        self.mulligan_recognizer = mulligan_recognizer
        #: 上次读成功的血量。数字被特效遮住时沿用旧值，比跳回默认值安全。
        self._my_hp = DEFAULT_NEXUS_HP
        self._enemy_hp = DEFAULT_NEXUS_HP
        #: 上次读成功的法力。读到 0 和读不出来是两回事：前者是没费了，
        #: 后者是数字被特效/动画盖住——当成 0 会让策略白白跳过一回合。
        self._mana = 0
        self._readings: dict[str, Reading] = {}
        self._previous_ui = UIState.UNKNOWN

    def load(self) -> None:
        self.ui.load()
        self.digits.load()

    def parse(self, image: np.ndarray) -> GameState:
        lay = self.layout
        state = GameState(ui_state=self.ui.detect(image),
                          continue_button=find_continue_button(image))
        if state.ui_state is UIState.MULLIGAN and self.mulligan_recognizer is not None:
            state.mulligan_cards = self.mulligan_recognizer(image)
        # 起手换牌是新对局边界，不能沿用上一场血量/法力。
        if state.ui_state is UIState.MULLIGAN and self._previous_ui is not UIState.MULLIGAN:
            self._readings.clear()
            self._my_hp = self._enemy_hp = DEFAULT_NEXUS_HP
            self._mana = 0
        self._previous_ui = state.ui_state
        readable_ui = state.ui_state not in (UIState.UNKNOWN, UIState.BATTLE_END)

        mana = self._observe("mana", image, lay.mana, readable_ui, state)
        if mana is not None:
            self._mana = mana
        state.mana = self._mana
        # 法力上限暂时跟着当前法力走：出牌判定只用到 mana，
        # 真正的宝石计数要等 pips 模板（见 docs/handoff.md §2）
        state.max_mana = self._mana

        enemy_hp = self._observe("enemy_nexus_hp", image, lay.enemy_hp, readable_ui, state)
        if enemy_hp is not None:
            self._enemy_hp = enemy_hp
        state.enemy_nexus_hp = self._enemy_hp

        my_hp = self._observe("nexus_hp", image, lay.my_hp, readable_ui, state)
        if my_hp is not None:
            self._my_hp = my_hp
        state.nexus_hp = self._my_hp

        # 先看展开态：展开后卡片大、位置明确、能拖；收起态只露左边缘拖不动。
        # 两套模板互不匹配（48px vs 56px），所以「谁认出来」就等于「处于哪个状态」。
        if lay.hand_expanded is not None:
            expanded = hand_perceive.recognize_expanded(image, lay.hand_expanded, self.digits)
            if expanded:
                state.hand = (self.card_recognizer(image, expanded)
                              if self.card_recognizer else expanded)
                state.hand_expanded = True

        if not state.hand_expanded and lay.hand_region is not None:
            # 徽章阈值是 hand 模块自己的常量，不要传 perception.match_threshold：
            # 0.85 是卡面模板的阈值，用在这里会把上百个圆形装饰都当成徽章
            state.hand = hand_perceive.recognize(image, lay.hand_region, self.digits)

        # 场上单位：只认位置，攻击力/生命值留 -1（留给战斗求解器读）
        if lay.my_board is not None:
            badges = units_perceive.find_unit_badges(image, lay.my_board)
            if (lay.my_combat is not None and not state.hand_expanded
                    and state.ui_state in (UIState.MY_TURN_IDLE, UIState.BLOCKING, UIState.COMBAT_RESOLVING)):
                badges += units_perceive.find_unit_badges(image, lay.my_combat)
            badges.sort(key=lambda badge: badge.center[0])
            state.my_units = units_perceive.to_units(badges, image=image)
        if lay.enemy_board is not None:
            state.enemy_units = units_perceive.to_units(
                units_perceive.find_unit_badges(image, lay.enemy_board, enemy=True),
                enemy=True,
                image=image,
            )
        # BLOCKING 时只有攻击行里的敌人才是攻击者；enemy_board 里的待命单位
        # 不能拿来分配格挡。区域识别不到时留空，由 BlockingPolicy 回退到
        # enemy_units（宁可多挡，不要因为区域没标定就整轮放行）。
        if state.ui_state is UIState.BLOCKING and lay.enemy_combat is not None:
            state.enemy_attackers = units_perceive.to_units(
                units_perceive.find_unit_badges(image, lay.enemy_combat, enemy=True),
                enemy=True,
                image=image,
            )

        # 只有轮到自己行动时令牌才有意义；对手攻击时的箭头长一样，但那时是 BLOCKING
        if state.ui_state is UIState.MY_TURN_IDLE and lay.attack_token is not None:
            state.has_attack_token = attack_token.has_attack_token(image, lay.attack_token)

        if state.ui_state is not UIState.MULLIGAN and mana is None:
            logger.debug("法力读不出来（区域 {}），沿用上次值 {}", lay.mana, self._mana)
        return state

    def _observe(self, name, image, rect, readable: bool, state: GameState) -> int | None:
        value = self._read(image, rect) if readable else None
        previous = self._readings.get(name, Reading())
        reading = (Reading(value, 0) if value is not None else Reading(
            previous.value,
            previous.age_frames + 1 if previous.age_frames is not None else None,
        ))
        self._readings[name] = reading
        state.readings[name] = reading
        return value

    def _read(self, image: np.ndarray, rect) -> int | None:
        if rect is None:
            return None
        return self.digits.read(image, rect)
