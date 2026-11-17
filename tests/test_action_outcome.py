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
    pending = ActionOutcome(Action(ActionType.PLAY_CARD, card_index=0), before, 8)
    assert pending.observe(before, 1).status is OutcomeStatus.WAITING
    assert pending.observe(state(), 2).reason == "hand_expanded"


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
    collapsed = ActionOutcome(Action(ActionType.PLAY_CARD, card_index=0),
                              state(hand_expanded=False), 8)
    assert collapsed.observe(state(ui_state=UIState.TARGETING, hand_expanded=False), 1).status is OutcomeStatus.NEEDS_INPUT


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


def test_play_yields_to_confirmation_when_the_game_requests_it():
    before = state()
    pending = ActionOutcome(Action(ActionType.PLAY_CARD, card_index=0), before, 8)
    after = replace(before, ui_state=UIState.COMBAT_RESOLVING)
    assert pending.observe(after, 1).status is OutcomeStatus.NEEDS_INPUT
    # 展开手牌之后出现结算按钮，不代表已经成功拖出卡牌。
    collapsed = replace(before, hand_expanded=False)
    expanded = ActionOutcome(Action(ActionType.PLAY_CARD, 0), collapsed, 8).observe(after, 1)
    assert expanded.reason == "hand_expanded"


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
