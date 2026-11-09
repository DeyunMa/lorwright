"""旧截图验证通用「继续」原子操作，不代表当前版本实机验证。"""

from pathlib import Path

import cv2
import pytest

from lorwright.act.translate import ActionTranslator
from lorwright.models import Action, ActionType, GameState, Layout
from lorwright.perceive.buttons import find_continue_button
from lorwright.perceive.state import StateParser
from lorwright.perceive.ui_state import UIStateDetector

FIXTURES = Path(__file__).parent / "fixtures"


def _image(path: Path):
    image = cv2.imread(str(path))
    assert image is not None
    return image


@pytest.mark.parametrize(("name", "expected"), [
    ("challenge_result.png", (477, 470)),
    ("challenge_experience.png", (480, 477)),
    ("vault_experience.png", (636, 495)),
])
@pytest.mark.parametrize("scale", [1, 2])
def test_continue_button_actual_location(name, expected, scale):
    image = _image(FIXTURES / "continue" / name)
    image = cv2.resize(image, (960 * scale, 540 * scale), interpolation=cv2.INTER_AREA)
    button = find_continue_button(image)
    assert button is not None
    assert abs(button.center[0] - expected[0] * scale) <= 6 * scale
    assert abs(button.center[1] - expected[1] * scale) <= 6 * scale
    plan = ActionTranslator(Layout()).translate(
        Action(ActionType.CONTINUE), GameState(continue_button=button)
    )
    assert plan is not None and plan.points == [button.center]


@pytest.mark.parametrize("path", [
    "continue/victory_banner.png",
    "mapnav/1080p_jinx_travel.png",
    "screens/1080p_login_form.png",
    "screens/1080p_targeting.png",
])
def test_absent_continue_never_creates_click_plan(path):
    button = find_continue_button(_image(FIXTURES / path))
    assert button is None
    assert ActionTranslator(Layout()).translate(
        Action(ActionType.CONTINUE), GameState(continue_button=button)
    ) is None


def test_multiple_continue_buttons_are_ambiguous():
    image = _image(FIXTURES / "continue" / "challenge_result.png")
    image[450:489, 200:336] = image[450:489, 409:545]
    assert find_continue_button(image) is None


def test_parser_exposes_continue_without_claiming_screen_type():
    image = _image(FIXTURES / "continue" / "challenge_result.png")
    parser = StateParser(Layout(), UIStateDetector(root="__missing__"))
    state = parser.parse(image)
    assert state.ui_state.value == "unknown"
    assert state.continue_button is not None
