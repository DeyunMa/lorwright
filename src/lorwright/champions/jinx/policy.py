"""用户指定的起手：應急裝置 → 减费 Jinx → 打掉 Jinx 生成的飞逝牌。"""

from lorwright.decide.rewards import QUALITY_RANK, CardRewardCandidate, CardRewardPick
from lorwright.models import Action, ActionType, GameState, UIState

#: Jinx 下场后手牌被替换成的飞逝牌。客户端繁中名 + 用户常用简中名。
ROCKET_NAMES = frozenset({
    "超威能死亡火箭！", "超威能死亡火箭",
    "超究极死神飞弹", "超究極死神飛彈",
    "威能死亡火箭！", "威能死亡火箭",
})
POW_POW_NAMES = frozenset({"砰砰", "碰碰", "Pow-Pow"})


def pick_card_reward(candidates: list[CardRewardCandidate]) -> CardRewardPick | None:
    """Jinx 战斗奖励：先比较有效费用，同费用再比较卡牌品质。"""
    if not candidates or any(
        c.card.cost is None or c.card.cost < 0 or not c.cost_certain for c in candidates
    ):
        return None
    lowest = min(c.card.cost for c in candidates)
    cheapest = [c for c in candidates if c.card.cost == lowest]
    if len(cheapest) == 1:
        return CardRewardPick(cheapest[0], "Jinx：费用最低优先")
    if any(c.card.quality not in QUALITY_RANK for c in cheapest):
        return None
    chosen = max(cheapest, key=lambda c: QUALITY_RANK[c.card.quality])
    return CardRewardPick(chosen, "Jinx：费用相同时品质最高优先")


class JinxOpeningPolicy:
    name = "jinx_opening"
    version = "0.1.0"

    def __init__(
        self, *, spell_already_played: bool = False, jinx_summoned: bool = False,
    ) -> None:
        # 恢复已有对局时，调用方必须依据可靠记录或人工确认显式提供此信息。
        self.step = 2 if jinx_summoned else (1 if spell_already_played else 0)
        self._mulligan = False
        self._mulligan_targets: tuple[bool, ...] | None = None
        self._awaiting_crab = False
        self._awaiting_hero = False
        self._board_before: int | None = None
        self._last_opening_view = None
        self._stable_views = 0
        #: 本次 Jinx 下场后已经打出的火箭数；用户要求最多打 2 次。
        self._rockets_played = 0

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
                self._mulligan_targets = None
            self._mulligan = True
            cards = state.mulligan_cards
            selected = state.mulligan_selected
            if (len(cards) != 4 or [card.index for card in cards] != list(range(4))
                    or len(selected) != 4
                    or any(value is None for value in selected)):
                return Action(type=ActionType.NO_OP)
            observed = tuple(card.matches_target for card in cards)
            if self._mulligan_targets is None:
                # 选中后的特效会遮挡卡面；必须在四张均未选中且可见时
                # 建立本局判断，重启后不能猜测已经选中的牌。
                if any(selected) or any(value is None for value in observed):
                    return Action(type=ActionType.NO_OP)
                self._mulligan_targets = observed
            elif any(
                not selected[i] and observed[i] != self._mulligan_targets[i]
                for i in range(4)
            ):
                return Action(type=ActionType.NO_OP)
            heroes = [i for i, matches in enumerate(self._mulligan_targets) if matches]
            # 有 Jinx 时只替换多余的 Jinx；没有则四张都替换。
            desired = set(heroes[1:]) if heroes else set(range(4))
            for card, current in zip(cards, selected, strict=True):
                target = card.index in desired
                if current != target:
                    return Action(
                        type=ActionType.MULLIGAN_REPLACE,
                        raw={"points": [card.rect.center], "mulligan_index": card.index,
                             "selected": target},
                    )
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
        if self.step == 0:
            spells = [card for card in state.hand if card.name == "應急裝置"]
            available = state.mana + (state.spell_mana or 0)
            matches = [card for card in state.hand if card.name == "應急裝置"
                       and 0 <= card.cost <= 3 and card.cost <= available]
            if not matches and any(card.cost < 0 or card.cost <= 3 for card in spells):
                # 有目标牌但费用不明或当前付不起时，不让通用层抢先打出 Jinx。
                return Action(type=ActionType.NO_OP)
        else:
            matches = [card for card in state.hand if card.name == "吉茵珂絲"
                       and 0 <= card.cost <= state.mana]
        if not matches or self._board_before is None:
            # 本帧找不到目标或费用不够：弃权。通用层可先把满价 Jinx
            # 打下去（英雄优先），不阻塞整局。
            return None
        return Action(type=ActionType.PLAY_CARD, card_index=matches[0].index)

    def _decide_post_jinx(self, state: GameState) -> Action | None:
        """Jinx 下场后先处理两张火箭；费用和可用法力须足以证明能出。"""
        if not state.hand_expanded:
            return None
        if self._rockets_played < 2:
            cards = sorted(state.hand, key=lambda card: card.index)
            remaining = 2 - self._rockets_played
            if len(cards) < remaining or [c.index for c in cards] != list(range(len(cards))):
                return Action(type=ActionType.NO_OP)
            # 首次选择时两张火箭都要有卡面证据，避免漏掉最左牌后
            # 把第二张当第一张。第二张只在前一张结果核实后选择。
            if any(card.name not in ROCKET_NAMES for card in cards[:remaining]):
                return Action(type=ActionType.NO_OP)
            rocket = cards[0]
            if rocket.cost < 0:
                return Action(type=ActionType.NO_OP)
            available = state.mana + (state.spell_mana or 0)
            if rocket.cost <= available:
                return Action(type=ActionType.PLAY_CARD, card_index=rocket.index,
                              raw={"jinx_rocket": True})
            # 确认不够费用时让通用层继续战斗；法术法力未知则等待。
            return None if state.spell_mana is not None else Action(type=ActionType.NO_OP)
        playable = [card for card in state.hand if 0 <= card.cost <= state.mana]
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
            if action.raw.get("jinx_rocket") is True and card.name in ROCKET_NAMES:
                self._rockets_played += 1
        elif self.step == 0 and card.name == "應急裝置" and 0 <= card.cost <= 3:
            if self._board_before is not None and len(after.my_units) > self._board_before:
                self.step = 1
            else:
                self._awaiting_crab = True
        elif self.step == 1 and card.name == "吉茵珂絲" and card.cost >= 0:
            if self._board_before is not None and len(after.my_units) > self._board_before:
                self.step = 2
                self._rockets_played = 0
            else:
                self._awaiting_hero = True
