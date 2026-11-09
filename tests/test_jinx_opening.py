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


def test_already_expanded_hand_still_starts_with_spell():
    # 起手直接是展开态时，也要先打應急裝置，而不是因为 _board_before=None 弃权。
    policy = load("jinx").make_policy()
    spell, hero = card(1, "應急裝置", 1), card(2, "吉茵珂絲", 2)
    state_now = state([card(0, "其他牌", 1), spell, hero])
    assert policy.decide(state_now) == Action(type=ActionType.PLAY_CARD, card_index=1)


def test_unknown_wrong_cost_and_expansion_do_not_advance():
    policy = load("jinx").make_policy()
    collapsed = state([card(0, "", 1)], expanded=False)
    action = policy.decide(collapsed)
    assert action.type is ActionType.PLAY_CARD
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


def test_resume_after_jinx_starts_at_fleeting_step():
    policy = JinxOpeningPolicy(jinx_summoned=True)
    assert policy.step == 2
    rocket = card(0, "超威能死亡火箭！", 1)
    assert policy.decide(state([rocket], mana=1)) == Action(
        type=ActionType.PLAY_CARD, card_index=0
    )


def test_mulligan_keeps_combo_cards_and_confirms():
    policy = load("jinx").make_policy()
    mulligan = GameState(
        ui_state=UIState.MULLIGAN,
        mulligan_cards=[
            card(0, "應急裝置", 1), card(1, "吉茵珂絲", 2),
            card(2, "其他牌", 3), card(3, "其他牌", 3),
        ],
    )
    assert policy.decide(mulligan).type is ActionType.CONFIRM


def test_mulligan_replaces_cards_missing_from_combo():
    policy = load("jinx").make_policy()
    mulligan = GameState(
        ui_state=UIState.MULLIGAN,
        mulligan_cards=[
            card(0, "應急裝置", 1), card(1, "其他牌", 2),
            card(2, "其他牌", 3), card(3, "其他牌", 3),
        ],
    )
    action = policy.decide(mulligan)
    assert action.type is ActionType.MULLIGAN_REPLACE
    assert len(action.raw["points"]) == 3
    # 换牌动作发出后，下一次决策直接確認，不能反复换牌。
    assert policy.decide(mulligan).type is ActionType.CONFIRM


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


def test_post_jinx_plays_two_rockets_then_pow_pow():
    policy = load("jinx").make_policy()
    policy.step = 2

    def rocket(index):
        return card(index, "超威能死亡火箭！", 1)

    def pow_pow(index):
        return card(index, "砰砰", 1)

    before = state([rocket(0), rocket(1), pow_pow(2)], mana=3)
    first = policy.decide(before)
    assert first == Action(type=ActionType.PLAY_CARD, card_index=0)
    policy.on_action_outcome(first, before, state([rocket(0), pow_pow(1)], mana=2))
    assert policy._rockets_played == 1

    after_first = state([rocket(0), pow_pow(1)], mana=2)
    second = policy.decide(after_first)
    assert second == Action(type=ActionType.PLAY_CARD, card_index=0)
    policy.on_action_outcome(second, after_first, state([pow_pow(0)], mana=1))
    assert policy._rockets_played == 2

    third = policy.decide(state([pow_pow(0)], mana=1))
    assert third == Action(type=ActionType.PLAY_CARD, card_index=0)


def test_post_jinx_unnamed_two_cards_play_leftmost():
    policy = load("jinx").make_policy()
    policy.step = 2
    before = state([card(0, "", 1), card(1, "", 1)], mana=2)
    assert policy.decide(before) == Action(type=ActionType.PLAY_CARD, card_index=0)


def test_post_jinx_does_not_play_unknown_large_hand():
    policy = load("jinx").make_policy()
    policy.step = 2
    before = state([card(i, "", 1) for i in range(5)], mana=5)
    assert policy.decide(before) is None
