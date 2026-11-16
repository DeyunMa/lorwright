from dataclasses import replace

import pytest

from lorwright.core.champions import load
from lorwright.core.champions.jinx.policy import JinxOpeningPolicy
from lorwright.core.models import (
    Action,
    ActionType,
    CardInHand,
    GameState,
    MulliganCard,
    Reading,
    Rect,
    UIState,
    Unit,
)


def card(index, name, cost):
    return CardInHand(index, name, cost, Rect(0, 0, 8, 8))


def mulligan_card(index, name, cost=0):
    return MulliganCard(index, None if not name else name == "吉茵珂絲", Rect(0, 0, 8, 8))


def state(cards, units=(), expanded=True, mana=3):
    return GameState(ui_state=UIState.MY_TURN_IDLE, hand=list(cards),
                     hand_expanded=expanded, mana=mana, my_units=list(units))


def test_two_steps_require_confirmed_spell_and_visible_crab():
    policy = load("jinx").make_policy()
    spell, hero = card(1, "應急裝置", 1), card(2, "吉茵珂絲", 2)
    before = state([card(0, "其他牌", 1), spell, hero])
    policy.decide(replace(before, hand_expanded=False))
    chosen = policy.decide(before)
    assert chosen == Action(type=ActionType.PLAY_CARD, card_index=1)
    # Merely deciding to play the spell must never unlock Jinx.
    # 无目标时弃权，让通用层接手而不是空转。
    assert policy.decide(state([hero])) is None
    no_crab = state([hero], mana=2)
    policy.on_action_outcome(chosen, before, no_crab)
    # 等蟹确认期间必须原地等待，不能重出法术。
    assert policy.decide(no_crab).type is ActionType.NO_OP
    crab = Unit("", -1, -1, Rect(0, 0, 10, 10))
    after = state([hero], [crab], mana=2)
    assert policy.decide(after) == Action(type=ActionType.PLAY_CARD, card_index=2)
    policy.decide(replace(after, hand_expanded=False))
    hero_action = policy.decide(after)
    policy.on_action_outcome(hero_action, after, state([], [crab, crab], mana=0))
    assert policy.step == 2
    assert policy.decide(after) is None


def test_already_expanded_hand_still_starts_with_spell():
    # 起手直接是展开态时，也要先打應急裝置，而不是因为 _board_before=None 弃权。
    policy = load("jinx").make_policy()
    spell, hero = card(1, "應急裝置", 1), card(2, "吉茵珂絲", 2)
    state_now = state([card(0, "其他牌", 1), spell, hero])
    assert policy.decide(state_now) == Action(type=ActionType.PLAY_CARD, card_index=1)


@pytest.mark.parametrize("cost", [0, 1, 2, 3])
def test_emergency_device_up_to_three_mana_starts_combo(cost):
    policy = JinxOpeningPolicy()
    spell = card(1, "應急裝置", cost)
    before = state([card(0, "其他牌", 1), spell, card(2, "吉茵珂絲", 2)], mana=3)
    chosen = policy.decide(before)
    assert chosen == Action(type=ActionType.PLAY_CARD, card_index=1)
    crab = Unit("", -1, -1, Rect(0, 0, 10, 10))
    after = state([card(2, "吉茵珂絲", 2)], units=[crab], mana=2)
    policy.on_action_outcome(chosen, before, after)
    assert policy.step == 1
    assert policy.decide(after) == Action(type=ActionType.PLAY_CARD, card_index=2)


def test_emergency_device_uses_spell_mana_without_allowing_jinx_to_preempt_it():
    policy = JinxOpeningPolicy()
    cards = [card(0, "吉茵珂絲", 2), card(1, "應急裝置", 3)]
    s = state(cards, mana=2)
    assert policy.decide(replace(s, spell_mana=3)) == Action(
        type=ActionType.PLAY_CARD, card_index=1
    )
    assert policy.decide(replace(s, spell_mana=0)) is None
    assert policy.decide(replace(s, spell_mana=None)) is None


