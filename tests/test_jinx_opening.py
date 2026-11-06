from dataclasses import replace

from lorwright.champions import load
from lorwright.champions.jinx.policy import JinxOpeningPolicy
from lorwright.models import Action, ActionType, CardInHand, GameState, Rect, UIState, Unit


def card(index, name, cost):
    return CardInHand(index, name, cost, Rect(0, 0, 8, 8))


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


def test_unknown_wrong_cost_and_expansion_do_not_advance():
    policy = load("jinx").make_policy()
    collapsed = state([card(0, "", 1)], expanded=False)
    assert policy.decide(collapsed).type is ActionType.NO_OP
    assert policy.decide(collapsed).type is ActionType.NO_OP
    action = policy.decide(collapsed)
    policy.on_action_outcome(action, collapsed, replace(collapsed, hand_expanded=True))
    assert policy.step == 0
    assert policy.decide(state([card(0, "", 1), card(1, "吉茵珂絲", 2)])) is None
    assert policy.decide(state([card(0, "應急裝置", 2)])) is None
    assert policy.decide(state([card(0, "應急裝置", 1)], mana=0)) is None


def test_new_mulligan_resets_opening():
    policy = load("jinx").make_policy()
    policy.step = 2
    assert policy.decide(GameState(ui_state=UIState.MULLIGAN)).type is ActionType.CONFIRM
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


def test_hero_is_not_played_twice_while_board_confirmation_is_pending():
    policy = load("jinx").make_policy()
    unit = Unit("", -1, -1, Rect(0, 0, 10, 10))
    hero = card(1, "吉茵珂絲", 2)
    policy.step = 1
    policy.decide(state([hero], [unit], expanded=False))
    before = state([hero, card(2, "吉茵珂絲", 2)])
    action = policy.decide(before)
    policy.on_action_outcome(action, before, state([hero], [unit], mana=0))
    assert policy.decide(state([hero], [unit], mana=2)).type is ActionType.NO_OP
    assert policy.step == 1
    assert policy.decide(state([], [unit, unit], mana=0)).type is ActionType.NO_OP
    assert policy.step == 2
