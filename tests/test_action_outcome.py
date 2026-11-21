"""结果验证不能把展开、动画、丢帧或部分拖拽当成动作完成。"""

from dataclasses import replace

import pytest

from lorwright.core.loop.outcome import ActionOutcome, OutcomeStatus
from lorwright.core.models import (
    Action,
    ActionType,
    CardInHand,
    GameState,
    Reading,
    Rect,
    UIState,
    Unit,
)


def state(**kwargs):
    defaults = dict(
        ui_state=UIState.MY_TURN_IDLE, mana=3, hand_expanded=True,
        hand=[CardInHand(i, "", 1, Rect(100 * i, 900, 20, 20)) for i in range(2)],
        readings={"mana": Reading(3, 0)},
    )
    defaults.update(kwargs)
    return GameState(**defaults)


def test_play_cross_view_resource_refill_reroutes_without_claiming_success():
    # seq220→252 的资源/视图模式；没有中间实拍，不能推断支付或出牌成功。
    before = state(mana=0, spell_mana=3,
                   readings={"mana": Reading(0, 0), "spell_mana": Reading(3, 0)})
    after = state(mana=4, spell_mana=3, hand_expanded=False,
                  readings={"mana": Reading(4, 0), "spell_mana": Reading(3, 0)})
    pending = ActionOutcome(Action(ActionType.PLAY_CARD, 0), before, 8)
    outcome = pending.observe(after, 7.6)
    assert outcome.status is OutcomeStatus.NEEDS_INPUT
    assert outcome.reason == "play_result_obscured_by_resource_refill"
    assert pending.observe(after, 8).status is OutcomeStatus.TIMED_OUT


@pytest.mark.parametrize("change", ["unknown", "before_stale", "after_stale", "missing_spell",
                                    "no_refill", "no_net_refill", "same_view"])
def test_play_resource_refill_reroute_requires_fresh_cross_view_evidence(change):
    before = state(mana=0, spell_mana=3,
                   readings={"mana": Reading(0, 0), "spell_mana": Reading(3, 0)})
    after = state(mana=4, spell_mana=3, hand_expanded=False, my_units=units(850, 850),
                  readings={"mana": Reading(4, 0), "spell_mana": Reading(3, 0)})
    if change == "unknown":
        after = replace(after, ui_state=UIState.UNKNOWN)
    elif change == "before_stale":
        before = replace(before, readings={"mana": Reading(0, 1), "spell_mana": Reading(3, 0)})
    elif change == "after_stale":
        after = replace(after, readings={"mana": Reading(4, 0), "spell_mana": Reading(3, 1)})
    elif change == "missing_spell":
        after = replace(after, spell_mana=None, readings={"mana": Reading(4, 0)})
    elif change == "no_refill":
        after = replace(after, mana=0, readings=before.readings)
    elif change == "no_net_refill":
        after = replace(after, mana=2, spell_mana=1,
                        readings={"mana": Reading(2, 0), "spell_mana": Reading(1, 0)})
    else:
        after = replace(after, hand_expanded=True)
    pending = ActionOutcome(Action(ActionType.PLAY_CARD, 0), before, 8)
    assert pending.observe(after, 7).status is OutcomeStatus.WAITING


def test_resource_refill_does_not_bypass_special_play_expectation():
    from lorwright.core.decide.base import PlayExpectation

    before = state(mana=0, spell_mana=3,
                   readings={"mana": Reading(0, 0), "spell_mana": Reading(3, 0)})
    after = state(mana=4, spell_mana=3, hand_expanded=False,
                  readings={"mana": Reading(4, 0), "spell_mana": Reading(3, 0)})
    pending = ActionOutcome(Action(ActionType.PLAY_CARD, 0), before, 8,
                            play_expectation=PlayExpectation(lambda _: False, "specific", 8))
    assert pending.observe(after, 7.6).status is OutcomeStatus.WAITING
    assert pending.observe(after, 8).status is OutcomeStatus.TIMED_OUT


def test_play_yields_to_discard_without_notifying_play_success():
    before = state()
    after = state(ui_state=UIState.DISCARD, hand=[])
    result = ActionOutcome(Action(ActionType.PLAY_CARD, card_index=0), before, 8).observe(after, 1)
    assert result.status is OutcomeStatus.NEEDS_INPUT
    assert result.reason == "discard_selection_required"