@pytest.mark.parametrize("cost", [0, 1, 2, 3, 4])
def test_jinx_after_spell_uses_current_affordable_cost(cost):
    policy = JinxOpeningPolicy(spell_already_played=True)
    before = state([card(0, "吉茵珂絲", cost)], mana=4)
    action = policy.decide(before)
    assert action == Action(type=ActionType.PLAY_CARD, card_index=0)
    unit = Unit("", -1, -1, Rect(0, 0, 10, 10))
    policy.on_action_outcome(action, before, state([], units=[unit], mana=0))
    assert policy.step == 2


def test_unknown_wrong_cost_and_expansion_do_not_advance():
    policy = load("jinx").make_policy()
    collapsed = state([card(0, "", 1)], expanded=False)
    action = policy.decide(collapsed)
    assert action.type is ActionType.PLAY_CARD
    policy.on_action_outcome(action, collapsed, replace(collapsed, hand_expanded=True))
    assert policy.step == 0
    assert policy.decide(state([card(0, "", 1), card(1, "吉茵珂絲", 2)])) is None
    assert policy.decide(state([card(0, "應急裝置", 4)], mana=4)) is None
    assert policy.decide(state([card(0, "應急裝置", -1)])) is None
    assert policy.decide(state([card(0, "應急裝置", 3)], mana=2)) is None
    assert policy.decide(state([card(0, "應急裝置", 1)], mana=0)) is None


def test_new_mulligan_resets_opening():
    policy = load("jinx").make_policy()
    policy.step = 2
    assert policy.decide(GameState(ui_state=UIState.MULLIGAN)).type is ActionType.NO_OP
    assert policy.step == 0


def test_explicit_resume_skips_spell_only_for_current_game():
    policy = JinxOpeningPolicy(spell_already_played=True)
    spell, hero = card(0, "應急裝置", 1), card(1, "吉茵珂絲", 2)
    policy.decide(state([spell, hero], expanded=False))
    assert policy.decide(state([spell, hero])) == Action(
        type=ActionType.PLAY_CARD, card_index=1
    )
    policy.decide(GameState(ui_state=UIState.MULLIGAN))
    policy.decide(state([spell, hero], expanded=False))
    assert policy.decide(state([spell, hero])) == Action(
        type=ActionType.PLAY_CARD, card_index=0
    )


def test_resume_after_jinx_starts_at_fleeting_step():
    policy = JinxOpeningPolicy(jinx_summoned=True)
    assert policy.step == 2
    rocket = card(0, "超威能死亡火箭！", 1)
    assert policy.decide(state([rocket, replace(rocket, index=1)], mana=1)) == Action(
        type=ActionType.PLAY_CARD, card_index=0, raw={"jinx_rocket": True}
    )


def test_mulligan_keeps_combo_cards_and_confirms():
    policy = load("jinx").make_policy()
    mulligan = GameState(
        ui_state=UIState.MULLIGAN,
        mulligan_selected=(False, False, False, False),
        mulligan_cards=[
            mulligan_card(0, "應急裝置"), mulligan_card(1, "吉茵珂絲"),
            mulligan_card(2, "其他牌"), mulligan_card(3, "其他牌"),
        ],
    )
    assert policy.decide(mulligan).type is ActionType.CONFIRM


def test_mulligan_keeps_other_cards_when_one_jinx_is_present():
    policy = load("jinx").make_policy()
    mulligan = GameState(ui_state=UIState.MULLIGAN, mulligan_selected=(False,) * 4, mulligan_cards=[
        mulligan_card(0, "其他牌"), mulligan_card(1, "吉茵珂絲"),
        mulligan_card(2, "其他牌"), mulligan_card(3, "其他牌"),
    ])
    assert policy.decide(mulligan).type is ActionType.CONFIRM


