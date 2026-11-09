"""用户指定的起手：應急裝置 → 减费 Jinx → 打掉 Jinx 生成的飞逝牌。"""

from lorwright.models import Action, ActionType, GameState, UIState

#: Jinx 下场后手牌被替换成的飞逝牌。客户端繁中名 + 用户常用简中名。
ROCKET_NAMES = frozenset({
    "超威能死亡火箭！", "超威能死亡火箭",
    "超究极死神飞弹", "超究極死神飛彈",
    "威能死亡火箭！", "威能死亡火箭",
})
POW_POW_NAMES = frozenset({"砰砰", "碰碰", "Pow-Pow"})


class JinxOpeningPolicy:
    name = "jinx_opening"
    version = "0.1.0"

    def __init__(
        self, *, spell_already_played: bool = False, jinx_summoned: bool = False,
    ) -> None:
        # 恢复已有对局时，调用方必须依据可靠记录或人工确认显式提供此信息。
        self.step = 2 if jinx_summoned else (1 if spell_already_played else 0)
        self._mulligan = False
        self._awaiting_crab = False
        self._awaiting_hero = False
        self._board_before: int | None = None
        self._last_opening_view = None
        self._stable_views = 0
        #: 本次 Jinx 下场后已经打出的火箭数；用户要求最多打 2 次。
        self._rockets_played = 0
        self._mulligan_replaced = False

    def decide(self, state: GameState) -> Action:
        if state.ui_state is UIState.MULLIGAN:
            if not self._mulligan:
                self.step = 0
                self._awaiting_crab = False
                self._awaiting_hero = False
                self._board_before = None
                self._last_opening_view = None
                self._stable_views = 0
                self._rockets_played = 0
                self._mulligan_replaced = False
            self._mulligan = True
            cards = state.mulligan_cards
            if len(cards) != 4 or any(not card.name for card in cards):
                return Action(type=ActionType.NO_OP)
            if not self._mulligan_replaced:
                heroes = [card for card in cards if card.name == "吉茵珂絲"]
                if heroes:
                    # 用户确认：有 Jinx 时保留其他牌，仅替换多余的 Jinx。
                    points = [card.rect.center for card in heroes[1:]]
                else:
                    points = [card.rect.center for card in cards]
                if points:
                    self._mulligan_replaced = True
                    return Action(
                        type=ActionType.MULLIGAN_REPLACE,
                        raw={"points": points},
                    )
            self._mulligan_replaced = True
            return Action(type=ActionType.CONFIRM)
        self._mulligan = False
        if self.step >= 3:
            # 开局组合完成：弃权，交给通用层（英雄优先/攻击序列）接手。
            return None
        if state.ui_state is not UIState.MY_TURN_IDLE:
            self._last_opening_view = None
            self._stable_views = 0
            return None
        if self.step == 2:
            return self._decide_post_jinx(state)
        # 起手手牌可能已经是展开态；不能只在收起分支里初始化场面基线。
        if self._board_before is None:
            self._board_before = len(state.my_units)
        if self._awaiting_crab:
            if self._board_before is None or len(state.my_units) <= self._board_before:
                return Action(type=ActionType.NO_OP)
            self._awaiting_crab = False
            self.step = 1
        if self._awaiting_hero:
            if self._board_before is not None and len(state.my_units) > self._board_before:
                self.step = 2
                self._awaiting_hero = False
            return Action(type=ActionType.NO_OP)
        if not state.hand_expanded:
            self._board_before = len(state.my_units)
            # PLAY_CARD 在收起态只展开手牌，不会打出该索引的牌；
            # 起手第一件事就是展开，不需要等 3 帧稳定。
            if state.hand:
                return Action(type=ActionType.PLAY_CARD, card_index=state.hand[0].index)
            return Action(type=ActionType.NO_OP)
        name, cost = (("應急裝置", 1) if self.step == 0 else ("吉茵珂絲", 2))
        matches = [card for card in state.hand if card.name == name and card.cost == cost]
        if not matches or state.mana < cost or self._board_before is None:
            # 本帧找不到目标或费用不够：弃权。通用层可先把满价 Jinx
            # 打下去（英雄优先），不阻塞整局。
            return None
        return Action(type=ActionType.PLAY_CARD, card_index=matches[0].index)

    def _decide_post_jinx(self, state: GameState) -> Action | None:
        """Jinx 已下场：优先打 2 张火箭，再用砰砰；名字认不出时只兜底小手牌。"""
        if not state.hand_expanded:
            return None
        playable = [card for card in state.hand if 0 <= card.cost <= state.mana]
        if not playable:
            return None
        if self._rockets_played < 2:
            rockets = [card for card in playable if card.name in ROCKET_NAMES]
            if rockets:
                return Action(type=ActionType.PLAY_CARD, card_index=rockets[0].index)
        pows = [card for card in playable if card.name in POW_POW_NAMES]
        if pows:
            return Action(type=ActionType.PLAY_CARD, card_index=pows[0].index)
        # 卡面识别不出名字时，只在刚下完 Jinx 的两张手牌上按最左顺序兜底；
        # 中局的大手牌不猜，避免把普通牌当飞逝牌打掉。
        if len(state.hand) <= 2:
            unnamed = [card for card in playable if not card.name]
            if unnamed:
                return Action(type=ActionType.PLAY_CARD, card_index=unnamed[0].index)
        return None

    def on_action_outcome(self, action: Action, before: GameState, after: GameState) -> None:
        """只在执行器确认动作成功后推进；展开手牌不算出牌。"""
        if action.type is not ActionType.PLAY_CARD or not before.hand_expanded:
            return
        card = next((c for c in before.hand if c.index == action.card_index), None)
        if card is None:
            return
        if self.step == 2:
            if card.name in ROCKET_NAMES:
                self._rockets_played += 1
        elif self.step == 0 and card.name == "應急裝置" and card.cost == 1:
            if self._board_before is not None and len(after.my_units) > self._board_before:
                self.step = 1
            else:
                self._awaiting_crab = True
        elif self.step == 1 and card.name == "吉茵珂絲" and card.cost == 2:
            if self._board_before is not None and len(after.my_units) > self._board_before:
                self.step = 2
                self._rockets_played = 0
            else:
                self._awaiting_hero = True