@pytest.mark.parametrize("ui", [UIState.UNKNOWN, UIState.DISCARD, UIState.MULLIGAN,
                                UIState.OPTIONAL_CHOICE])
def test_discard_does_not_accept_unknown_or_unrelated_interactions(ui):
    outcome = ActionOutcome(Action(ActionType.DISCARD_CARD, card_index=0),
                            state(ui_state=UIState.DISCARD), 8)
    assert outcome.observe(state(ui_state=ui), 1).status is OutcomeStatus.WAITING
    assert outcome.observe(state(), 8).status is OutcomeStatus.TIMED_OUT


def units(*ys):
    return [Unit("", -1, -1, Rect(i * 150, y, 8, 8)) for i, y in enumerate(ys)]


@pytest.mark.parametrize("kind", [ActionType.END_TURN, ActionType.PASS])
@pytest.mark.parametrize("previous_count", [0, 1, 3])
def test_pass_reroutes_when_more_opponent_units_are_observed(kind, previous_count):
    before = state(enemy_units=units(*([100] * previous_count)), readings={
        "enemy_units_visible": Reading(previous_count or None, 0 if previous_count else None),
    })
    after = state(enemy_units=units(*([100] * (previous_count + 1))), readings={
        "enemy_units_visible": Reading(previous_count + 1, 0),
    })
    outcome = ActionOutcome(Action(kind), before, 8).observe(after, 1)
    assert outcome.status is OutcomeStatus.NEEDS_INPUT
    assert outcome.reason == "opponent_unit_appeared"


@pytest.mark.parametrize("change", [
    "unknown", "view", "unchanged", "confirm", "missing", "stale", "mismatch", "prior_stale",
])
def test_opponent_unit_reroute_requires_current_visible_evidence(change):
    before = state(enemy_units=units(100), readings={"enemy_units_visible": Reading(1, 0)})
    after = state(enemy_units=units(100, 100), readings={"enemy_units_visible": Reading(2, 0)})
    kind = ActionType.END_TURN
    if change == "unknown":
        after = replace(after, ui_state=UIState.UNKNOWN)
    elif change == "view":
        after = replace(after, hand_expanded=False)
    elif change == "unchanged":
        after = before
    elif change == "missing":
        after = replace(after, readings={})
    elif change == "stale":
        after = replace(after, readings={"enemy_units_visible": Reading(2, 1)})
    elif change == "mismatch":
        after = replace(after, readings={"enemy_units_visible": Reading(1, 0)})
    elif change == "prior_stale":
        before = replace(before, readings={"enemy_units_visible": Reading(1, 1)})
    else:
        kind = ActionType.CONFIRM
    pending = ActionOutcome(Action(kind), before, 8)
    assert pending.observe(after, 1).status is OutcomeStatus.WAITING
    assert pending.observe(after, 8).status is OutcomeStatus.TIMED_OUT


def test_expanding_is_a_separate_step_from_playing():
    before = state(hand_expanded=False)
    pending = ActionOutcome(Action(ActionType.EXPAND_HAND), before, 8)
    assert pending.observe(before, 1).status is OutcomeStatus.WAITING
    expanded = state()
    outcome = pending.observe(expanded, 2)
    assert outcome.status is OutcomeStatus.SUCCEEDED
    assert outcome.reason == "hand_expanded"
    play = ActionOutcome(Action(ActionType.PLAY_CARD, card_index=0), expanded, 8)
    assert play.observe(expanded, 3).status is OutcomeStatus.WAITING


@pytest.mark.parametrize("ui", [UIState.MY_TURN_IDLE, UIState.TARGETING, UIState.COMBAT_RESOLVING])
def test_collapsed_play_cannot_be_verified_as_expansion_or_play(ui):
    before = state(hand_expanded=False)
    pending = ActionOutcome(Action(ActionType.PLAY_CARD, card_index=0), before, 8)
    after = state(ui_state=ui, hand=before.hand[:1], mana=2, readings={"mana": Reading(2, 0)})
    outcome = pending.observe(after, 1)
    assert outcome.status is OutcomeStatus.WAITING
    assert outcome.reason == "play_requires_expanded_hand"
    assert pending.observe(after, 8).status is OutcomeStatus.TIMED_OUT


