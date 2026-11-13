"""起手按钮的真实帧与有限遮挡回归。"""
from pathlib import Path

import cv2
import numpy as np
import pytest

from lorwright.perceive.mulligan import recognize_mulligan_selection


def _load(name: str):
    image = cv2.imread(str(Path("tests/fixtures/jinx") / name))
    assert image is not None
    return image


@pytest.mark.parametrize(("name", "expected"), [
    ("mulligan-support-before.png", (False, False, False, False)),
    ("mulligan-support-first-selected.png", (True, False, False, False)),
    ("mulligan-4cards.png", (False, False, False, False)),
])
def test_selection_matches_real_frames(name, expected):
    assert recognize_mulligan_selection(_load(name)) == expected


def test_buttons_not_yet_shown_are_unknown():
    image = cv2.imread("tests/fixtures/screens/1080p_mulligan.png")
    assert image is not None
    assert recognize_mulligan_selection(image) == (False, False, None, None)


def test_normalized_720p_buttons_are_readable():
    image = cv2.imread("tests/fixtures/screens/720p_mulligan.png")
    assert image is not None
    image = cv2.resize(image, (1920, 1080), interpolation=cv2.INTER_AREA)
    assert recognize_mulligan_selection(image) == (False, False, False, False)


def test_obscured_and_dim_buttons_are_unknown():
    image = _load("mulligan-support-before.png")
    cv2.rectangle(image, (472, 812), (493, 866), (0, 0, 0), -1)
    assert recognize_mulligan_selection(image)[0] is None
    image = _load("mulligan-support-before.png")
    image[785:890, 345:628] = (image[785:890, 345:628] * 0.75).astype(np.uint8)
    assert recognize_mulligan_selection(image)[0] is None


def test_other_resolutions_are_unknown_without_normalization():
    assert recognize_mulligan_selection(np.zeros((720, 1280, 3), np.uint8)) == (None,) * 4
