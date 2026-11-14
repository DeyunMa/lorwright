"""动作后的可见结果：等待新帧，不把输入已发送当作动作已成功。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from lorwright.models import Action, ActionType, GameState, UIState


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
    ) -> None:
        self.action = action
        self.before = before
        self.deadline = deadline
        self.combat_row_min_move_px = combat_row_min_move_px

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
                if not before.hand_expanded:
                    if known and after.hand_expanded:
                        reason = "hand_expanded"
                elif after.ui_state is UIState.TARGETING:
                    return Outcome(OutcomeStatus.NEEDS_INPUT, "target_selection_required")
                elif (before.ui_state is UIState.MY_TURN_IDLE
                      and after.ui_state is UIState.COMBAT_RESOLVING):
                    # 慢速法术先进入堆栈，要点「確認」后才会真正结算。
                    return Outcome(OutcomeStatus.NEEDS_INPUT, "confirmation_required")
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
            elif kind in (ActionType.SELECT_TARGET, ActionType.CANCEL):
                if before.ui_state is UIState.TARGETING and after.ui_state is not UIState.TARGETING:
                    reason = "targeting_closed"
            elif kind is ActionType.CONTINUE:
                if after.ui_state is not before.ui_state:
                    reason = "ui_transition"
            elif kind in (ActionType.CONFIRM, ActionType.END_TURN, ActionType.PASS):
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
