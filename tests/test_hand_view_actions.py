"""手牌视图动作独立于出牌，缺失费用不妨碍取证。"""
from dataclasses import replace

from lorwright.core.act.translate import ActionTranslator
from lorwright.core.decide.generic import ExpandHandPolicy
from lorwright.core.loop.outcome import ActionOutcome, OutcomeStatus
from lorwright.core.loop.readiness import ActionReadiness
from lorwright.core.models import Action, ActionType, CardInHand, GameState, Layout, Rect, UIState


def collapsed():
    return GameState(ui_state=UIState.MY_TURN_IDLE, hand_expanded=False,
                     hand=[CardInHand(0, "", -1, Rect(1400, 900, 30, 40))])


def test_expand_has_independent_intent_and_never_drags():
    state = collapsed()
    action = ExpandHandPolicy().decide(state)
    assert action.type.value == "expand_hand"
    assert action.card_index is None
    layout = Layout(hand_region=Rect(1420, 855, 500, 225))
    plan = ActionTranslator(layout).translate(action, state)
    assert plan.points == [layout.hand_region.center]
    assert not plan.drag
    assert ActionTranslator(layout).translate(Action(ActionType.PLAY_CARD, 0), state) is None
    assert ActionTranslator(layout).translate(action, replace(state, hand_expanded=True)) is None
    assert ActionTranslator(layout).translate(action, replace(state, hand=[])) is None
    assert ActionTranslator(layout).translate(action, replace(state, ui_state=UIState.UNKNOWN)) is None


def test_expand_readiness_uses_view_evidence_without_card_identity():
    state = collapsed()
    action = Action(ActionType.EXPAND_HAND)
    readiness = ActionReadiness()
    readiness.observe(state)
    assert not readiness.ready(action)
    readiness.observe(replace(state, hand=[replace(state.hand[0], cost=10, name="新牌")]))
    assert readiness.ready(action)
    readiness.observe(replace(state, hand=[]))
    assert not readiness.ready(action)
    readiness.reset()
    assert not readiness.ready(action)


def test_expand_result_requires_known_idle_expanded_view_and_keeps_deadline():
    state = collapsed()
    pending = ActionOutcome(Action(ActionType.EXPAND_HAND), state, 8)
    assert pending.observe(state, 1).status is OutcomeStatus.WAITING
    for ui in (UIState.UNKNOWN, UIState.TARGETING, UIState.COMBAT_RESOLVING):
        assert pending.observe(replace(state, hand_expanded=True, ui_state=ui), 2).status is OutcomeStatus.WAITING
    after = replace(state, hand_expanded=True)
    assert pending.observe(after, 3).reason == "hand_expanded"
    assert pending.observe(after, 8).status is OutcomeStatus.TIMED_OUT
    assert pending.deadline == 8
    play = ActionOutcome(Action(ActionType.PLAY_CARD, 0), state, 8)
    assert play.observe(after, 3).status is OutcomeStatus.WAITING
