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
    ) -> None:
        self.action = action
        self.before = before
        self.deadline = deadline
        self.combat_row_min_move_px = combat_row_min_move_px
        self.play_expectation = play_expectation
        self._confirmation_completed = False

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
        known = after.ui_state is not UIState.UNKNOWN
        reason = ""
        # UNKNOWN 动画期间仅凭单位数量增加不够：收起的手牌可能露出原有单位。
        if known or kind is ActionType.PLAY_CARD:
            if kind is ActionType.PLAY_CARD:
                if after.ui_state is UIState.DISCARD:
                    return Outcome(OutcomeStatus.NEEDS_INPUT, "discard_selection_required")
                if after.ui_state is UIState.OPTIONAL_CHOICE:
                    return Outcome(OutcomeStatus.NEEDS_INPUT, "optional_choice_required")
                if after.ui_state is UIState.TARGETING:
                    return Outcome(OutcomeStatus.NEEDS_INPUT, "target_selection_required")
                if not before.hand_expanded:
                    if (after.ui_state is UIState.COMBAT_RESOLVING
                            and after.action_prompt in {"action_confirm", "action_commit"}):
                        # 只点过展开，可能被对手技能打断；交给确认策略，
                        # 不把原动作记为成功或暂存为已拖出的待确认牌。
                        return Outcome(OutcomeStatus.NEEDS_INPUT, "hand_expansion_interrupted")
                    if known and after.hand_expanded:
                        reason = "hand_expanded"
                elif (not self._confirmation_completed
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
            elif kind in (ActionType.SELECT_TARGET, ActionType.CANCEL):
                if before.ui_state is UIState.TARGETING and after.ui_state is not UIState.TARGETING:
                    reason = "targeting_closed"
            elif kind is ActionType.CONTINUE:
                if after.ui_state is not before.ui_state:
                    reason = "ui_transition"
            elif kind in (ActionType.CONFIRM, ActionType.END_TURN, ActionType.PASS):
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
