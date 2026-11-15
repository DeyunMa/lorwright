from pathlib import Path

import cv2
import numpy as np
import pytest

from lorwright.core.perceive.revive_screen import find_revive_button

FIXTURES = Path(__file__).parent / "fixtures"


def _image(name: str) -> np.ndarray:
    image = cv2.imread(str(FIXTURES / name))
    assert image is not None
    return image


def test_recognizes_f1_revive_screen():
    button = find_revive_button(_image("screens/f1-revive-20261115.png"))
    assert button is not None
    assert button.center == (960, 912)


@pytest.mark.parametrize("bounds", [(460, 600, 620, 660), (804, 858, 960, 967),
                                     (960, 858, 1116, 967)])
def test_rejects_obscured_message_or_button(bounds):
    image = _image("screens/f1-revive-20261115.png")
    x1, y1, x2, y2 = bounds
    image[y1:y2, x1:x2] = 0
    assert find_revive_button(image) is None


def test_rejects_dimmed_and_blurred_screens():
    image = _image("screens/f1-revive-20261115.png")
    assert find_revive_button((image * 0.5).astype(np.uint8)) is None
    assert find_revive_button(cv2.GaussianBlur(image, (15, 15), 0)) is None


@pytest.mark.parametrize("name", ["screens/1080p_home_adventure_entry.png",
                                  "screens/f1-adventure-resume-20261114.png",
                                  "mapnav/1080p_map.png"])
def test_rejects_other_screens(name):
    assert find_revive_button(_image(name)) is None
