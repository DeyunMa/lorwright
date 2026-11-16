"""用户指定的起手：應急裝置 → 减费 Jinx → 打掉 Jinx 生成的飞逝牌。"""

from lorwright.core.decide.base import PlayExpectation
from lorwright.core.decide.rewards import QUALITY_RANK, CardRewardCandidate, CardRewardPick
from lorwright.core.models import Action, ActionType, GameState, UIState

#: Jinx 下场后手牌被替换成的飞逝牌。客户端繁中名 + 用户常用简中名。
ROCKET_NAMES = frozenset({
    "超威能死亡火箭！", "超威能死亡火箭",
    "超究极死神飞弹", "超究極死神飛彈",
    "威能死亡火箭！", "威能死亡火箭",
})
POW_POW_NAMES = frozenset({"砰砰", "碰碰", "Pow-Pow"})


def pick_card_reward(candidates: list[CardRewardCandidate]) -> CardRewardPick | None:
    """Jinx 奖励按已核实预览费用选择；同费比较已知品质，未知保留未知。"""
    if not candidates or any(
        c.card.cost is None or c.card.cost < 0
        or not (c.cost_certain or c.preview_cost_verified) for c in candidates
    ):
        return None
    lowest = min(c.card.cost for c in candidates)
    cheapest = [c for c in candidates if c.card.cost == lowest]
    if len(cheapest) == 1:
        return CardRewardPick(cheapest[0], "Jinx：费用最低优先")
    if any(c.card.quality not in QUALITY_RANK for c in cheapest):
        if not all(c.preview_cost_verified for c in cheapest):
            return None
        known = [c for c in cheapest if c.card.quality in QUALITY_RANK]
        chosen = max(known, key=lambda c: QUALITY_RANK[c.card.quality]) if known else cheapest[0]
        return CardRewardPick(chosen, "Jinx：预览费用最低；品质不全，已知优先，同级按显示顺序")
    chosen = max(cheapest, key=lambda c: QUALITY_RANK[c.card.quality])
    return CardRewardPick(chosen, "Jinx：费用相同时品质最高优先")


