"""地图控件在真实画面及遮挡时的识别回归。"""

from pathlib import Path

import cv2
import numpy as np
import pytest

from lorwright.perceive.adventure_scene import is_map

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