def test_unacknowledged_mulligan_confirm_reroutes_before_deadline():
    # 会话 20261121T133319：「確定」已点、按钮仍在，画面停在换牌 21 秒。
    before = state(ui_state=UIState.MULLIGAN, mulligan_selected=(False,) * 4)
    pending = ActionOutcome(Action(ActionType.CONFIRM), before, 20,
                            unacknowledged_deadline=6)
    assert pending.observe(before, 5).status is OutcomeStatus.WAITING
    outcome = pending.observe(before, 7)
    assert outcome.status is OutcomeStatus.NEEDS_INPUT
    assert outcome.reason == "mulligan_confirm_unacknowledged"


def test_mulligan_confirm_retry_requires_legible_replace_buttons():
    before = state(ui_state=UIState.MULLIGAN, mulligan_selected=(False,) * 4)
    pending = ActionOutcome(Action(ActionType.CONFIRM), before, 20,
                            unacknowledged_deadline=6)
    blurred = replace(before, mulligan_selected=(None,) * 4)
    # 转场/模糊帧上重发可能点到别的界面；保持等待直到原截止。
    assert pending.observe(blurred, 7).status is OutcomeStatus.WAITING
    assert pending.observe(blurred, 20).status is OutcomeStatus.TIMED_OUT


def test_mulligan_confirm_without_retry_deadline_keeps_waiting():
    before = state(ui_state=UIState.MULLIGAN, mulligan_selected=(False,) * 4)
    pending = ActionOutcome(Action(ActionType.CONFIRM), before, 20)
    assert pending.observe(before, 7).status is OutcomeStatus.WAITING
    assert pending.observe(before, 20).status is OutcomeStatus.TIMED_OUT


def test_unacknowledged_deadline_ignores_non_confirm_actions():
    before = state(ui_state=UIState.MULLIGAN, mulligan_selected=(False,) * 4)
    end_turn = ActionOutcome(Action(ActionType.END_TURN), before, 20,
                             unacknowledged_deadline=6)
    assert end_turn.observe(before, 7).status is OutcomeStatus.WAITING


def test_mulligan_replace_waits_for_the_requested_selection_change():
    before = state(ui_state=UIState.MULLIGAN, mulligan_selected=(False,) * 4)
    pending = ActionOutcome(
        Action(ActionType.MULLIGAN_REPLACE, raw={"points": [(10, 20)],
                                                 "mulligan_index": 0, "selected": True}),
        before, 8,
    )
    assert pending.observe(before, 1).status is OutcomeStatus.WAITING
    assert pending.observe(replace(before, mulligan_selected=(None, False, False, False)), 2).status is (
        OutcomeStatus.WAITING
    )
    assert pending.observe(replace(before, mulligan_selected=(True, True, False, False)), 3).status is (
        OutcomeStatus.WAITING
    )
    outcome = pending.observe(replace(before, mulligan_selected=(True, False, False, False)), 4)
    assert outcome.status is OutcomeStatus.SUCCEEDED
    assert outcome.reason == "mulligan_selection_changed"


def test_play_waits_for_correlated_evidence():
    before = state()
    pending = ActionOutcome(Action(ActionType.PLAY_CARD, card_index=0), before, 8)
    # 识别漏掉一张或手牌收起，不能单独算出牌成功。
    fewer = replace(before, hand=before.hand[:1], hand_expanded=False)
    assert pending.observe(fewer, 1).status is OutcomeStatus.WAITING
    paid = replace(fewer, mana=2, readings={"mana": Reading(2, 0)})
    assert pending.observe(paid, 2).status is OutcomeStatus.SUCCEEDED


def test_stale_mana_cannot_prove_payment():
    before = state()
    after = replace(before, hand=before.hand[:1], mana=2, readings={"mana": Reading(2, 1)})
    pending = ActionOutcome(Action(ActionType.PLAY_CARD, card_index=0), before, 8)
    assert pending.observe(after, 1).status is OutcomeStatus.WAITING


