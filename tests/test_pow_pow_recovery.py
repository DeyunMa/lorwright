from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import cv2

from lorwright.core.act.translate import ActionTranslator
from lorwright.core.champions.jinx.policy import JinxOpeningPolicy
from lorwright.core.champions.jinx.vision import recognize_targeted_spell
from lorwright.core.loop.engine import Engine
from lorwright.core.loop.outcome import ActionOutcome, OutcomeStatus
from lorwright.core.loop.readiness import ActionReadiness
from lorwright.core.models import (
    Action,
    ActionType,
    GameState,
    Layout,
    Rect,
    TargetedSpell,
    UIState,
)
from lorwright.core.perceive.normalize import Scale
from lorwright.core.perceive.state import StateParser


def test_synthetic_target_recovery():
    state = GameState(ui_state=UIState.TARGETING,
                      targeted_spell=TargetedSpell("砰砰", Rect(930, 508, 60, 60)))
    action = JinxOpeningPolicy().decide(state)
    assert action.type is ActionType.CANCEL
    plan = ActionTranslator(Layout(hand_region=Rect(1420, 855, 500, 225))).translate(action, state)
    assert plan.drag and plan.drag_hold_ms > 0
    assert plan.points == [(960, 538), (1670, 967)]
    device = Mock()
    engine = SimpleNamespace(device=device, _scale=Scale(0.5, 0.5),
                             _readiness=ActionReadiness(), _readiness_deadline=None)
    assert Engine._execute(engine, plan) == 2
    device.drag.assert_called_once_with(480, 269, 835, 484, plan.drag_hold_ms, plan.drag_ms)
    pending = ActionOutcome(action, state, 8)
    assert pending.observe(state, 1).status is OutcomeStatus.WAITING
    assert pending.observe(replace(state, ui_state=UIState.UNKNOWN), 2).status is OutcomeStatus.WAITING
    assert pending.observe(state, 8).status is OutcomeStatus.TIMED_OUT
    assert pending.observe(replace(state, ui_state=UIState.MY_TURN_IDLE), 2).status is OutcomeStatus.SUCCEEDED


def test_generic_action_requires_visible_spell_and_correct_state():
    layout = Layout(hand_region=Rect(1420, 855, 500, 225))
    state = GameState(ui_state=UIState.TARGETING)
    assert JinxOpeningPolicy().decide(state).type is ActionType.NO_OP
    other = replace(state, targeted_spell=TargetedSpell("other", Rect(930, 508, 60, 60)))
    assert JinxOpeningPolicy().decide(other).type is ActionType.NO_OP
    action = Action(ActionType.CANCEL, raw={"return_to_hand": True})
    translator = ActionTranslator(layout)
    assert translator.translate(action, state) is None
    assert translator.translate(action, replace(other, ui_state=UIState.UNKNOWN)) is None
    assert ActionTranslator(Layout()).translate(action, other) is None
    assert translator.translate(action, other).points == [(960, 538), (1670, 967)]


def test_missing_template_and_non_targeting_screen_do_not_produce_evidence(monkeypatch):
    frame = cv2.imread("tests/fixtures/screens/1080p_targeting.png")
    assert frame is not None
    monkeypatch.setattr("lorwright.core.champions.jinx.vision._targeted_spell_template", lambda: None)
    assert recognize_targeted_spell(frame) is None
    callback = Mock(return_value=TargetedSpell("砰砰", Rect(930, 508, 60, 60)))
    ui = Mock()
    ui.detect.return_value = UIState.UNKNOWN
    state = StateParser(Layout(), ui, targeted_spell_recognizer=callback).parse(frame)
    assert state.targeted_spell is None
    callback.assert_not_called()
