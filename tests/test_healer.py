"""治疗师页面的实拍识别与遮挡保护。"""


import cv2
import numpy as np
import pytest

from lorwright.core.perceive.healer import healer_heal_button, is_healer_screen
from tools.test_data import fixtures_root

FIXTURES = fixtures_root()


@pytest.fixture(params=[
    "healer/f1-full-health.png", "screens/f1-field-cook-20261116.png",
    "screens/f1-weekly-healer-20261116.png", "healer/f1-remaining-panel-20261118.png",
])
def healer_image(request) -> np.ndarray:
    image = cv2.imread(str(FIXTURES / request.param))
    assert image is not None
    if request.param == "healer/f1-remaining-panel-20261118.png":
        full = np.zeros((1080, 1920, 3), np.uint8)
        full[20:1045, 530:1510] = image
        image = full
    return image


def test_healer_free_heal_is_recognized(healer_image):
    assert is_healer_screen(healer_image)
    button = healer_heal_button(healer_image)
    assert button is not None
    assert button.center == (1441, 1004)


@pytest.mark.parametrize("bounds", [
    (550, 335, 805, 435),  # 治疗师或战地厨师标题
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


def test_solid_gold_cover_does_not_count_as_healer_title():
    image = cv2.imread(str(FIXTURES / "healer/f1-full-health.png"))
    assert image is not None and healer_heal_button(image) is not None
    image[335:435, 540:805] = (32, 146, 230)
    assert not is_healer_screen(image)
    assert healer_heal_button(image) is None


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