def test_fresh_spell_mana_payment_can_prove_play_but_stale_cannot():
    before = state(spell_mana=2, readings={"mana": Reading(3, 0),
                                          "spell_mana": Reading(2, 0)})
    after = replace(before, hand=before.hand[:1], spell_mana=1,
                    readings={"mana": Reading(3, 0), "spell_mana": Reading(1, 0)})
    pending = ActionOutcome(Action(ActionType.PLAY_CARD, card_index=0), before, 8)
    assert pending.observe(after, 1).status is OutcomeStatus.SUCCEEDED
    stale = replace(after, readings={"mana": Reading(3, 0), "spell_mana": Reading(1, 1)})
    assert pending.observe(stale, 1).status is OutcomeStatus.WAITING
    assert pending.observe(replace(after, hand=before.hand), 1).status is OutcomeStatus.WAITING


def test_free_unit_uses_board_change_but_not_hand_representation_change():
    before = state()
    pending = ActionOutcome(Action(ActionType.PLAY_CARD, card_index=0), before, 8)
    after = replace(before, hand=before.hand[:1], my_units=units(900))
    assert pending.observe(after, 1).status is OutcomeStatus.SUCCEEDED
    # 手牌打空后展开态会变成 False；手牌减少 + 场面增加仍是成功证据。
    assert pending.observe(replace(after, hand_expanded=False), 1).status is OutcomeStatus.SUCCEEDED


def test_targeting_requires_input_instead_of_repeating_drag():
    pending = ActionOutcome(Action(ActionType.PLAY_CARD, card_index=0), state(), 8)
    assert pending.observe(state(ui_state=UIState.TARGETING), 1).status is OutcomeStatus.NEEDS_INPUT
    collapsed_after_drag = ActionOutcome(Action(ActionType.PLAY_CARD, card_index=0), state(), 8)
    assert collapsed_after_drag.observe(
        state(ui_state=UIState.TARGETING, hand_expanded=False), 1,
    ).status is OutcomeStatus.NEEDS_INPUT


@pytest.mark.parametrize("field", ["enemy_nexus_hp", "nexus_hp"])
def test_commit_yields_to_next_commit_only_with_fresh_damage(field):
    from lorwright.core.models import Reading

    before = state(ui_state=UIState.COMBAT_RESOLVING, action_prompt="action_commit",
                   readings={field: Reading(16, 0)}, **{field: 16})
    after = replace(before, readings={field: Reading(5, 0)}, **{field: 5})
    pending = ActionOutcome(Action(ActionType.CONFIRM), before, 20)
    outcome = pending.observe(after, 3)
    assert outcome.status is OutcomeStatus.NEEDS_INPUT
    assert outcome.reason == "stack_progressed_confirmation_required"
    assert pending.observe(before, 3).status is OutcomeStatus.WAITING
    assert pending.observe(replace(after, readings={field: Reading(5, 1)}), 3).status is OutcomeStatus.WAITING
    assert pending.observe(after, 20).status is OutcomeStatus.TIMED_OUT
    assert pending.deadline == 20


@pytest.mark.parametrize("prompt", ["action_confirm", "action_commit"])
def test_play_yields_to_confirmation_when_the_game_requests_it(prompt):
    before = state()
    pending = ActionOutcome(Action(ActionType.PLAY_CARD, card_index=0), before, 8)
    after = replace(before, ui_state=UIState.COMBAT_RESOLVING, action_prompt=prompt)
    assert pending.observe(after, 1).status is OutcomeStatus.NEEDS_INPUT
    # 展开被结算按钮打断，不代表已经成功拖出卡牌或完成展开。
    collapsed = replace(before, hand_expanded=False)
    expanded = ActionOutcome(Action(ActionType.EXPAND_HAND), collapsed, 8).observe(after, 1)
    assert expanded.status is OutcomeStatus.NEEDS_INPUT
    assert expanded.reason == "hand_expansion_interrupted"


