"""用户指定的起手：先召蟹法术，再打减费至 2 费的 Jinx。"""

from lorwright.models import Action, ActionType, GameState, UIState


class JinxOpeningPolicy:
    name = "jinx_opening"
    version = "0.1.0"

    def __init__(self, *, spell_already_played: bool = False) -> None:
        # 恢复已有对局时，调用方必须依据可靠记录或人工确认显式提供此信息。
        self.step = 1 if spell_already_played else 0
        self._mulligan = False
        self._awaiting_crab = False
        self._awaiting_hero = False
        self._board_before: int | None = None
        self._last_opening_view = None
        self._stable_views = 0

    def decide(self, state: GameState) -> Action:
        if state.ui_state is UIState.MULLIGAN:
            if not self._mulligan:
                self.step = 0
                self._awaiting_crab = False
                self._awaiting_hero = False
                self._board_before = None
                self._last_opening_view = None
                self._stable_views = 0
            self._mulligan = True
            return Action(type=ActionType.CONFIRM)
        self._mulligan = False
        if self.step >= 2:
            # 开局组合完成：弃权，交给通用层（英雄优先/攻击序列）接手。
            return None
        if state.ui_state is not UIState.MY_TURN_IDLE:
            self._last_opening_view = None
            self._stable_views = 0
            return None
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
            view = (state.mana, state.nexus_hp, state.enemy_nexus_hp,
                    len(state.my_units), tuple(card.cost for card in state.hand))
            self._stable_views = self._stable_views + 1 if view == self._last_opening_view else 1
            self._last_opening_view = view
            # PLAY_CARD 在收起态只展开手牌，不会打出该索引的牌。
            if state.hand and self._stable_views >= 3:
                return Action(type=ActionType.PLAY_CARD, card_index=state.hand[0].index)
            return Action(type=ActionType.NO_OP)
        name, cost = (("應急裝置", 1) if self.step == 0 else ("吉茵珂絲", 2))
        matches = [card for card in state.hand if card.name == name and card.cost == cost]
        if not matches or state.mana < cost or self._board_before is None:
            # 本帧找不到目标或费用不够：弃权。通用层可先把满价 Jinx
            # 打下去（英雄优先），不阻塞整局。
            return None
        return Action(type=ActionType.PLAY_CARD, card_index=matches[0].index)

    def on_action_outcome(self, action: Action, before: GameState, after: GameState) -> None:
        """只在执行器确认动作成功后推进；展开手牌不算出牌。"""
        if action.type is not ActionType.PLAY_CARD or not before.hand_expanded:
            return
        card = next((c for c in before.hand if c.index == action.card_index), None)
        if card is None:
            return
        if self.step == 0 and card.name == "應急裝置" and card.cost == 1:
            if self._board_before is not None and len(after.my_units) > self._board_before:
                self.step = 1
            else:
                self._awaiting_crab = True
        elif self.step == 1 and card.name == "吉茵珂絲" and card.cost == 2:
            if self._board_before is not None and len(after.my_units) > self._board_before:
                self.step = 2
            else:
                self._awaiting_hero = True
