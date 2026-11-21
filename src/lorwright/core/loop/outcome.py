"""动作后的可见结果：等待新帧，不把输入已发送当作动作已成功。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from lorwright.core.decide.base import PlayExpectation
from lorwright.core.models import Action, ActionType, GameState, UIState


@dataclass(frozen=True)
class LoopResult:
    """循环退出事实；battle_end 不代表战斗获胜。"""

    status: str
    reason: str


class OutcomeStatus(StrEnum):
    WAITING = "waiting"
    SUCCEEDED = "succeeded"
    NEEDS_INPUT = "needs_input"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True)
class Outcome:
    status: OutcomeStatus
    reason: str


class ActionOutcome:
    """一次已执行动作的观察窗口；超时仅说明没有取得足够证据。

    攻击/格挡只确认所选单位进入另一行，不证明格挡合法或战斗获胜。
    时钟由调用方传入，便于用连续状态确定性回归。
    """

    def __init__(
        self, action: Action, before: GameState, deadline: float,
        combat_row_min_move_px: int = 80,
        play_expectation: PlayExpectation | None = None,
        unacknowledged_deadline: float | None = None,
    ) -> None:
        self.action = action
        self.before = before
        self.deadline = deadline
        self.combat_row_min_move_px = combat_row_min_move_px
        self.play_expectation = play_expectation
        self._confirmation_completed = False
        #: 输入被游戏吞掉的重路由点：画面保持原样、按钮仍可读时，
        #: 在这个单调时钟点之前提前交回决策，不等满动作窗口。
        self._unacknowledged_deadline = unacknowledged_deadline

    def resume_after_confirmation(self) -> None:
        """确认交互已结束，沿用原观察窗口等待出牌结果。"""
        self._confirmation_completed = True

    def observe(self, after: GameState, now: float) -> Outcome:
        if now >= self.deadline:
            return Outcome(OutcomeStatus.TIMED_OUT, "no_verified_result_before_deadline")
        before = self.before
        kind = self.action.type
        if kind is ActionType.MULLIGAN_REPLACE:
            index = self.action.raw.get("mulligan_index")
            target = self.action.raw.get("selected")
            previous = before.mulligan_selected
            current = after.mulligan_selected
            if (before.ui_state is UIState.MULLIGAN and after.ui_state is UIState.MULLIGAN
                    and isinstance(index, int) and not isinstance(index, bool) and 0 <= index < 4
                    and isinstance(target, bool) and len(previous) == len(current) == 4
                    and all(value is not None for value in (*previous, *current))
                    and previous[index] is not target and current[index] is target
                    and all(previous[i] == current[i] for i in range(4) if i != index)):
                return Outcome(OutcomeStatus.SUCCEEDED, "mulligan_selection_changed")
            return Outcome(OutcomeStatus.WAITING, "awaiting_mulligan_selection")
        if kind is ActionType.EXPAND_HAND:
            if before.ui_state is UIState.MY_TURN_IDLE and not before.hand_expanded and before.hand:
                if (after.ui_state is UIState.COMBAT_RESOLVING
                        and after.action_prompt in {"action_confirm", "action_commit"}):
                    return Outcome(OutcomeStatus.NEEDS_INPUT, "hand_expansion_interrupted")
                if after.ui_state is UIState.MY_TURN_IDLE and after.hand_expanded and after.hand:
                    return Outcome(OutcomeStatus.SUCCEEDED, "hand_expanded")
            return Outcome(OutcomeStatus.WAITING, "awaiting_hand_expansion")
        if kind is ActionType.PLAY_CARD and not before.hand_expanded:
            return Outcome(OutcomeStatus.WAITING, "play_requires_expanded_hand")
        known = after.ui_state is not UIState.UNKNOWN
        reason = ""
        # UNKNOWN 动画期间仅凭单位数量增加不够：收起的手牌可能露出原有单位。
        if known or kind is ActionType.PLAY_CARD:
            if kind is ActionType.PLAY_CARD:
                if after.ui_state is UIState.DISCARD:
                    return Outcome(OutcomeStatus.NEEDS_INPUT, "discard_selection_required")
                if after.ui_state is UIState.OPTIONAL_CHOICE:
                    return Outcome(OutcomeStatus.NEEDS_INPUT, "optional_choice_required")
                if after.ui_state is UIState.REQUIRED_CHOICE:
                    return Outcome(OutcomeStatus.NEEDS_INPUT, "required_choice_required")
                if after.ui_state is UIState.TARGETING:
                    return Outcome(OutcomeStatus.NEEDS_INPUT, "target_selection_required")
                if (not self._confirmation_completed
                      and before.ui_state is UIState.MY_TURN_IDLE
                      and after.ui_state is UIState.COMBAT_RESOLVING):
                    # 慢速法术先进入堆栈，要点「確認」后才会真正结算。
                    return Outcome(OutcomeStatus.NEEDS_INPUT, "confirmation_required")
                elif self.play_expectation is not None:
                    if self.play_expectation.verify(after):
                        reason = self.play_expectation.reason
                elif len(after.hand) < len(before.hand) and (
                    (before.has_fresh_readings("mana") and after.has_fresh_readings("mana")
                     and after.mana < before.mana)
                    or (before.has_fresh_readings("spell_mana")
                        and after.has_fresh_readings("spell_mana")
                        and before.spell_mana is not None and after.spell_mana is not None
                        and after.spell_mana < before.spell_mana)
                    # 手牌打空后展开态会变成 False；只要手牌减少且场面增加，
                    # 仍是“打出了单位”，不能因为手牌收起就判失败。
                    or (known and len(after.my_units) > len(before.my_units))
                ):
                    reason = "hand_reduced_and_mana_or_board_changed"
                elif (before.ui_state is after.ui_state is UIState.MY_TURN_IDLE
                      and not after.hand_expanded
                      and before.has_fresh_readings("mana", "spell_mana")
                      and after.has_fresh_readings("mana", "spell_mana")
                      and before.spell_mana is not None and after.spell_mana is not None
                      and after.mana > before.mana
                      and after.mana + after.spell_mana > before.mana + before.spell_mana):
                    # 跨视图牌数不可比较，资源回填又掩盖了支付；新鲜行动页
                    # 只支持重新决策，不通知出牌成功或推进英雄阶段。
                    return Outcome(OutcomeStatus.NEEDS_INPUT,
                                   "play_result_obscured_by_resource_refill")
                elif self._unit_landed(before, after):
                    reason = "unit_landed_on_board"
                elif (self._unacknowledged_deadline is not None
                      and now >= self._unacknowledged_deadline
                      and before.ui_state is after.ui_state is UIState.MY_TURN_IDLE
                      and len(after.hand) == len(before.hand)
                      and after.mana == before.mana
                      and len(after.my_units) == len(before.my_units)
                      and len(after.enemy_units) == len(before.enemy_units)):
                    # 拖拽被游戏吞掉：宽限内画面像素级不变、卡仍在手，
                    # 重路由让决策层按当前牌位重算起点再拖一次（实机
                    # 20261121T135644 尖嘯蜘蛛 20s 无变化）。手牌自动收起
                    # 与法术力读数抖动与出牌结果无关，不纳入判等；出牌
                    # 生效（手牌减少/法力支付/单位上场）不会判成未确认。
                    # 连续无进展由 watchdog 兜底。
                    return Outcome(OutcomeStatus.NEEDS_INPUT, "play_unacknowledged")
            elif kind is ActionType.DISCARD_CARD:
                if (before.ui_state is UIState.DISCARD and after.ui_state in {
                    UIState.MY_TURN_IDLE, UIState.ENEMY_TURN, UIState.COMBAT_RESOLVING,
                    UIState.BLOCKING, UIState.TARGETING, UIState.BATTLE_END,
                }):
                    reason = "discard_selection_closed"
            elif kind is ActionType.SKIP_CHOICE:
                if (before.ui_state is UIState.OPTIONAL_CHOICE and after.ui_state in {
                    UIState.MY_TURN_IDLE, UIState.ENEMY_TURN, UIState.COMBAT_RESOLVING,
                    UIState.BLOCKING, UIState.TARGETING, UIState.BATTLE_END,
                }):
                    reason = "optional_choice_closed"
            elif kind is ActionType.PICK_CHOICE:
                if (before.ui_state is UIState.REQUIRED_CHOICE and after.ui_state in {
                    UIState.MY_TURN_IDLE, UIState.ENEMY_TURN, UIState.COMBAT_RESOLVING,
                    UIState.BLOCKING, UIState.TARGETING, UIState.BATTLE_END,
                }):
                    reason = "required_choice_closed"
            elif kind is ActionType.COLLAPSE_HAND:
                if (before.ui_state is UIState.MY_TURN_IDLE and before.hand_expanded
                        and after.ui_state is UIState.MY_TURN_IDLE and not after.hand_expanded):
                    reason = "hand_collapsed"
            elif kind in (ActionType.ATTACK, ActionType.BLOCK):
                # 按 x 排列的单位在声明后可能重新排位，不能把列表下标当身份。
                # 比较攻击行人数的净增长；阈值取前后己方单位两行的中点。
                wanted = (self.action.raw.get("attackers", []) if kind is ActionType.ATTACK
                          else [p[0] for p in self.action.raw.get("pairs", [])])
                if kind is ActionType.ATTACK and not wanted:
                    wanted = [i for i, u in enumerate(before.my_units) if u.can_attack][:1]
                selected = [before.my_units[i] for i in set(wanted)
                            if 0 <= i < len(before.my_units)]
                if selected and len(selected) == len(set(wanted)) and len(after.my_units) == len(before.my_units):
                    # 只接受足够大的上移，不把几像素抖动算声明成功。
                    baseline = min(u.rect.center[1] for u in selected)
                    cutoff = baseline - self.combat_row_min_move_px
                    old_count = sum(u.rect.center[1] < cutoff for u in before.my_units)
                    new_count = sum(u.rect.center[1] < cutoff for u in after.my_units)
                    if new_count - old_count >= len(selected):
                        reason = "selected_units_moved_to_combat_row"
                if not reason and known and after.ui_state is UIState.COMBAT_RESOLVING and before.ui_state is not after.ui_state:
                    reason = "combat_ui_transition"
                if (kind is ActionType.BLOCK and not reason
                        and self._unacknowledged_deadline is not None
                        and now >= self._unacknowledged_deadline
                        and before.ui_state is after.ui_state is UIState.BLOCKING
                        and selected):
                    # 格挡拖拽被吞：没有任何我方单位进入格挡行（实机
                    # 20261121T143406 单位停在备战行 8s）。重路由让策略
                    # 按当前位置重算指派重拖；已落地的指派不走到这里。
                    cutoff = min(u.rect.center[1] for u in selected) - self.combat_row_min_move_px
                    if not any(u.rect.center[1] < cutoff for u in after.my_units):
                        return Outcome(OutcomeStatus.NEEDS_INPUT,
                                       "block_unacknowledged")
            elif kind in (ActionType.SELECT_TARGET, ActionType.CANCEL):
                if before.ui_state is UIState.TARGETING and after.ui_state is not UIState.TARGETING:
                    reason = "targeting_closed"
                elif (kind is ActionType.SELECT_TARGET
                      and before.ui_state is after.ui_state is UIState.TARGETING
                      and (after.replace_prompt != before.replace_prompt
                           or after.action_prompt != before.action_prompt
                           or after.spell_options != before.spell_options)):
                    # 同为 TARGETING 但提示身份变了：实机 20261121T134723
                    # 满场替换点选后紧接出牌可选效果的选目标，原选择已被
                    # 消费，需要重新路由处理新提示（不可只靠枚举变化判完成）。
                    return Outcome(OutcomeStatus.NEEDS_INPUT,
                                   "targeting_context_changed")
            elif kind is ActionType.CONTINUE:
                if after.ui_state is not before.ui_state:
                    reason = "ui_transition"
            elif kind in (ActionType.CONFIRM, ActionType.END_TURN, ActionType.PASS):
                if (kind is ActionType.CONFIRM
                        and before.ui_state is after.ui_state is UIState.MULLIGAN
                        and self._unacknowledged_deadline is not None
                        and now >= self._unacknowledged_deadline
                        and len(after.mulligan_selected) == 4
                        and all(type(value) is bool
                                for value in after.mulligan_selected)):
                    # 「確定」被吞：画面未变且四个替換/取消按钮仍可读。
                    # 换牌确认是幂等单按钮，重路由让决策层再发一次；
                    # 重复无变化由 watchdog 的卡死升级兜底。按钮读不出
                    # 的帧可能在转场中，重发会落到别的界面，保持等待。
                    return Outcome(OutcomeStatus.NEEDS_INPUT,
                                   "mulligan_confirm_unacknowledged")
                if (kind is ActionType.CONFIRM
                        and before.ui_state is after.ui_state is UIState.COMBAT_RESOLVING
                        and before.action_prompt == after.action_prompt == "action_confirm"
                        and self._unacknowledged_deadline is not None
                        and now >= self._unacknowledged_deadline):
                    # 「確認」被吞：提示未变（实机 20261121T143042 攻击确认
                    # 点击后 action_confirm 停 21 秒）。单按钮幂等，重路由
                    # 重发；提示变了说明在结算/新阶段，走上面的既有分支。
                    return Outcome(OutcomeStatus.NEEDS_INPUT,
                                   "confirm_unacknowledged")
                if (kind is ActionType.CONFIRM
                        and before.ui_state is after.ui_state is UIState.COMBAT_RESOLVING
                        and {before.action_prompt, after.action_prompt}
                        == {"action_confirm", "action_commit"}):
                    # 攻击声明与堆栈结算共用状态；新提示需要重新路由，
                    # 不能把尚待结算的原出牌提前通知为成功。
                    return Outcome(OutcomeStatus.NEEDS_INPUT, "confirmation_prompt_changed")
                if (kind is ActionType.CONFIRM
                        and before.ui_state is after.ui_state is UIState.COMBAT_RESOLVING
                        and before.action_prompt == after.action_prompt == "action_commit"
                        and any(before.has_fresh_readings(name)
                                and after.has_fresh_readings(name)
                                and getattr(after, name) < getattr(before, name)
                                for name in ("enemy_nexus_hp", "nexus_hp"))):
                    # 伤害已结算但仍有后续堆栈；重新核验按钮，不宣告父出牌完成。
                    return Outcome(OutcomeStatus.NEEDS_INPUT, "stack_progressed_confirmation_required")
                previous = before.readings.get("enemy_units_visible")
                current = after.readings.get("enemy_units_visible")
                if (kind in (ActionType.END_TURN, ActionType.PASS)
                        and before.ui_state is after.ui_state is UIState.MY_TURN_IDLE
                        and before.hand_expanded == after.hand_expanded
                        and previous is not None and current is not None and current.fresh
                        and current.value == len(after.enemy_units)
                        and len(after.enemy_units) > len(before.enemy_units)
                        and ((previous.fresh and previous.value == len(before.enemy_units))
                             or (previous.value is None and not before.enemy_units))):
                    # 新检出的单位提供重新决策的依据，不证明上次是空场或交回优先权。
                    return Outcome(OutcomeStatus.NEEDS_INPUT, "opponent_unit_appeared")
                if after.ui_state is not before.ui_state:
                    reason = "ui_transition"
                elif (before.has_fresh_readings("mana") and after.has_fresh_readings("mana")
                      and after.mana > before.mana):
                    reason = "new_mana_observed"
                elif (kind is ActionType.CONFIRM
                      and before.has_attack_token and not after.has_attack_token
                      and before.my_units and after.my_units
                      and min(u.rect.center[1] for u in after.my_units)
                      > min(u.rect.center[1] for u in before.my_units) + self.combat_row_min_move_px):
                    reason = "attack_token_spent_and_units_returned"
        if reason:
            return Outcome(OutcomeStatus.SUCCEEDED, reason)
        return Outcome(OutcomeStatus.WAITING, "awaiting_visible_result")

    def _unit_landed(self, before: GameState, after: GameState) -> bool:
        """打出单位的落地核验：收起的展开态不能比牌数、零费也没有支付，
        但己方场面单位数在已知界面下净增，且所打之牌本身是已确认单位，
        或同名单位新上桌（如吉茵珂絲），即可证明落地而非无变化。
        """
        if after.ui_state not in {UIState.MY_TURN_IDLE, UIState.ENEMY_TURN,
                                  UIState.BLOCKING}:
            return False
        if len(after.my_units) <= len(before.my_units):
            return False
        card = next((c for c in before.hand
                     if c.index == self.action.card_index), None)
        if card is None:
            return False
        if card.visible_playable_unit or self.action.raw.get("unit_card") is True:
            return True
        return bool(card.name) and (
            any(unit.name == card.name for unit in after.my_units)
            and not any(unit.name == card.name for unit in before.my_units))