@pytest.mark.parametrize("kind,raw", [
    (ActionType.ATTACK, {"attackers": [0, 1]}),
    (ActionType.BLOCK, {"pairs": [(0, 0), (1, 1)]}),
])
def test_all_selected_units_must_move(kind, raw):
    before = state(my_units=units(900, 900))
    pending = ActionOutcome(Action(kind, raw=raw), before, 8)
    assert pending.observe(replace(before, my_units=units(895, 895)), 1).status is OutcomeStatus.WAITING
    assert pending.observe(replace(before, my_units=units(700, 900)), 2).status is OutcomeStatus.WAITING
    assert pending.observe(replace(before, my_units=units(700, 700)), 3).status is OutcomeStatus.SUCCEEDED


@pytest.mark.parametrize("kind", [ActionType.SELECT_TARGET, ActionType.CANCEL])
def test_targeting_only_completes_when_selection_closes(kind):
    before = state(ui_state=UIState.TARGETING)
    pending = ActionOutcome(Action(kind), before, 8)
    assert pending.observe(before, 1).status is OutcomeStatus.WAITING
    assert pending.observe(state(), 2).status is OutcomeStatus.SUCCEEDED


@pytest.mark.parametrize("kind", [ActionType.CONFIRM, ActionType.END_TURN, ActionType.PASS])
def test_unknown_transition_is_not_confirmation(kind):
    before = state()
    pending = ActionOutcome(Action(kind), before, 8)
    assert pending.observe(state(ui_state=UIState.UNKNOWN), 1).status is OutcomeStatus.WAITING
    assert pending.observe(state(ui_state=UIState.ENEMY_TURN), 2).status is OutcomeStatus.SUCCEEDED


def test_continue_requires_a_known_transition():
    before = state(continue_button=Rect(450, 900, 50, 30))
    pending = ActionOutcome(Action(ActionType.CONTINUE), before, 8)
    assert pending.observe(before, 1).status is OutcomeStatus.WAITING
    assert pending.observe(state(ui_state=UIState.UNKNOWN), 2).status is OutcomeStatus.WAITING
    assert pending.observe(state(ui_state=UIState.ENEMY_TURN), 3).status is OutcomeStatus.SUCCEEDED


def test_timeout_is_unverified_not_success():
    before = state()
    pending = ActionOutcome(Action(ActionType.PLAY_CARD, card_index=0), before, 8)
    assert pending.observe(before, 8).status is OutcomeStatus.TIMED_OUT
    assert pending.observe(state(ui_state=UIState.ENEMY_TURN), 9).status is OutcomeStatus.TIMED_OUT


@pytest.mark.parametrize("change", ["prompt_flag", "action_prompt", "both"])
def test_select_target_reroutes_when_targeting_prompt_changes(change):
    # 会话 20261121T134723：满场替换点选后立刻进入出牌可选效果的
    # 新选目标，ui 同为 TARGETING；原选择已被消费，要重新路由。
    before = state(ui_state=UIState.TARGETING, replace_prompt=True)
    if change == "prompt_flag":
        after = state(ui_state=UIState.TARGETING, replace_prompt=False)
    elif change == "action_prompt":
        after = state(ui_state=UIState.TARGETING, replace_prompt=True,
                      action_prompt="action_skip")
    else:
        after = state(ui_state=UIState.TARGETING, replace_prompt=False,
                      action_prompt="action_skip")
    pending = ActionOutcome(Action(ActionType.SELECT_TARGET), before, 8)
    outcome = pending.observe(after, 1)
    assert outcome.status is OutcomeStatus.NEEDS_INPUT
    assert outcome.reason == "targeting_context_changed"


def test_option_pick_reroutes_when_variants_consumed():
    # 会话 20261121T142531：变体点选后选项卡消失、提示进入单位选目标，
    # ui 同为 TARGETING；选项集合变化即上下文变化，需重新路由。
    options = (Rect(645, 240, 280, 320), Rect(965, 240, 280, 320))
    before = state(ui_state=UIState.TARGETING,
                   action_prompt="action_target", spell_options=options)
    after = state(ui_state=UIState.TARGETING, action_prompt="action_target")
    pending = ActionOutcome(Action(ActionType.SELECT_TARGET,
                                   raw={"option": 0}), before, 15)
    outcome = pending.observe(after, 1)
    assert outcome.status is OutcomeStatus.NEEDS_INPUT
    assert outcome.reason == "targeting_context_changed"
    closed = pending.observe(
        state(ui_state=UIState.MY_TURN_IDLE), 2)
    assert closed.status is OutcomeStatus.SUCCEEDED
    assert closed.reason == "targeting_closed"


