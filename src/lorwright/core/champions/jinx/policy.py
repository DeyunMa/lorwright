"""用户指定的起手：應急裝置 → 减费 Jinx → 打掉 Jinx 生成的飞逝牌。"""

from lorwright.core.decide.base import PlayExpectation
from lorwright.core.decide.card import CardKind
from lorwright.core.decide.generic import board_count
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
    """跳过地标，单位优先，同组先比已核验的费用，同费再比品质。"""
    eligible = [c for c in candidates if c.kind is not None and c.kind is not CardKind.LANDMARK]
    units = [c for c in eligible if c.kind.is_unit]
    pool = units or eligible
    if not pool:
        return None
    reason = "Jinx：单位优先，再比费用，同费选高品质"
    if len(pool) == 1:
        return CardRewardPick(pool[0], reason)
    if any(
        c.card.cost is None or c.card.cost < 0 or not (c.cost_certain or c.preview_cost_verified)
        for c in pool
    ):
        return None
    chosen = min(pool, key=lambda c: (c.card.cost, -QUALITY_RANK.get(c.card.quality, -2)))
    return CardRewardPick(chosen, reason)


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
        self._mulligan_targets: tuple[bool | None, ...] | None = None
        self._awaiting_crab = False
        self._board_before: int | None = None
        self._last_opening_view = None
        self._stable_views = 0
        #: 本次 Jinx 下场后已经打出的火箭数；用户要求最多打 2 次。
        self._rockets_played = rockets_already_played
        self._cancelled_pow_pow_mana: int | None = None

    def decide(self, state: GameState) -> Action | None:
        if state.ui_state in (UIState.MULLIGAN, UIState.ENEMY_TURN, UIState.BLOCKING):
            self._cancelled_pow_pow_mana = None
        elif (self._cancelled_pow_pow_mana is not None
              and self._cancelled_pow_pow_mana >= 0 and state.has_fresh_readings("mana")
              and state.mana > self._cancelled_pow_pow_mana):
            self._cancelled_pow_pow_mana = None
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
                # 选中特效会遮挡卡面；只在四槽均未选中时建立判断。
                # 未知身份保留，不阻塞其他槽位；重启后不猜已选中的牌。
                if any(selected):
                    return Action(type=ActionType.NO_OP)
                self._mulligan_targets = observed
            elif any(
                not selected[i] and self._mulligan_targets[i] is not None
                and observed[i] != self._mulligan_targets[i]
                and (self._mulligan_targets[i] is True or observed[i] is not None)
                for i in range(4)
            ):
                return Action(type=ActionType.NO_OP)
            heroes = [i for i, matches in enumerate(self._mulligan_targets) if matches]
            # 有 Jinx 时只替换多余 Jinx；否则替换已知非目标，保留未知。
            desired = set(heroes[1:]) if heroes else {
                i for i, matches in enumerate(self._mulligan_targets) if matches is False
            }
            for card, current in zip(cards, selected, strict=True):
                target = card.index in desired
                if current != target:
                    # 当前卡面暂时不可读时保留这张，其他槽仍由各自的两帧证据核验。
                    if target and card.matches_target is None:
                        continue
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
            # 先展开重新识别，出牌由后续新帧决策。
            if state.hand:
                return Action(type=ActionType.EXPAND_HAND)
            return None
        if self.step == 0:
            available = max(0, state.mana) + (state.spell_mana or 0)
            matches = [card for card in state.hand if card.name == "應急裝置"
                       and card.drag_point_valid and board_count(state) < 6
                       and 0 <= card.cost <= 3 and card.cost <= available]
        else:
            matches = [card for card in state.hand if card.name == "吉茵珂絲"
                       and card.drag_point_valid and board_count(state) < 6
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
        if state.enemy_units and self._cancelled_pow_pow_mana is None:
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
        """展开态核验重建；收起态以新鲜支付及卡面或伤害交叉核验。"""
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
                    # 跨视图牌数不可比较；前后资源读数均新鲜且总额减少覆盖
                    # 实际费用时可独立核验支付，资源回填不能伪装成净支付。
                    paid = (card.cost > 0
                            and before.has_fresh_readings("mana", "spell_mana")
                            and after.has_fresh_readings("mana", "spell_mana")
                            and before.spell_mana is not None and after.spell_mana is not None
                            and before.mana + before.spell_mana - after.mana - after.spell_mana
                            >= card.cost)
                    return after.ui_state is UIState.MY_TURN_IDLE and (damaged or paid)
                return len(after.hand) < len(before.hand) and (mana_paid or spell_paid or damaged)

            return PlayExpectation(verify_rocket, "jinx_rocket_payment_or_damage_verified", 20.0)
        if card.name != "吉茵珂絲":
            return None

        def verify(after: GameState) -> bool:
            if (after.ui_state not in (UIState.MY_TURN_IDLE, UIState.ENEMY_TURN)
                    or len(after.my_units) <= len(before.my_units)):
                return False
            paid = (card.cost > 0 and before.has_fresh_readings("mana")
                    and after.has_fresh_readings("mana")
                    and before.mana - after.mana >= card.cost)
            if not after.hand_expanded:
                # 跨视图牌数不比较。支付须再有明确 Jinx 卡面或新鲜伤害，
                # 对手回血可能抵消伤害。
                damaged = (before.has_fresh_readings("enemy_nexus_hp")
                           and after.has_fresh_readings("enemy_nexus_hp")
                           and after.enemy_nexus_hp < before.enemy_nexus_hp)
                visible_jinx = any(unit.name == "吉茵珂絲" for unit in after.my_units)
                if card.cost <= 0:
                    # 零费落地没有支付证据；同名单位新上场即落地，
                    # 仅凭伤害不够（实机 20261121T061713 费用读作 0 而 Jinx 已上桌）。
                    new_named = visible_jinx and not any(
                        unit.name == "吉茵珂絲" for unit in before.my_units)
                    return after.ui_state is UIState.MY_TURN_IDLE and new_named
                return after.ui_state is UIState.MY_TURN_IDLE and paid and (damaged or visible_jinx)
            generated = (sum(c.name in ROCKET_NAMES for c in after.hand) == 2
                         and all(c.name in ROCKET_NAMES | POW_POW_NAMES for c in after.hand))
            # 同为展开态仍要求重建数量，并有支付或生成牌身份作为独立依据。
            return len(after.hand) == len(before.hand) + 1 and (paid or generated)

        return PlayExpectation(verify, "jinx_hand_rebuilt_and_summoned", 20.0)

    def on_action_outcome(self, action: Action, before: GameState, after: GameState) -> None:
        """只在执行器确认动作成功后推进；展开手牌不算出牌。"""
        if (action.type is ActionType.CANCEL and action.raw.get("return_to_hand")
                and before.targeted_spell is not None
                and before.targeted_spell.name in POW_POW_NAMES
                and after.ui_state is UIState.MY_TURN_IDLE):
            # 本轮无可核验目标时先让出优先级，避免取消后又打出同一法术。
            self._cancelled_pow_pow_mana = before.mana if before.has_fresh_readings("mana") else -1
            return
        if action.type is not ActionType.PLAY_CARD or not before.hand_expanded:
            return
        card = next((c for c in before.hand if c.index == action.card_index), None)
        if card is None:
            return
        if card.name == "吉茵珂絲" and card.cost >= 0:
            # 已通过专属后验；旧场面基线可能受手牌遮挡，不能再次否定结果。
            self.step = 2
            self._rockets_played = 0
            self._cancelled_pow_pow_mana = None
        elif self.step == 2:
            if action.raw.get("jinx_rocket") is True and card.name in ROCKET_NAMES:
                self._rockets_played += 1
        elif self.step == 0 and card.name == "應急裝置" and 0 <= card.cost <= 3:
            if self._board_before is not None and len(after.my_units) > self._board_before:
                self.step = 1
            else:
                self._awaiting_crab = True
