"""结算页实图识别；这些截图不是对完整胜利流程的实机验收。"""

from pathlib import Path

import cv2
import pytest

from lorwright.models import UIState
from lorwright.perceive.buttons import find_continue_button
from lorwright.perceive.result_screen import result_screen
from lorwright.perceive.ui_state import UIStateDetector

FIXTURES = Path("tests/fixtures/continue")


def _load(name):
    image = cv2.imread(str(FIXTURES / name))
    assert image is not None
    return cv2.resize(image, (1920, 1080), interpolation=cv2.INTER_AREA)


@pytest.mark.parametrize(("name", "expected"), [
    ("f1-missions-20261113.jpg", "missions"),
    ("f1-vault-20261113.jpg", "vault"),
    ("vault_experience.png", "vault"),
])
def test_results_require_two_visible_features(name, expected):
    image = _load(name)
    assert result_screen(image) == expected
    assert UIStateDetector().detect(image) is UIState.BATTLE_END
    assert result_screen((image * 0.6).astype("uint8")) is None
    if expected == "missions":
        image[205:255, 548:759] = 0
    else:
        image[40:133, 1178:1367] = 0
    assert result_screen(image) is None


def test_mission_page_has_no_confirmed_continue_but_vault_does():
    assert find_continue_button(_load("f1-missions-20261113.jpg")) is None
    button = find_continue_button(_load("f1-vault-20261113.jpg"))
    assert button is not None and abs(button.center[0] - 1270) < 20


@pytest.mark.parametrize("name", ["challenge_result.png", "challenge_experience.png",
                                  "victory_banner.png"])
def test_unrelated_result_screens_are_not_assumed_to_be_vault_or_missions(name):
    assert result_screen(_load(name)) is None