@pytest.mark.parametrize("after_ui,after_prompt", [
    (UIState.TARGETING, None),
    (UIState.MY_TURN_IDLE, None),
])
def test_select_target_context_unchanged_or_closed(after_ui, after_prompt):
    before = state(ui_state=UIState.TARGETING, replace_prompt=True)
    after = state(ui_state=after_ui, replace_prompt=True,
                  action_prompt=after_prompt)
    pending = ActionOutcome(Action(ActionType.SELECT_TARGET), before, 8)
    if after_ui is UIState.TARGETING:
        assert pending.observe(after, 1).status is OutcomeStatus.WAITING
    else:
        assert pending.observe(after, 1).status is OutcomeStatus.SUCCEEDED


def test_confirmed_stack_play_succeeds_on_resolution_return():
    # 会话 20261121T144407：0 费傾巢而出经「確認」结算召唤三只
    # 小蜘蛛——无法力消耗、召唤物与法术不同名，落地/支付判据失配；
    # 堆栈经确认闭合回到常规界面即为已结算证据。
    card = CardInHand(2, "傾巢而出", 0, Rect(400, 850, 80, 100))
    before = state(hand_expanded=True, hand=[card],
                   my_units=[], enemy_units=[])
    pending = ActionOutcome(Action(ActionType.PLAY_CARD, card_index=2),
                            before, 20)
    staged = state(ui_state=UIState.COMBAT_RESOLVING,
                   action_prompt="action_confirm")
    assert pending.observe(staged, 1).reason == "confirmation_required"
    pending.resume_after_confirmation()
    resolved = state(ui_state=UIState.MY_TURN_IDLE,
                     my_units=[Unit("小蜘蛛", 2, 1, Rect(400, 550, 80, 100)),
                               Unit("小蜘蛛", 2, 1, Rect(520, 550, 80, 100)),
                               Unit("小蜘蛛", 2, 1, Rect(640, 550, 80, 100))])
    outcome = pending.observe(resolved, 3)
    assert outcome.status is OutcomeStatus.SUCCEEDED
    assert outcome.reason == "stack_confirmation_resolved"
    # 敌方优先权阶段仍等待，不误判已结算。
    assert pending.observe(
        state(ui_state=UIState.COMBAT_RESOLVING), 4
    ).status is OutcomeStatus.WAITING


def test_combat_confirm_unacknowledged_reroutes_before_deadline():
    # 会话 20261121T143042：攻击确认点击被吞，action_confirm 停 21s。
    before = state(ui_state=UIState.COMBAT_RESOLVING,
                   action_prompt="action_confirm")
    after = state(ui_state=UIState.COMBAT_RESOLVING,
                  action_prompt="action_confirm")
    pending = ActionOutcome(Action(ActionType.CONFIRM), before, 20,
                            unacknowledged_deadline=6)
    assert pending.observe(after, 5).status is OutcomeStatus.WAITING
    outcome = pending.observe(after, 7)
    assert outcome.status is OutcomeStatus.NEEDS_INPUT
    assert outcome.reason == "confirm_unacknowledged"
    # 提示变了说明在结算/新阶段，不误判被吞。
    progressed = state(ui_state=UIState.COMBAT_RESOLVING,
                       action_prompt="action_commit")
    pending2 = ActionOutcome(Action(ActionType.CONFIRM), before, 20,
                             unacknowledged_deadline=6)
    outcome2 = pending2.observe(progressed, 7)
    assert outcome2.status is OutcomeStatus.NEEDS_INPUT
    assert outcome2.reason == "confirmation_prompt_changed"


