from lorwright.decide.candidates import describe, generate
from lorwright.models import ActionType, CardInHand, GameState, Rect, UIState, Unit


def _card(i, cost, name="c"):
    return CardInHand(index=i, name=name, cost=cost, rect=Rect(0, 0, 10, 10))


def test_generate_only_affordable() -> None:
    state = GameState(mana=2, hand=[_card(0, 1), _card(1, 5)])
    acts = generate(state)
    play = [a for a in acts if a.type is ActionType.PLAY_CARD]
    assert len(play) == 1
    assert play[0].card_index == 0


def test_generate_always_has_end_turn() -> None:
    acts = generate(GameState())
    assert any(a.type is ActionType.END_TURN for a in acts)


def test_attack_candidate_only_with_units() -> None:
    state = GameState(my_units=[Unit("s", 1, 1, Rect(0, 0, 1, 1))])
    assert any(a.type is ActionType.ATTACK for a in generate(state))
    assert not any(a.type is ActionType.ATTACK for a in generate(GameState()))


def test_describe() -> None:
    state = GameState(hand=[_card(0, 1, "蜘蛛")])
    assert "蜘蛛" in describe(ActionType_play(0), state)


def ActionType_play(i):
    from lorwright.models import Action

    return Action(type=ActionType.PLAY_CARD, card_index=i)
