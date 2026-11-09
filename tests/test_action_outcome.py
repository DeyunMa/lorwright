"""结果验证不能把展开、动画、丢帧或部分拖拽当成动作完成。"""

from dataclasses import replace

import pytest

from lorwright.loop.outcome import ActionOutcome, OutcomeStatus
from lorwright.models import Action, ActionType, CardInHand, GameState, Reading, Rect, UIState, Unit


def state(**kwargs):
    defaults = dict(
        ui_state=UIState.MY_TURN_IDLE, mana=3, hand_expanded=True,
        hand=[CardInHand(i, "", 1, Rect(100 * i, 900, 20, 20)) for i in range(2)],
        readings={"mana": Reading(3, 0)},
    )
    defaults.update(kwargs)
    return GameState(**defaults)


def units(*ys):
    return [Unit("", -1, -1, Rect(i * 150, y, 8, 8)) for i, y in enumerate(ys)]


def test_expanding_is_a_separate_step_from_playing():
    before = state(hand_expanded=False)
    pending = ActionOutcome(Action(ActionType.PLAY_CARD, card_index=0), before, 8)
    assert pending.observe(before, 1).status is OutcomeStatus.WAITING
    assert pending.observe(state(), 2).reason == "hand_expanded"


def test_mulligan_replace_is_sent_without_waiting_for_state_change():
    before = state(ui_state=UIState.MULLIGAN)
    pending = ActionOutcome(
        Action(ActionType.MULLIGAN_REPLACE, raw={"points": [(10, 20)]}), before, 8,
    )
    outcome = pending.observe(before, 1)
    assert outcome.status is OutcomeStatus.SUCCEEDED
    assert outcome.reason == "mulligan_replace_sent"


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


def test_free_spell_without_correlated_evidence_stays_unverified():
    before = state()
    pending = ActionOutcome(Action(ActionType.PLAY_CARD, 0), before, 8)
    # 单独手牌数量变化仍可能是漏识别；在缺身份/法术效果识别时宁可停。
    assert pending.observe(replace(before, hand=before.hand[:1]), 1).status is OutcomeStatus.WAITING


def test_play_card_can_succeed_while_ui_is_unknown():
    before = state()
    pending = ActionOutcome(Action(ActionType.PLAY_CARD, 0), before, 8)
    after = replace(
        before,
        ui_state=UIState.UNKNOWN,
        hand=[],
        my_units=units(900),
    )
    assert pending.observe(after, 1).status is OutcomeStatus.SUCCEEDED