def test_combat_commit_unacknowledged_reroutes_before_deadline():
    # 会话 20261121T150328：堆栈「結算」点击被吞，action_commit 停 21s。
    before = state(ui_state=UIState.COMBAT_RESOLVING,
                   action_prompt="action_commit")
    after = state(ui_state=UIState.COMBAT_RESOLVING,
                  action_prompt="action_commit")
    pending = ActionOutcome(Action(ActionType.CONFIRM), before, 20,
                            unacknowledged_deadline=6)
    outcome = pending.observe(after, 7)
    assert outcome.status is OutcomeStatus.NEEDS_INPUT
    assert outcome.reason == "confirm_unacknowledged"
    # 提示读不出时不判被吞（转场中帧），保持等待。
    unread = replace(after, action_prompt=None)
    pending2 = ActionOutcome(Action(ActionType.CONFIRM), before, 20,
                             unacknowledged_deadline=6)
    assert pending2.observe(unread, 7).status is OutcomeStatus.WAITING


def test_block_drag_unacknowledged_reroutes_before_deadline():
    # 会话 20261121T143406：格挡拖拽被吞，单位 8s 停在备战行。
    before = state(ui_state=UIState.BLOCKING,
                   my_units=[Unit("b", 2, 2, Rect(400, 850, 90, 100))],
                   enemy_units=[Unit("a", 3, 1, Rect(400, 300, 90, 100))])
    action = Action(ActionType.BLOCK, raw={"pairs": [(0, 0)]})
    pending = ActionOutcome(action, before, 15, unacknowledged_deadline=6)
    after = replace(before, my_units=[
        Unit("b", 2, 2, Rect(400, 850, 90, 100))])
    assert pending.observe(after, 5).status is OutcomeStatus.WAITING
    outcome = pending.observe(after, 7)
    assert outcome.status is OutcomeStatus.NEEDS_INPUT
    assert outcome.reason == "block_unacknowledged"
    # 已入格挡行的指派按既有成功判据结案，不误判被吞。
    landed = replace(before, my_units=[
        Unit("b", 2, 2, Rect(400, 550, 90, 100))])
    landed_outcome = pending.observe(landed, 7)
    assert landed_outcome.status is OutcomeStatus.SUCCEEDED
    assert landed_outcome.reason == "selected_units_moved_to_combat_row"


def test_play_drag_unacknowledged_reroutes_before_deadline():
    # 会话 20261121T135644：尖嘯蜘蛛拖拽后画面 20s 像素级不变、卡仍在手。
    before = state()
    pending = ActionOutcome(Action(ActionType.PLAY_CARD, card_index=0), before, 20,
                            unacknowledged_deadline=10)
    assert pending.observe(before, 9).status is OutcomeStatus.WAITING
    outcome = pending.observe(before, 11)
    assert outcome.status is OutcomeStatus.NEEDS_INPUT
    assert outcome.reason == "play_unacknowledged"


def test_play_unacknowledged_ignores_idle_hand_collapse():
    # LoR 手牌闲置数秒会自动收起；收起与出牌结果无关，仍判被吞重路由
    # （实机 20261121T140029 与严格判等同病）。
    before = state()
    pending = ActionOutcome(Action(ActionType.PLAY_CARD, card_index=0), before, 20,
                            unacknowledged_deadline=10)
    collapsed = replace(before, hand_expanded=False)
    outcome = pending.observe(collapsed, 11)
    assert outcome.status is OutcomeStatus.NEEDS_INPUT
    assert outcome.reason == "play_unacknowledged"


def test_play_unacknowledged_requires_no_relevant_change():
    before = state()
    pending = ActionOutcome(Action(ActionType.PLAY_CARD, card_index=0), before, 20,
                            unacknowledged_deadline=10)
    changed = replace(before, hand=before.hand[:1])
    # 手牌有变化时不是「没发生」，沿用原等待/核验路径。
    assert pending.observe(changed, 11).status is OutcomeStatus.WAITING
    paid = replace(before, mana=2)
    assert pending.observe(paid, 11).status is OutcomeStatus.WAITING
    # 单位上场是出牌成功的证据，走原有核验而不是「未确认」。
    landed = replace(before, hand=before.hand[:1], my_units=units(900))
    assert pending.observe(landed, 11).status is OutcomeStatus.SUCCEEDED


def test_play_unacknowledged_without_deadline_keeps_waiting():
    before = state()
    pending = ActionOutcome(Action(ActionType.PLAY_CARD, card_index=0), before, 20)
    assert pending.observe(before, 11).status is OutcomeStatus.WAITING
    assert pending.observe(before, 20).status is OutcomeStatus.TIMED_OUT


