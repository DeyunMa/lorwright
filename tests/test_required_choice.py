"""实拍强制三选一识别（无「略過」），以及选取候选的动作安全边界。"""

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
from lorwright.core.perceive.ui_state import TEXT_BAND, UIStateDetector
from tools.test_data import fixtures_root


def _image():
    image = cv2.imread(str(fixtures_root() / "screens/f1-required-choice-20261121.png"))
    assert image is not None
    return image


def _skip_image():
    image = cv2.imread(
        str(fixtures_root() / "screens/f1-optional-target-skip-20261121.png"))
    assert image is not None
    return image


def test_optional_target_skip_reads_action_skip_and_parses_targeting():
    # 可选目标提示：动作按钮读「跳過」，识别为 TARGETING 并带一个敌方目标。
    image = _skip_image()
    assert _detector().action_prompt(image) == "action_skip"
    assert _detector().detect(image) is UIState.TARGETING
    state = _parse(image)
    assert state.ui_state is UIState.TARGETING
    assert state.action_prompt == "action_skip"
    assert len(state.enemy_units) == 1


def test_optional_target_skip_requires_readable_prompt():
    # 按钮文字涂黑后不得升级为目标提示（skip 控件单独不足为证）。
    image = _skip_image()
    _mask_action_prompt(image)
    assert _detector().detect(image) is UIState.UNKNOWN


def _spells_image():
    image = cv2.imread(
        str(fixtures_root() / "screens/f1-required-choice-spells-20261121.png"))
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


def _mask_action_prompt(image: cv2.Mat) -> None:
    """按 action_prompt 的同一搜索带涂黑按钮文字。"""
    b = load_settings().layout.to_layout().end_turn
    dx, dy, kw, kh = TEXT_BAND
    x = b.x - int(b.w * (kw - 1) / 2)
    y = b.y + int(b.h * dy)
    image[y:y + int(b.h * kh), x:x + int(b.w * kw)] = 0


def test_real_required_choice_detects_via_detector_and_parser():
    image = _image()
    assert _detector().detect(image) is UIState.REQUIRED_CHOICE
    assert _parse(image).ui_state is UIState.REQUIRED_CHOICE


@pytest.mark.parametrize("name,expected", [
    ("f1-optional-choice-20261116.png", UIState.OPTIONAL_CHOICE),
    ("1080p_battle_turn2.png", UIState.MY_TURN_IDLE),
    ("1080p_block_phase.png", UIState.BLOCKING),
    ("1080p_targeting.png", UIState.TARGETING),
    ("1080p_mulligan.png", UIState.MULLIGAN),
])
def test_required_choice_does_not_reclassify_existing_frames(name, expected):
    image = cv2.imread(str(fixtures_root() / f"screens/{name}"))
    assert image is not None
    assert _detector().detect(image) is expected


def test_spell_candidates_on_other_board_detect_required_choice():
    # 同一强制三选一布局在棕色棋盘上：收起控件为背景变体。
    image = _spells_image()
    assert _detector().detect(image) is UIState.REQUIRED_CHOICE
    assert _parse(image).ui_state is UIState.REQUIRED_CHOICE


def test_spells_frame_masked_target_prompt_keeps_unknown():
    image = _spells_image()
    _mask_action_prompt(image)
    assert _detector().detect(image) is UIState.UNKNOWN


@pytest.mark.parametrize("area", [
    (195, 245, 95, 100),  # 选择区收起控件
    (810, 325, 70, 80),   # 中间费用框
])
def test_spells_frame_missing_control_does_not_yield_required(area):
    image = _spells_image()
    x, y, w, h = area
    image[y:y + h, x:x + w] = 0
    assert _detector().detect(image) is not UIState.REQUIRED_CHOICE


def test_masked_target_prompt_keeps_unknown():
    image = _image()
    _mask_action_prompt(image)
    assert _detector().detect(image) is UIState.UNKNOWN


@pytest.mark.parametrize("area", [
    (195, 245, 95, 100),  # 选择区收起控件
    (490, 325, 70, 80),
    (810, 325, 70, 80),
    (1130, 325, 70, 80),
])
def test_missing_choice_control_does_not_yield_required(area):
    image = _image()
    x, y, w, h = area
    image[y:y + h, x:x + w] = 0
    assert _detector().detect(image) is not UIState.REQUIRED_CHOICE


@pytest.mark.parametrize("champion", ["jinx", "elise"])
def test_real_required_choice_routes_to_leftmost_pick(champion):
    ui = _detector().detect(_image())
    assert ui is UIState.REQUIRED_CHOICE
    state = GameState(ui_state=ui)
    routed = Router(_battle_layers(load(champion))).decide(state)
    assert routed.action.type is ActionType.PICK_CHOICE
    assert routed.action.card_index == 0
    assert routed.layer == "required_choice"
    assert Engine._missing_action_evidence(routed.action, state) == []
    plan = ActionTranslator(load_settings().layout.to_layout()).translate(
        routed.action, state)
    assert plan is not None and plan.points == [(640, 535)]
    assert ui in AdventureLoop.BATTLE_STATES


@pytest.mark.parametrize("champion", ["jinx", "elise"])
def test_champion_policies_abstain_on_required_choice(champion):
    assert load(champion).make_policy().decide(
        GameState(ui_state=UIState.REQUIRED_CHOICE)) is None


@pytest.mark.parametrize("ui", list(UIState))
def test_pick_requires_choice_and_only_succeeds_on_known_battle_successor(ui):
    before = GameState(ui_state=UIState.REQUIRED_CHOICE)
    after = replace(before, ui_state=ui)
    action = Action(ActionType.PICK_CHOICE, card_index=0)
    outcome = ActionOutcome(action, before, 8).observe(after, 1)
    accepted = {UIState.MY_TURN_IDLE, UIState.ENEMY_TURN, UIState.COMBAT_RESOLVING,
                UIState.BLOCKING, UIState.TARGETING, UIState.BATTLE_END}
    assert outcome.status is (OutcomeStatus.SUCCEEDED if ui in accepted
                              else OutcomeStatus.WAITING)
    if ui not in accepted:
        assert ActionOutcome(action, before, 8).observe(after, 8).status is OutcomeStatus.TIMED_OUT
    translator = ActionTranslator(load_settings().layout.to_layout())
    if ui is not UIState.REQUIRED_CHOICE:
        assert translator.translate(action, after) is None
        assert Engine._missing_action_evidence(action, after) == ["required_choice"]
        assert ActionOutcome(action, after, 8).observe(after, 1).status is OutcomeStatus.WAITING


def test_play_releases_pending_for_required_choice_without_play_success():
    before = GameState(ui_state=UIState.MY_TURN_IDLE, hand_expanded=True)
    after = replace(before, ui_state=UIState.REQUIRED_CHOICE)
    outcome = ActionOutcome(Action(ActionType.PLAY_CARD, card_index=0), before, 8).observe(after, 1)
    assert outcome.status is OutcomeStatus.NEEDS_INPUT
    assert outcome.reason == "required_choice_required"


@pytest.mark.parametrize("index", [None, -1, 3, True])
def test_pick_with_invalid_index_translates_to_nothing(index):
    state = GameState(ui_state=UIState.REQUIRED_CHOICE)
    action = Action(ActionType.PICK_CHOICE, card_index=index)
    translator = ActionTranslator(load_settings().layout.to_layout())
    assert translator.translate(action, state) is None