def test_mulligan_only_replaces_duplicate_jinx():
    policy = load("jinx").make_policy()
    cards = [
        MulliganCard(i, name == "吉茵珂絲", Rect(i * 100, 0, 8, 8))
        for i, name in enumerate(["其他牌", "吉茵珂絲", "其他牌", "吉茵珂絲"])
    ]
    mulligan = GameState(ui_state=UIState.MULLIGAN, mulligan_selected=(False,) * 4,
                         mulligan_cards=cards)
    action = policy.decide(mulligan)
    assert action.type is ActionType.MULLIGAN_REPLACE
    assert action.raw["points"] == [cards[3].rect.center]
    unknown = replace(cards[0], matches_target=None)
    assert policy.decide(replace(mulligan, mulligan_cards=[unknown, *cards[1:]])).type is ActionType.NO_OP
    assert policy.decide(mulligan).type is ActionType.MULLIGAN_REPLACE
    selected_cards = [*cards[:3], replace(cards[3], matches_target=None)]
    assert policy.decide(replace(mulligan, mulligan_cards=selected_cards,
                                 mulligan_selected=(False, False, False, True))).type is (
        ActionType.CONFIRM
    )


def test_mulligan_keeps_unknown_slot_and_replaces_known_duplicate():
    policy = load("jinx").make_policy()
    cards = [mulligan_card(0, "吉茵珂絲"), mulligan_card(1, ""),
             mulligan_card(2, "其他牌"), mulligan_card(3, "吉茵珂絲")]
    mulligan = GameState(ui_state=UIState.MULLIGAN, mulligan_selected=(False,) * 4,
                         mulligan_cards=cards)
    action = policy.decide(mulligan)
    assert action.type is ActionType.MULLIGAN_REPLACE
    assert action.raw["mulligan_index"] == 3
    assert policy.decide(replace(mulligan, mulligan_cards=cards[:3])).type is ActionType.NO_OP
    selected = replace(mulligan, mulligan_selected=(False, False, False, True))
    assert policy.decide(selected).type is ActionType.CONFIRM


@pytest.mark.parametrize("targets,desired", [
    ([None, False, None, False], {1, 3}),
    ([None, None, None, None], set()),
    ([None, True, False, None], set()),
])
def test_mulligan_unknown_slots_do_not_block_known_actions(targets, desired):
    policy = load("jinx").make_policy()
    cards = [MulliganCard(i, target, Rect(i * 100, 0, 8, 8))
             for i, target in enumerate(targets)]
    selected = [False] * 4
    for index in sorted(desired):
        current = GameState(ui_state=UIState.MULLIGAN, mulligan_cards=cards,
                            mulligan_selected=tuple(selected))
        action = policy.decide(current)
        assert action.type is ActionType.MULLIGAN_REPLACE
        assert action.raw["mulligan_index"] == index
        selected[index] = True
        cards[index] = replace(cards[index], matches_target=None)
    assert policy.decide(GameState(
        ui_state=UIState.MULLIGAN, mulligan_cards=cards,
        mulligan_selected=tuple(selected),
    )).type is ActionType.CONFIRM


def test_mulligan_replaces_all_cards_when_jinx_missing():
    policy = load("jinx").make_policy()
    mulligan = GameState(
        ui_state=UIState.MULLIGAN,
        mulligan_selected=(False, False, False, False),
        mulligan_cards=[
            mulligan_card(0, "應急裝置"), mulligan_card(1, "其他牌"),
            mulligan_card(2, "其他牌"), mulligan_card(3, "其他牌"),
        ],
    )
    action = policy.decide(mulligan)
    assert action.type is ActionType.MULLIGAN_REPLACE
    assert action.raw["mulligan_index"] == 0
    assert len(action.raw["points"]) == 1
    # 先确认一张已选，才能继续处理下一张。
    second = replace(mulligan, mulligan_selected=(True, False, False, False))
    assert policy.decide(second).raw["mulligan_index"] == 1
    assert policy.decide(replace(mulligan, mulligan_selected=(True,) * 4)).type is ActionType.CONFIRM