def test_confirmation_required_keeps_fixed_parent_budget():
    # 确认提示不续父预算；慢速法术的时间在发送时的 20s 窗口里（engine
    # 对已展开出牌统一给 20s，见 test_expanded_play_gets_full_window）。
    before = state()
    pending = ActionOutcome(Action(ActionType.PLAY_CARD, card_index=0), before, 20)
    after = replace(before, ui_state=UIState.COMBAT_RESOLVING,
                    action_prompt="action_confirm")
    assert pending.observe(after, 18).status is OutcomeStatus.NEEDS_INPUT
    assert pending.deadline == 20
    assert pending.observe(after, 20).status is OutcomeStatus.TIMED_OUT


def test_confirmation_can_observe_a_new_round_without_ui_enum_change():
    before = state(mana=0, readings={"mana": Reading(0, 0)})
    pending = ActionOutcome(Action(ActionType.END_TURN), before, 8)
    assert pending.observe(state(), 1).reason == "new_mana_observed"
    assert pending.observe(state(readings={"mana": Reading(3, 1)}), 1).status is OutcomeStatus.WAITING


def test_attack_confirmation_requires_token_and_unit_return_evidence():
    before = state(my_units=units(700), has_attack_token=True)
    pending = ActionOutcome(Action(ActionType.CONFIRM), before, 8)
    after = replace(before, has_attack_token=False)
    assert pending.observe(after, 1).status is OutcomeStatus.WAITING
    assert pending.observe(replace(after, my_units=units(900)), 2).reason == "attack_token_spent_and_units_returned"


@pytest.mark.parametrize("previous,current,ui,kind,expected", [
    ("action_confirm", "action_commit", UIState.COMBAT_RESOLVING, ActionType.CONFIRM, OutcomeStatus.NEEDS_INPUT),
    ("action_commit", "action_confirm", UIState.COMBAT_RESOLVING, ActionType.CONFIRM, OutcomeStatus.NEEDS_INPUT),
    ("action_commit", "action_commit", UIState.COMBAT_RESOLVING, ActionType.CONFIRM, OutcomeStatus.WAITING),
    ("action_confirm", None, UIState.COMBAT_RESOLVING, ActionType.CONFIRM, OutcomeStatus.WAITING),
    (None, "action_commit", UIState.COMBAT_RESOLVING, ActionType.CONFIRM, OutcomeStatus.WAITING),
    ("action_confirm", "action_commit", UIState.UNKNOWN, ActionType.CONFIRM, OutcomeStatus.WAITING),
    ("action_confirm", "action_commit", UIState.COMBAT_RESOLVING, ActionType.END_TURN, OutcomeStatus.WAITING),
])
def test_only_a_new_known_confirmation_prompt_allows_further_input(previous, current, ui, kind, expected):
    before = state(ui_state=UIState.COMBAT_RESOLVING, action_prompt=previous)
    after = replace(before, ui_state=ui, action_prompt=current)
    pending = ActionOutcome(Action(kind), before, 8)
    assert pending.observe(after, 1).status is expected
    assert pending.observe(after, 8).status is OutcomeStatus.TIMED_OUT


def test_free_spell_without_correlated_evidence_stays_unverified():
    before = state()
    pending = ActionOutcome(Action(ActionType.PLAY_CARD, 0), before, 8)
    # 单独手牌数量变化仍可能是漏识别；在缺身份/法术效果识别时宁可停。
    assert pending.observe(replace(before, hand=before.hand[:1]), 1).status is OutcomeStatus.WAITING


def test_unknown_animation_does_not_prove_play_by_revealing_units():
    before = state()
    pending = ActionOutcome(Action(ActionType.PLAY_CARD, 0), before, 8)
    after = replace(
        before,
        ui_state=UIState.UNKNOWN,
        hand=[],
        my_units=units(900),
    )
    assert pending.observe(after, 1).status is OutcomeStatus.WAITING
    staged = replace(after, ui_state=UIState.COMBAT_RESOLVING)
    assert pending.observe(staged, 2).status is OutcomeStatus.NEEDS_INPUT
