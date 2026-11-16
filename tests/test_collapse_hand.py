"""收起手牌的决策安全回归。"""

from lorwright.core.act.translate import ActionTranslator
from lorwright.core.config import load_settings
from lorwright.core.decide.generic import AttackWhenTokenPolicy, ExpandHandPolicy
from lorwright.core.decide.router import Router
from lorwright.core.loop.outcome import ActionOutcome, OutcomeStatus
from lorwright.core.models import Action, ActionType, CardInHand, GameState, Rect, UIState, Unit


def test_collapse_only_from_idle_expanded_and_requires_verified_result():
    layout = load_settings().layout.to_layout()
    translator = ActionTranslator(layout)
    action = Action(ActionType.COLLAPSE_HAND)
    before = GameState(ui_state=UIState.MY_TURN_IDLE, hand_expanded=True)
    assert translator.translate(action, before).points == [(500, 620)]
    for ui in (UIState.UNKNOWN, UIState.TARGETING):
        assert translator.translate(action, GameState(ui_state=ui, hand_expanded=True)) is None
        assert ActionOutcome(action, before, 10).observe(
            GameState(ui_state=ui), 1).status is OutcomeStatus.WAITING
    assert ActionOutcome(action, before, 1).observe(before, 1).status is OutcomeStatus.TIMED_OUT
    after = GameState(ui_state=UIState.MY_TURN_IDLE, hand_expanded=False)
    assert ActionOutcome(action, before, 10).observe(after, 1).status is OutcomeStatus.SUCCEEDED


def test_board_inspection_attacks_or_ends_turn_without_reexpanding():
    router = Router([ExpandHandPolicy(), AttackWhenTokenPolicy()])
    state = GameState(ui_state=UIState.MY_TURN_IDLE, has_attack_token=True,
                      hand=[CardInHand(0, '', 1, Rect(0, 0, 10, 10))],
                      my_units=[Unit('', 1, 1, Rect(500, 850, 50, 50))])
    assert router.decide(state, suppress_hand_expansion=True).action.type is ActionType.ATTACK
    state.my_units.clear()
    assert router.decide(state, suppress_hand_expansion=True).action.type is ActionType.END_TURN
