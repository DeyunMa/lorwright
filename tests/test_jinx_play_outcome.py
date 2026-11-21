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
                      hand=[replace(hand[0], index=i) for i in range(7)], hand_expanded=True,
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


@pytest.mark.parametrize("hand_count", [6, 7, 8, 10])
def test_collapsed_jinx_summon_uses_payment_damage_and_board(hand_count):
    action, before, after = summon_states()
    before = replace(before, enemy_nexus_hp=33,
                     readings={**before.readings, "enemy_nexus_hp": Reading(33, 0)})
    after = replace(after, hand_expanded=False,
                    hand=[replace(after.hand[0], index=i) for i in range(hand_count)],
                    enemy_nexus_hp=18,
                    readings={**after.readings, "enemy_nexus_hp": Reading(18, 0)})
    expectation = JinxOpeningPolicy().play_expectation(action, before)
    assert expectation.verify(after)
    # 任一独立依据缺失时，即便偶然数出七张，也不能接受跨视图牌数。
    assert not expectation.verify(replace(after, my_units=[]))
    assert not expectation.verify(replace(after, mana=3, readings={
        "mana": Reading(3, 0), "enemy_nexus_hp": Reading(18, 0),
    }))
    assert not expectation.verify(replace(after, readings={
        "mana": Reading(1, 1), "enemy_nexus_hp": Reading(18, 0),
    }))
    assert not expectation.verify(replace(after, readings={
        "mana": Reading(1, 0), "enemy_nexus_hp": Reading(18, 1),
    }))
    assert not expectation.verify(replace(after, enemy_nexus_hp=33, readings={
        "mana": Reading(1, 0), "enemy_nexus_hp": Reading(33, 0),
    }))
    for ui in (UIState.UNKNOWN, UIState.ENEMY_TURN, UIState.BLOCKING):
        assert not expectation.verify(replace(after, ui_state=ui))
    assert not JinxOpeningPolicy().play_expectation(action, replace(before, readings={
        "mana": Reading(3, 0), "enemy_nexus_hp": Reading(33, 1),
    })).verify(after)


def test_collapsed_jinx_with_healed_enemy_requires_visible_jinx_and_payment():
    # 实机会话 20261117T032446：2 费 Jinx 后手牌收起，敌方血量 20→23。
    action, before, after = summon_states()
    before = replace(before, enemy_nexus_hp=20,
                     readings={**before.readings, "enemy_nexus_hp": Reading(20, 0)})
    after = replace(after, hand_expanded=False, enemy_nexus_hp=23,
                    my_units=[replace(after.my_units[0], name="吉茵珂絲")],
                    readings={**after.readings, "enemy_nexus_hp": Reading(23, 0)})
    expectation = JinxOpeningPolicy().play_expectation(action, before)
    outcome = ActionOutcome(action, before, 20, play_expectation=expectation)
    assert outcome.observe(after, 12).status is OutcomeStatus.SUCCEEDED
    assert not expectation.verify(replace(after, my_units=[replace(after.my_units[0], name="")]))
    assert not expectation.verify(replace(after, mana=3, readings={"mana": Reading(3, 0)}))
    assert not expectation.verify(replace(after, readings={"mana": Reading(1, 1)}))
    assert not expectation.verify(replace(after, ui_state=UIState.UNKNOWN))
    assert not expectation.verify(replace(after, ui_state=UIState.ENEMY_TURN))
    assert outcome.observe(after, 20).status is OutcomeStatus.TIMED_OUT
    assert not expectation.verify(replace(after, my_units=[]))
    stale_before = replace(before, readings={"mana": Reading(3, 1)})
    assert not JinxOpeningPolicy().play_expectation(action, stale_before).verify(after)
    _, zero_before, _ = summon_states(cost=0)
    # 零费落地改由同名单位新上桌核验（实机 20261121T061713）。
    assert JinxOpeningPolicy().play_expectation(action, zero_before).verify(after)


