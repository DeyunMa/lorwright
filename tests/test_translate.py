from lorwright.act.translate import ActionTranslator, Layout
from lorwright.models import (
    Action,
    ActionType,
    CardInHand,
    GameState,
    Rect,
    Unit,
)

LAYOUT = Layout(
    end_turn=Rect(1700, 900, 100, 60),
    enemy_nexus=Rect(900, 200, 120, 120),
    play_area=Rect(900, 500, 200, 200),
)


def test_end_turn_click() -> None:
    t = ActionTranslator(LAYOUT)
    plan = t.translate(Action(type=ActionType.END_TURN), GameState())
    assert plan is not None
    assert plan.points == [(1750, 930)]


def test_play_card_two_clicks() -> None:
    state = GameState(hand=[CardInHand(0, "蜘蛛", 1, Rect(100, 1000, 80, 120))])
    t = ActionTranslator(LAYOUT)
    plan = t.translate(Action(type=ActionType.PLAY_CARD, card_index=0), state)
    assert plan is not None
    assert plan.points[0] == (140, 1060)
    assert plan.points[1] == (1000, 600)


def test_attack_uses_first_available_unit() -> None:
    state = GameState(my_units=[Unit("s", 2, 2, Rect(400, 600, 80, 80))])
    t = ActionTranslator(LAYOUT)
    plan = t.translate(Action(type=ActionType.ATTACK, target="nexus"), state)
    assert plan is not None
    assert plan.points[0] == (440, 640)


def test_missing_layout_returns_none() -> None:
    t = ActionTranslator(Layout())
    assert t.translate(Action(type=ActionType.END_TURN), GameState()) is None