def test_mulligan_does_not_confirm_without_observed_replacement():
    policy = load("jinx").make_policy()
    mulligan = GameState(
        ui_state=UIState.MULLIGAN,
        mulligan_selected=(False,) * 4,
        mulligan_cards=[mulligan_card(i, "其他牌") for i in range(4)],
    )
    assert policy.decide(mulligan).type is ActionType.MULLIGAN_REPLACE
    assert policy.decide(mulligan).type is ActionType.MULLIGAN_REPLACE


def test_mulligan_waits_for_known_selection_and_corrects_unwanted_selection():
    policy = load("jinx").make_policy()
    cards = [mulligan_card(i, name) for i, name in enumerate(["吉茵珂絲", "其他牌", "其他牌", "其他牌"])]
    mulligan = GameState(ui_state=UIState.MULLIGAN, mulligan_cards=cards,
                         mulligan_selected=(False, None, False, False))
    assert policy.decide(mulligan).type is ActionType.NO_OP
    policy.decide(replace(mulligan, mulligan_selected=(False,) * 4))
    action = policy.decide(replace(mulligan, mulligan_selected=(True, False, False, False)))
    assert action.type is ActionType.MULLIGAN_REPLACE
    assert action.raw["mulligan_index"] == 0 and action.raw["selected"] is False


def test_existing_unit_is_not_mistaken_for_new_crab():
    policy = load("jinx").make_policy()
    unit = Unit("", -1, -1, Rect(0, 0, 10, 10))
    spell, hero = card(0, "應急裝置", 1), card(1, "吉茵珂絲", 2)
    collapsed = state([spell, hero], [unit], expanded=False)
    policy.decide(collapsed)
    expanded = state([spell, hero], [], expanded=True)
    action = policy.decide(expanded)
    # Expanded hand hides the original unit. It must not count as a new crab.
    policy.on_action_outcome(action, expanded, state([hero], [unit], mana=2))
    assert policy.step == 0
    assert policy.decide(state([hero], [unit], mana=2)).type is ActionType.NO_OP
    assert policy.step == 0
    assert policy.decide(state([hero, card(2, "吉茵珂絲", 2)], [unit, unit], mana=2)) == (
        Action(type=ActionType.PLAY_CARD, card_index=1)
    )


def test_verified_hero_does_not_wait_again_for_old_board_baseline():
    policy = load("jinx").make_policy()
    unit = Unit("", -1, -1, Rect(0, 0, 10, 10))
    hero = card(1, "吉茵珂絲", 2)
    policy.step = 1
    policy.decide(state([hero], [unit], expanded=False))
    before = state([hero, card(2, "吉茵珂絲", 2)])
    action = policy.decide(before)
    policy.on_action_outcome(action, before, state([hero], [unit], mana=0))
    # 回调仅由动作后验成功触发，不能再按收手时的旧基线等待一次。
    assert policy.step == 2
    assert policy.decide(state([card(0, "", 1)], [unit], mana=2)) is None
    assert policy.decide(state([], [unit, unit], mana=0)) is None


def test_post_jinx_plays_two_rockets_then_pow_pow():
    policy = load("jinx").make_policy()
    policy.step = 2

    def rocket(index):
        return card(index, "超威能死亡火箭！", 1)

    def pow_pow(index):
        return card(index, "砰砰", 1)

    before = state([rocket(0), rocket(1), pow_pow(2)], mana=3)
    first = policy.decide(before)
    assert first == Action(type=ActionType.PLAY_CARD, card_index=0, raw={"jinx_rocket": True})
    assert policy.decide(before) == first
    assert policy._rockets_played == 0
    policy.on_action_outcome(first, before, state([rocket(0), pow_pow(1)], mana=2))
    assert policy._rockets_played == 1

    after_first = state([rocket(0), pow_pow(1)], mana=2)
    second = policy.decide(after_first)
    assert second == Action(type=ActionType.PLAY_CARD, card_index=0, raw={"jinx_rocket": True})
    policy.on_action_outcome(second, after_first, state([pow_pow(0)], mana=1))
    assert policy._rockets_played == 2

    enemy = Unit("", -1, -1, Rect(0, 0, 10, 10))
    third = policy.decide(replace(state([pow_pow(0)], mana=1), enemy_units=[enemy]))
    assert third == Action(type=ActionType.PLAY_CARD, card_index=0)


