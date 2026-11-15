"""治疗师页面的实拍识别与遮挡保护。"""

from pathlib import Path

import cv2
import numpy as np
import pytest

from lorwright.core.perceive.healer import healer_heal_button, is_healer_screen

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def healer_image() -> np.ndarray:
    image = cv2.imread(str(FIXTURES / "healer" / "f1-full-health.png"))
    assert image is not None
    return image


def test_healer_free_heal_is_recognized(healer_image):
    assert is_healer_screen(healer_image)
    button = healer_heal_button(healer_image)
    assert button is not None
    assert button.center == (1441, 1004)


@pytest.mark.parametrize("bounds", [
    (563, 357, 736, 416),  # 页面标题
    (932, 754, 979, 814),  # 免费治疗的选中标记
    (1204, 35, 1492, 75),  # 免费治疗说明
    (1397, 981, 1486, 1027),  # 治疗按钮文字
])
def test_obscured_healer_controls_do_not_authorize_click(healer_image, bounds):
    x1, y1, x2, y2 = bounds
    healer_image[y1:y2, x1:x2] = 0
    assert healer_heal_button(healer_image) is None


def test_darkened_healer_screen_does_not_authorize_click(healer_image):
    darkened = cv2.convertScaleAbs(healer_image, alpha=0.5)
    assert healer_heal_button(darkened) is None


@pytest.mark.parametrize("relative", [
    "mapnav/1080p_jinx_map.png",
    "screens/1080p_jinx_support_selection.jpg",
    "card_rewards/before.png",
])
def test_other_screens_are_not_healer(relative):
    image = cv2.imread(str(FIXTURES / relative))
    assert image is not None
    assert not is_healer_screen(image)
    assert healer_heal_button(image) is None