class JinxOpeningPolicy:
    name = "jinx_opening"
    version = "0.1.0"

    def __init__(
        self, *, spell_already_played: bool = False, jinx_summoned: bool = False,
        rockets_already_played: int = 0,
    ) -> None:
        if not 0 <= rockets_already_played <= 2 or (rockets_already_played and not jinx_summoned):
            raise ValueError("火箭恢复计数需为 0..2，且 Jinx 已下场")
        # 恢复已有对局时，调用方必须依据可靠记录或人工确认显式提供此信息。
        self.step = 2 if jinx_summoned else (1 if spell_already_played else 0)
        self._mulligan = False
        self._mulligan_targets: tuple[bool, ...] | None = None
        self._awaiting_crab = False
        self._board_before: int | None = None
        self._last_opening_view = None
        self._stable_views = 0
        #: 本次 Jinx 下场后已经打出的火箭数；用户要求最多打 2 次。
        self._rockets_played = rockets_already_played

    def decide(self, state: GameState) -> Action | None:
        if state.ui_state is UIState.MULLIGAN:
            if not self._mulligan:
                self.step = 0
                self._awaiting_crab = False
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
        if state.ui_state is UIState.TARGETING:
            if state.targeted_spell is not None and state.targeted_spell.name in POW_POW_NAMES:
                if state.enemy_units:
                    return Action(type=ActionType.SELECT_TARGET, raw={"enemy": True, "index": 0})
                return Action(type=ActionType.CANCEL, raw={"return_to_hand": True})
            return Action(type=ActionType.NO_OP)
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
        if not state.hand_expanded:
            self._board_before = len(state.my_units)
            # PLAY_CARD 在收起态只展开手牌，不会打出该索引的牌；
            # 起手第一件事就是展开，不需要等 3 帧稳定。
            if state.hand:
                return Action(type=ActionType.PLAY_CARD, card_index=state.hand[0].index)
            return None
        if self.step == 0:
            available = max(0, state.mana) + (state.spell_mana or 0)
            matches = [card for card in state.hand if card.name == "應急裝置"
                       and card.drag_point_valid and len(state.my_units) < 6
                       and 0 <= card.cost <= 3 and card.cost <= available]
        else:
            matches = [card for card in state.hand if card.name == "吉茵珂絲"
                       and card.drag_point_valid and len(state.my_units) < 6
                       and 0 <= card.cost <= max(0, state.mana)]
        if not matches or self._board_before is None:
            # 本帧找不到目标或费用不够：弃权。通用层可先把满价 Jinx
            # 打下去（英雄优先），不阻塞整局。
            return None
        raw = {"spell_mana_only": True} if self.step == 0 and state.mana < 0 else {}
        return Action(type=ActionType.PLAY_CARD, card_index=matches[0].index, raw=raw)

    def _decide_post_jinx(self, state: GameState) -> Action | None:
        """可执行火箭最优先；偏好无法执行时弃权，交给通用层继续。"""
        if not state.hand_expanded:
            return None
        cards = sorted(state.hand, key=lambda card: card.index)
        available = max(0, state.mana) + (state.spell_mana or 0)
        if self._rockets_played < 2:
            for card in cards:
                if (card.name in ROCKET_NAMES and card.drag_point_valid
                        and 0 <= card.cost <= available):
                    raw = {"jinx_rocket": True}
                    if state.mana < 0:
                        raw["spell_mana_only"] = True
                    return Action(type=ActionType.PLAY_CARD, card_index=card.index, raw=raw)
        # 跳过未知牌、付不起或拖点无效的牌，不让局部失败阻挡后续候选。
        if state.enemy_units:
            for card in cards:
                if (card.name not in POW_POW_NAMES or card.cost < 0
                        or not card.drag_point_valid):
                    continue
                if ((self._rockets_played >= 2 or state.has_fresh_readings("mana"))
                        and card.cost <= available):
                    raw = {"spell_mana_only": True} if state.mana < 0 else {}
                    return Action(type=ActionType.PLAY_CARD, card_index=card.index, raw=raw)
                if (state.has_fresh_readings("spell_mana")
                        and state.spell_mana is not None and card.cost <= state.spell_mana):
                    return Action(type=ActionType.PLAY_CARD, card_index=card.index,
                                  raw={"spell_mana_only": True})
        return None

    def play_expectation(self, action: Action, before: GameState) -> PlayExpectation | None:
        """Jinx 下场弃手转砰砰并生成两枚火箭，手牌应为出牌前数量加一。"""
        card = next((c for c in before.hand if c.index == action.card_index), None)
        if (action.type is not ActionType.PLAY_CARD or not before.hand_expanded
                or card is None or card.cost < 0):
            return None
        if card.name in ROCKET_NAMES and action.raw.get("jinx_rocket") is True:
            def verify_rocket(after: GameState) -> bool:
                if after.ui_state not in (UIState.MY_TURN_IDLE, UIState.ENEMY_TURN,
                                          UIState.BLOCKING):
                    return False
                mana_paid = (before.has_fresh_readings("mana")
                             and after.has_fresh_readings("mana") and after.mana < before.mana)
                spell_paid = (before.has_fresh_readings("spell_mana")
                              and after.has_fresh_readings("spell_mana")
                              and before.spell_mana is not None and after.spell_mana is not None
                              and after.spell_mana < before.spell_mana)
                damaged = (before.has_fresh_readings("enemy_nexus_hp")
                           and after.has_fresh_readings("enemy_nexus_hp")
                           and after.enemy_nexus_hp < before.enemy_nexus_hp)
                if not after.hand_expanded:
                    # 展开与收起视图的可见牌数不可直接比较；确认结算后仅凭
                    # 新鲜伤害且回到己方行动核验，不以法力回填或视图变化放行。
                    return after.ui_state is UIState.MY_TURN_IDLE and damaged
                return len(after.hand) < len(before.hand) and (mana_paid or spell_paid or damaged)

            return PlayExpectation(verify_rocket, "jinx_rocket_payment_or_damage_verified", 20.0)
        if card.name != "吉茵珂絲":
            return None

        def verify(after: GameState) -> bool:
            if (after.ui_state not in (UIState.MY_TURN_IDLE, UIState.ENEMY_TURN)
                    or len(after.my_units) <= len(before.my_units)
                    or len(after.hand) != len(before.hand) + 1):
                return False
            paid = (card.cost > 0 and before.has_fresh_readings("mana")
                    and after.has_fresh_readings("mana")
                    and before.mana - after.mana >= card.cost)
            generated = (sum(c.name in ROCKET_NAMES for c in after.hand) == 2
                         and all(c.name in ROCKET_NAMES | POW_POW_NAMES for c in after.hand))
            # 数量增加或露出旧单位本身不足以证明召唤，还需支付或生成牌依据。
            return paid or generated

        return PlayExpectation(verify, "jinx_hand_rebuilt_and_summoned", 20.0)

    def on_action_outcome(self, action: Action, before: GameState, after: GameState) -> None:
        """只在执行器确认动作成功后推进；展开手牌不算出牌。"""
        if action.type is not ActionType.PLAY_CARD or not before.hand_expanded:
            return
        card = next((c for c in before.hand if c.index == action.card_index), None)
        if card is None:
            return
        if card.name == "吉茵珂絲" and card.cost >= 0:
            # 已通过专属后验；旧场面基线可能受手牌遮挡，不能再次否定结果。
            self.step = 2
            self._rockets_played = 0
        elif self.step == 2:
            if action.raw.get("jinx_rocket") is True and card.name in ROCKET_NAMES:
                self._rockets_played += 1
        elif self.step == 0 and card.name == "應急裝置" and 0 <= card.cost <= 3:
            if self._board_before is not None and len(after.my_units) > self._board_before:
                self.step = 1
            else:
                self._awaiting_crab = True
