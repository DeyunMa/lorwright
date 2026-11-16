"""Jinx 召唤重建手牌的后验；合成序列不作为实机成功证据。"""

from dataclasses import replace

import pytest

from lorwright.core.champions.jinx.policy import JinxOpeningPolicy
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


def summon_states(cost=2):
    action = Action(ActionType.PLAY_CARD, card_index=2)
    hand = [CardInHand(i, "吉茵珂絲" if i == 2 else "", cost if i == 2 else 1,
                       Rect(400 + i * 80, 800, 50, 50)) for i in range(6)]
    before = GameState(ui_state=UIState.MY_TURN_IDLE, mana=3, hand=hand,
                       hand_expanded=True, readings={"mana": Reading(3, 0)})
    after = GameState(ui_state=UIState.MY_TURN_IDLE, mana=3 - cost,
                      hand=[replace(hand[0], index=i) for i in range(7)],
                      my_units=[Unit("", 6, 7, Rect(1000, 850, 100, 150))],
                      readings={"mana": Reading(3 - cost, 0)})
    return action, before, after


def test_jinx_rebuild_succeeds_while_generic_hand_reduction_does_not():
    action, before, after = summon_states()
    policy = JinxOpeningPolicy()
    expectation = policy.play_expectation(action, before)
    assert expectation is not None
    assert expectation.timeout_s == 20
    generic = ActionOutcome(action, before, 20)
    assert generic.observe(after, 12).status is OutcomeStatus.WAITING
    special = ActionOutcome(action, before, 20, play_expectation=expectation)
    assert special.observe(after, 12).status is OutcomeStatus.SUCCEEDED
    assert special.observe(after, 20).status is OutcomeStatus.TIMED_OUT
    # 旧的收手场面基线即使高于当前识别数量，也不能否定已验证的出牌。
    policy._board_before = 10
    policy.on_action_outcome(action, before, after)
    assert policy.step == 2
    assert policy._rockets_played == 0


@pytest.mark.parametrize("change", [
    {"ui_state": UIState.UNKNOWN},
    {"my_units": []},
    {"mana": 3, "readings": {"mana": Reading(3, 0)}},
    {"readings": {"mana": Reading(1, 1)}},
    {"hand": []},
])
def test_jinx_rebuild_requires_independent_result_evidence(change):
    action, before, after = summon_states()
    expectation = JinxOpeningPolicy().play_expectation(action, before)
    assert not expectation.verify(replace(after, **change))


def test_zero_cost_jinx_needs_generated_card_identities():
    action, before, after = summon_states(cost=0)
    expectation = JinxOpeningPolicy().play_expectation(action, before)
    assert not expectation.verify(after)
    generated = [replace(card, name="超威能死亡火箭！" if i < 2 else "砰砰")
                 for i, card in enumerate(after.hand)]
    assert expectation.verify(replace(after, hand=generated))


def test_special_outcome_cannot_accept_generic_hand_reduction_during_animation():
    action, before, after = summon_states()
    expectation = JinxOpeningPolicy().play_expectation(action, before)
    animation = replace(after, ui_state=UIState.UNKNOWN, hand=after.hand[:4])
    assert ActionOutcome(action, before, 20).observe(animation, 2).status is OutcomeStatus.SUCCEEDED
    assert ActionOutcome(action, before, 20, play_expectation=expectation).observe(
        animation, 2
    ).status is OutcomeStatus.WAITING


@pytest.mark.parametrize("damage_reading", [Reading(1, 0), Reading(1, 1), Reading(8, 0)])
def test_rocket_accepts_fresh_damage_when_mana_is_refilled(damage_reading):
    rocket = CardInHand(0, "超威能死亡火箭！", 1, Rect(400, 800, 50, 50))
    before = GameState(ui_state=UIState.MY_TURN_IDLE, hand=[rocket, rocket],
                       hand_expanded=True, mana=1, spell_mana=3, enemy_nexus_hp=8,
                       readings={"mana": Reading(1, 0), "spell_mana": Reading(3, 0),
                                 "enemy_nexus_hp": Reading(8, 0)})
    after = replace(before, hand=[rocket], enemy_nexus_hp=damage_reading.value,
                    readings={**before.readings, "enemy_nexus_hp": damage_reading})
    action = Action(ActionType.PLAY_CARD, card_index=0, raw={"jinx_rocket": True})
    expectation = JinxOpeningPolicy().play_expectation(action, before)
    assert expectation.verify(after) is (damage_reading == Reading(1, 0))
    assert not expectation.verify(replace(after, hand=before.hand))
    assert not expectation.verify(replace(after, ui_state=UIState.UNKNOWN))


@pytest.mark.parametrize("ui,reading,expected", [
    (UIState.MY_TURN_IDLE, Reading(6, 0), True),
    (UIState.MY_TURN_IDLE, Reading(6, 1), False),
    (UIState.MY_TURN_IDLE, Reading(13, 0), False),
    (UIState.UNKNOWN, Reading(6, 0), False),
    (UIState.ENEMY_TURN, Reading(6, 0), False),
    (UIState.BLOCKING, Reading(6, 0), False),
])
def test_rocket_collapsed_hand_uses_fresh_damage_instead_of_cross_view_count(ui, reading, expected):
    rocket = CardInHand(0, "超威能死亡火箭！", 1, Rect(400, 800, 50, 50))
    before = GameState(ui_state=UIState.MY_TURN_IDLE, hand=[rocket] * 6,
                       hand_expanded=True, mana=1, enemy_nexus_hp=13,
                       readings={"mana": Reading(1, 0), "enemy_nexus_hp": Reading(13, 0)})
    action = Action(ActionType.PLAY_CARD, card_index=0, raw={"jinx_rocket": True})
    expectation = JinxOpeningPolicy().play_expectation(action, before)
    after = replace(before, ui_state=ui, hand_expanded=False, enemy_nexus_hp=reading.value,
                    readings={**before.readings, "enemy_nexus_hp": reading})
    assert expectation.verify(after) is expected
    # 不能用支付或视图变化替代伤害证据。
    assert not expectation.verify(replace(after, mana=0, enemy_nexus_hp=13,
                                         readings={"mana": Reading(0, 0),
                                                   "enemy_nexus_hp": Reading(13, 0)}))
    assert not expectation.verify(replace(after, readings={"enemy_nexus_hp": Reading(6, 1)}))


def test_expansion_and_other_cards_keep_generic_result_checks():
    action, before, _ = summon_states()
    policy = JinxOpeningPolicy()
    assert policy.play_expectation(action, replace(before, hand_expanded=False)) is None
    assert policy.play_expectation(replace(action, card_index=0), before) is None
