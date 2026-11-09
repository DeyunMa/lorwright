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
            # 换牌点击没有稳定的「成功」画面；点击已按计划发出，下一步由
            # 策略点「確定」，不能再等一个不存在的状态变化。
            return Outcome(OutcomeStatus.SUCCEEDED, "mulligan_replace_sent")
        known = after.ui_state is not UIState.UNKNOWN
        reason = ""
        # 出牌动画期间 UI 可能短暂 UNKNOWN，但手牌减少 + 场面增加/费用下降
        # 仍是可验证的可见结果；不能让动画把动作拖到超时。
        if known or kind is ActionType.PLAY_CARD:
            if kind is ActionType.PLAY_CARD:
                if not before.hand_expanded:
                    if known and after.hand_expanded:
                        reason = "hand_expanded"
                elif after.ui_state is UIState.TARGETING:
                    return Outcome(OutcomeStatus.NEEDS_INPUT, "target_selection_required")
                elif len(after.hand) < len(before.hand) and (
                    (before.has_fresh_readings("mana") and after.has_fresh_readings("mana")
                     and after.mana < before.mana)
                    # 手牌打空后展开态会变成 False；只要手牌减少且场面增加，
                    # 仍是“打出了单位”，不能因为手牌收起就判失败。
                    or len(after.my_units) > len(before.my_units)
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