def test_resume_after_one_rocket_plays_only_the_remaining_rocket():
    policy = load("jinx").make_policy(jinx_summoned=True, rockets_already_played=1)
    before = state([card(0, "超威能死亡火箭！", 1), card(1, "砰砰", 1)], mana=2)
    action = policy.decide(before)
    assert action == Action(type=ActionType.PLAY_CARD, card_index=0, raw={"jinx_rocket": True})
    policy.on_action_outcome(action, before, state([card(0, "砰砰", 1)], mana=1))
    enemy = Unit("", -1, -1, Rect(0, 0, 10, 10))
    assert policy.decide(replace(state([card(0, "砰砰", 1)], mana=1), enemy_units=[enemy])) == Action(
        type=ActionType.PLAY_CARD, card_index=0
    )


def test_pow_pow_requires_visible_enemy_after_rockets():
    policy = JinxOpeningPolicy(jinx_summoned=True, rockets_already_played=2)
    jinx = Unit("吉茵珂絲", 6, 7, Rect(0, 0, 10, 10))
    assert policy.decide(state([card(0, "砰砰", 1)], units=[jinx], mana=5)) is None
    assert policy.decide(state([card(0, "", 1)], units=[jinx], mana=5)) is None


def test_known_unit_does_not_bypass_board_or_mana_limits():
    policy = JinxOpeningPolicy(jinx_summoned=True, rockets_already_played=2)
    cards = [card(0, "", 1), card(1, "汙水坑疏濬機器人", 3)]
    assert policy.decide(state(cards, mana=2)) is None
    units = [Unit("", 1, 1, Rect(0, 0, 10, 10)) for _ in range(6)]
    assert policy.decide(state(cards, units=units, mana=4)) is None


def test_unrecognized_rockets_delegate_attack_to_generic_layer():
    policy = JinxOpeningPolicy(jinx_summoned=True)
    unit = Unit("", 2, 2, Rect(0, 900, 10, 10))
    s = replace(state([card(0, "", 1)], units=[unit], mana=2), has_attack_token=True)
    assert policy.decide(s) is None
    assert policy.decide(replace(s, has_attack_token=False)) is None


def test_resume_one_rocket_still_refuses_unrecognized_card():
    policy = JinxOpeningPolicy(jinx_summoned=True, rockets_already_played=1)
    assert policy.decide(state([card(0, "", 1)], mana=2)) is None


def test_post_jinx_unnamed_cards_are_not_assumed_to_be_rockets():
    policy = load("jinx").make_policy()
    policy.step = 2
    before = state([card(0, "", 1), card(1, "", 1)], mana=2)
    assert policy.decide(before) is None


def test_post_jinx_uses_spell_mana_and_skips_unknown_cost():
    policy = JinxOpeningPolicy(jinx_summoned=True)
    rockets = [card(i, "超威能死亡火箭！", 1) for i in range(2)]
    before = replace(state(rockets, mana=0), spell_mana=1)
    assert policy.decide(before) == Action(
        type=ActionType.PLAY_CARD, card_index=0, raw={"jinx_rocket": True}
    )
    assert policy.decide(replace(before, spell_mana=None)) is None
    assert policy.decide(replace(before, hand=[replace(rockets[0], cost=-1), rockets[1]])) == Action(
        ActionType.PLAY_CARD, card_index=1, raw={"jinx_rocket": True}
    )


