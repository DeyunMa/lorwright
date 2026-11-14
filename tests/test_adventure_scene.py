"""地图控件在真实画面及遮挡时的识别回归。"""

from pathlib import Path

import cv2
import numpy as np
import pytest

from lorwright.champions.jinx.vision import recognize_selected_hero
from lorwright.perceive.adventure_scene import find_resume_adventure_button, is_map

FIXTURES = Path(__file__).parent / "fixtures"


def _image(relative: str) -> np.ndarray:
    image = cv2.imread(str(FIXTURES / relative))
    assert image is not None, relative
    return image


@pytest.mark.parametrize("name", [
    "1080p_zoommax.png",
    "1080p_map.png",
    "1080p_jinx_map.png",
    "1080p_node_panel.png",
    "1080p_jinx_support_map.jpg",
])
def test_visible_map_controls_are_recognized(name):
    assert is_map(_image("mapnav/" + name))


@pytest.mark.parametrize("relative", [
    "mapnav/1080p_jinx_exit_prompt.jpg",
    "mapnav/1080p_ability_select.png",
    "mapnav/1080p_jinx_battle_detail.png",
    "support/jinx-1080-selected-left.jpg",
    "card_rewards/before.png",
])
def test_overlay_and_other_scenes_are_not_maps(relative):
    assert not is_map(_image(relative))


@pytest.mark.parametrize("name", ["1080p_zoommax.png", "1080p_jinx_support_map.jpg"])
def test_darkened_map_is_not_authorized(name):
    image = _image("mapnav/" + name)
    darkened = cv2.convertScaleAbs(image, alpha=0.5)
    assert not is_map(darkened)


@pytest.mark.parametrize("bounds", [(1805, 275, 1840, 310), (1805, 370, 1840, 390)])
def test_partially_obscured_zoom_control_is_not_authorized(bounds):
    image = _image("mapnav/1080p_jinx_support_map.jpg")
    x1, y1, x2, y2 = bounds
    image[y1:y2, x1:x2] = 0
    assert not is_map(image)


def test_resume_adventure_recognizes_button_and_selected_jinx():
    image = _image("screens/f1-adventure-resume-20261114.png")
    button = find_resume_adventure_button(image)
    assert button is not None
    assert 1390 <= button.x <= 1410 and 940 <= button.y <= 955
    assert recognize_selected_hero(image)


@pytest.mark.parametrize("bounds", [
    (1535, 965, 1560, 1000),  # 按钮文字被遮挡
    (78, 60, 120, 106),       # 页面返回键被遮挡
])
def test_resume_adventure_rejects_obscured_controls(bounds):
    image = _image("screens/f1-adventure-resume-20261114.png")
    x1, y1, x2, y2 = bounds
    image[y1:y2, x1:x2] = 0
    assert find_resume_adventure_button(image) is None


def test_resume_adventure_rejects_dimmed_page():
    image = _image("screens/f1-adventure-resume-20261114.png")
    image = (image * 0.5).astype(np.uint8)
    assert find_resume_adventure_button(image) is None
    assert not recognize_selected_hero(image)


def test_resume_adventure_does_not_recognize_home_or_map():
    assert find_resume_adventure_button(_image("screens/1080p_home_adventure_entry.png")) is None
    assert find_resume_adventure_button(_image("mapnav/1080p_map.png")) is None