def test_zero_cost_collapsed_jinx_verified_by_named_unit_landing():
    """实机 20261121T061713：费用读作 0、手牌 5→6 收起，Jinx 9|10 上桌，
    敌核 29→24——支付证据不可得，同名单位落地即核验。"""
    action, before, after = summon_states(cost=0)
    before = replace(before, mana=3, enemy_nexus_hp=29,
                     hand=before.hand[:5],
                     readings={"mana": Reading(3, 0),
                               "enemy_nexus_hp": Reading(29, 0)})
    after = replace(after, hand_expanded=False,
                    hand=after.hand[:6], enemy_nexus_hp=24,
                    my_units=[Unit("吉茵珂絲", 9, 10, Rect(700, 850, 100, 150)),
                              Unit("", 3, 2, Rect(500, 850, 100, 150)),
                              Unit("", 1, 1, Rect(300, 850, 100, 150))],
                    readings={"mana": Reading(3, 0),
                              "enemy_nexus_hp": Reading(24, 0)})
    expectation = JinxOpeningPolicy().play_expectation(action, before)
    assert expectation.verify(after)
    outcome = ActionOutcome(action, before, 20, play_expectation=expectation)
    assert outcome.observe(after, 12).status is OutcomeStatus.SUCCEEDED
    # 同名单位未新上桌（伤害或数量不足以单独成证）仍不接受。
    assert not expectation.verify(replace(
        after, my_units=[replace(u, name="") for u in after.my_units]))
    assert not expectation.verify(replace(after, ui_state=UIState.ENEMY_TURN))
    assert not expectation.verify(before)


def test_zero_cost_collapsed_jinx_cannot_use_damage_without_payment():
    action, before, after = summon_states(cost=0)
    before = replace(before, enemy_nexus_hp=33,
                     readings={**before.readings, "enemy_nexus_hp": Reading(33, 0)})
    after = replace(after, hand_expanded=False, enemy_nexus_hp=18,
                    readings={**after.readings, "enemy_nexus_hp": Reading(18, 0)})
    assert not JinxOpeningPolicy().play_expectation(action, before).verify(after)


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
    # 缺少法术法力读数时，不以不完整支付或视图变化替代伤害证据。
    assert not expectation.verify(replace(after, mana=0, enemy_nexus_hp=13,
                                         readings={"mana": Reading(0, 0),
                                                   "enemy_nexus_hp": Reading(13, 0)}))
    assert not expectation.verify(replace(after, readings={"enemy_nexus_hp": Reading(6, 1)}))


@pytest.mark.parametrize("change", ["none", "stale_before_mana", "stale_before_spell",
                                    "stale_after_mana", "stale_after_spell", "missing_spell",
                                    "refill", "no_payment", "cost_exceeds_payment", "zero_cost",
                                    "unknown", "enemy", "blocking"])
def test_collapsed_rocket_payment_requires_fresh_net_spending(change):
    rocket = CardInHand(0, "超威能死亡火箭！", 1, Rect(400, 800, 50, 50))
    before = GameState(ui_state=UIState.MY_TURN_IDLE, hand=[rocket] * 6,
                       hand_expanded=True, mana=1, spell_mana=2, enemy_nexus_hp=10,
                       readings={"mana": Reading(1, 0), "spell_mana": Reading(2, 0),
                                 "enemy_nexus_hp": Reading(10, 0)})
    after = replace(before, hand_expanded=False, hand=before.hand[:5], spell_mana=1,
                    enemy_nexus_hp=11, readings={"mana": Reading(1, 0),
                                               "spell_mana": Reading(1, 0),
                                               "enemy_nexus_hp": Reading(11, 0)})
    if change.startswith("stale_"):
        _, side, field = change.split("_", 2)
        name = "mana" if field == "mana" else "spell_mana"
        state = before if side == "before" else after
        state = replace(state, readings={**state.readings, name: Reading(state.readings[name].value, 1)})
        if side == "before":
            before = state
        else:
            after = state
    elif change == "missing_spell":
        after = replace(after, spell_mana=None, readings={"mana": Reading(1, 0)})
    elif change == "refill":
        after = replace(after, mana=2, readings={**after.readings, "mana": Reading(2, 0)})
    elif change == "no_payment":
        after = replace(after, spell_mana=2, readings={**after.readings, "spell_mana": Reading(2, 0)})
    elif change in {"cost_exceeds_payment", "zero_cost"}:
        before = replace(before, hand=[replace(rocket, cost=2 if change == "cost_exceeds_payment" else 0)])
    elif change in {"unknown", "enemy", "blocking"}:
        after = replace(after, ui_state={"unknown": UIState.UNKNOWN, "enemy": UIState.ENEMY_TURN,
                                        "blocking": UIState.BLOCKING}[change])
    action = Action(ActionType.PLAY_CARD, card_index=0, raw={"jinx_rocket": True})
    expectation = JinxOpeningPolicy().play_expectation(action, before)
    assert expectation.verify(after) is (change == "none")


def test_expansion_and_other_cards_keep_generic_result_checks():
    action, before, _ = summon_states()
    policy = JinxOpeningPolicy()
    assert policy.play_expectation(action, replace(before, hand_expanded=False)) is None
    assert policy.play_expectation(replace(action, card_index=0), before) is None