def test_post_jinx_prioritizes_identified_rocket_even_when_other_cards_are_unknown():
    policy = JinxOpeningPolicy(jinx_summoned=True)
    rocket = card(1, "超威能死亡火箭！", 1)
    assert policy.decide(state([card(0, "", 1), rocket, card(2, "砰砰", 1)], mana=2)) == Action(
        ActionType.PLAY_CARD, card_index=1, raw={"jinx_rocket": True}
    )


def test_unrecognized_cards_do_not_block_pow_but_rocket_takes_priority():
    policy = JinxOpeningPolicy(jinx_summoned=True, rockets_already_played=1)
    enemy = Unit("", 2, 1, Rect(0, 0, 10, 10))
    s = replace(state([card(0, "", 1), card(1, "砰砰", 1)], mana=0),
                enemy_units=[enemy], spell_mana=1,
                readings={"spell_mana": Reading(1, 0)})
    assert policy.decide(s) == Action(ActionType.PLAY_CARD, card_index=1,
                                      raw={"spell_mana_only": True})
    assert policy.decide(replace(s, spell_mana=None)) is None
    assert policy.decide(replace(s, readings={"spell_mana": Reading(1, 1)})) is None
    rocket = card(0, "超威能死亡火箭！", 1)
    assert policy.decide(replace(s, hand=[rocket, s.hand[1]])).raw == {"jinx_rocket": True}
    assert policy.decide(replace(s, ui_state=UIState.UNKNOWN)) is None


@pytest.mark.parametrize(("policy_kwargs", "name"), [
    ({}, "應急裝置"),
    ({"spell_already_played": True}, "吉茵珂絲"),
    ({"jinx_summoned": True}, "超威能死亡火箭！"),
    ({"jinx_summoned": True, "rockets_already_played": 2}, "砰砰"),
])
@pytest.mark.parametrize("invalid", [{"drag_point_valid": False}, {"cost": -1}, {"cost": 4}])
def test_jinx_skips_unusable_card_and_tries_next_candidate(policy_kwargs, name, invalid):
    policy = JinxOpeningPolicy(**policy_kwargs)
    first = replace(card(0, name, 1), **invalid)
    second = card(1, name, 1)
    s = replace(state([first, second], mana=2),
                enemy_units=[Unit("", 1, 1, Rect(0, 350, 10, 10))])
    assert policy.decide(s).card_index == 1
    assert policy.decide(replace(s, hand=[first])) is None


@pytest.mark.parametrize(("policy_kwargs", "name"), [
    ({}, "應急裝置"),
    ({"spell_already_played": True}, "吉茵珂絲"),
    ({"jinx_summoned": True}, "超威能死亡火箭！"),
    ({"jinx_summoned": True, "rockets_already_played": 2}, "砰砰"),
])
def test_unknown_mana_never_makes_negative_cost_playable(policy_kwargs, name):
    policy = JinxOpeningPolicy(**policy_kwargs)
    s = replace(state([card(0, name, -1)], mana=-1),
                enemy_units=[Unit("", 1, 1, Rect(0, 350, 10, 10))])
    assert policy.decide(s) is None


@pytest.mark.parametrize(("policy_kwargs", "name"), [
    ({}, "應急裝置"), ({"jinx_summoned": True}, "超威能死亡火箭！"),
])
def test_spell_mana_can_pay_when_regular_mana_is_unknown(policy_kwargs, name):
    policy = JinxOpeningPolicy(**policy_kwargs)
    s = replace(state([card(0, name, 2)], mana=-1), spell_mana=2)
    assert policy.decide(s).card_index == 0


def test_post_jinx_does_not_play_unknown_large_hand():
    policy = load("jinx").make_policy()
    policy.step = 2
    before = state([card(i, "", 1) for i in range(5)], mana=5)
    assert policy.decide(before) is None
