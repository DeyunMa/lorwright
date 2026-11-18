"""实拍可选选牌识别，以及合成后继的动作安全边界。"""

from dataclasses import replace

import cv2
import pytest

from lorwright.cli.app import _battle_layers
from lorwright.core.act.translate import ActionTranslator
from lorwright.core.champions import load
from lorwright.core.config import load_settings
from lorwright.core.decide.router import Router
from lorwright.core.loop.adventure import AdventureLoop
from lorwright.core.loop.engine import Engine
from lorwright.core.loop.outcome import ActionOutcome, OutcomeStatus
from lorwright.core.models import Action, ActionType, GameState, UIState
from lorwright.core.perceive.state import StateParser
from lorwright.core.perceive.ui_state import UIStateDetector
from tools.test_data import fixtures_root


def _image():
    image = cv2.imread(str(fixtures_root() / "screens/f1-optional-choice-20261116.png"))
    assert image is not None
    return image


def _detector():
    layout = load_settings().layout.to_layout()
    detector = UIStateDetector(action_button=layout.end_turn)
    detector.load()
    return detector


def _parse(image):
    layout = load_settings().layout.to_layout()
    parser = StateParser(layout, UIStateDetector(action_button=layout.end_turn))
    parser.load()
    return parser.parse(image)


@pytest.mark.parametrize("missing_column", [490, 810, 1130])
def test_two_choice_cost_frames_block_idle_when_other_controls_are_missing(missing_column):
    image = _image()
    image[245:345, 195:290] = 0
    image[325:405, missing_column:missing_column + 70] = 0
    # 合成文字消失，保留原蓝色按钮；整块涂黑会掩盖蓝色兜底误判。
    prompt = image[505:585, 1685:1810]
    prompt[prompt.min(axis=2) > 150] = image[590, 1730]
    assert _parse(image).ui_state is UIState.UNKNOWN


@pytest.mark.parametrize("column", [490, 810, 1130])
@pytest.mark.parametrize("name,expected", [
    ("1080p_battle_turn2.png", UIState.MY_TURN_IDLE),
    ("1080p_block_phase.png", UIState.BLOCKING),
    ("1080p_targeting.png", UIState.TARGETING),
    ("1080p_mulligan.png", UIState.MULLIGAN),
])
def test_one_cost_frame_does_not_override_normal_battle_state(column, name, expected):
    image = cv2.imread(str(fixtures_root() / f"screens/{name}"))
    assert image is not None
    assert _parse(image).ui_state is expected
    source = _image()
    image[325:405, column:column + 70] = source[325:405, column:column + 70]
    assert _parse(image).ui_state is expected


@pytest.mark.parametrize("area", [
    (1685, 505, 125, 80),  # 跳过文字
    (195, 245, 95, 100),  # 选择区收起控件
    (490, 325, 70, 80),
    (810, 325, 70, 80),
    (1130, 325, 70, 80),
])
def test_incomplete_choice_blocks_blue_button_fallback(area):
    image = _image()
    x, y, w, h = area
    image[y:y + h, x:x + w] = 0
    assert _detector().detect(image) is UIState.UNKNOWN


def test_darkened_choice_does_not_allow_skip():
    image = (_image().astype(float) * 0.5).astype("uint8")
    assert _detector().detect(image) is not UIState.OPTIONAL_CHOICE


@pytest.mark.parametrize("name", ["1080p_battle_turn2.png", "1080p_block_phase.png",
                                  "1080p_targeting.png", "1080p_mulligan.png"])
def test_other_action_buttons_do_not_allow_skip(name):
    image = cv2.imread(str(fixtures_root() / f"screens/{name}"))
    assert image is not None
    assert _detector().detect(image) is not UIState.OPTIONAL_CHOICE


@pytest.mark.parametrize("champion", ["jinx", "elise"])
def test_real_choice_routes_to_one_skip_with_existing_champion_layers(champion):
    ui = _detector().detect(_image())
    assert ui is UIState.OPTIONAL_CHOICE
    state = GameState(ui_state=ui)
    routed = Router(_battle_layers(load(champion))).decide(state)
    assert routed.action.type is ActionType.SKIP_CHOICE
    assert routed.layer == "optional_choice"
    assert Engine._missing_action_evidence(routed.action, state) == []
    layout = load_settings().layout.to_layout()
    plan = ActionTranslator(layout).translate(routed.action, state)
    assert plan is not None and plan.points == [layout.end_turn.center]
    assert ui in AdventureLoop.BATTLE_STATES


@pytest.mark.parametrize("ui", list(UIState))
def test_skip_requires_choice_and_only_succeeds_on_known_battle_successor(ui):
    before = GameState(ui_state=UIState.OPTIONAL_CHOICE)
    after = replace(before, ui_state=ui)
    action = Action(ActionType.SKIP_CHOICE)
    outcome = ActionOutcome(action, before, 8).observe(after, 1)
    accepted = {UIState.MY_TURN_IDLE, UIState.ENEMY_TURN, UIState.COMBAT_RESOLVING,
                UIState.BLOCKING, UIState.TARGETING, UIState.BATTLE_END}
    assert outcome.status is (OutcomeStatus.SUCCEEDED if ui in accepted
                              else OutcomeStatus.WAITING)
    if ui not in accepted:
        assert ActionOutcome(action, before, 8).observe(after, 8).status is OutcomeStatus.TIMED_OUT
    translator = ActionTranslator(load_settings().layout.to_layout())
    if ui is not UIState.OPTIONAL_CHOICE:
        assert translator.translate(action, after) is None
        assert Engine._missing_action_evidence(action, after) == ["optional_choice"]
        assert ActionOutcome(action, after, 8).observe(after, 1).status is OutcomeStatus.WAITING


def test_play_releases_pending_for_choice_without_claiming_play_success():
    before = GameState(ui_state=UIState.MY_TURN_IDLE, hand_expanded=True)
    after = replace(before, ui_state=UIState.OPTIONAL_CHOICE)
    outcome = ActionOutcome(Action(ActionType.PLAY_CARD, card_index=0), before, 8).observe(after, 1)
    assert outcome.status is OutcomeStatus.NEEDS_INPUT
    assert outcome.reason == "optional_choice_required"
