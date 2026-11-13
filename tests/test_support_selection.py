"""辅助英雄真实画面与费用排序；不依赖游戏设备。"""

from pathlib import Path

import cv2
import numpy as np
import pytest

from lorwright.decide.support import SupportGroup, pick_support_group
from lorwright.perceive.digits import normalize_glyph
from lorwright.perceive.normalize import Normalizer
from lorwright.perceive.support_screen import (
    is_support_screen,
    recognize_support_choices,
    same_support_choices,
    support_confirm_button,
    support_selection,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _image(path: str) -> np.ndarray:
    image = cv2.imread(str(FIXTURES / path))
    assert image is not None
    return Normalizer((1920, 1080)).fit(image)[0]


@pytest.mark.parametrize(("name", "groups", "chosen"), [
    ("screens/1080p_jinx_support_selection.jpg", [
        SupportGroup(2, (2, 6)), SupportGroup(6, (2, 3)), SupportGroup(5, (None, 3)),
    ], 0),
    ("support/m3-travel.jpg", [
        SupportGroup(5, (2, 2)), SupportGroup(5, (3, 3)), SupportGroup(4, (1, 6)),
    ], 2),
    ("support/support-options.jpg", [
        SupportGroup(4, (1, 6)), SupportGroup(5, (3, 5)), SupportGroup(1, (2, 3)),
    ], 2),
    ("support/monthly2-support-options.jpg", [
        SupportGroup(4, (1, 2)), SupportGroup(4, (3, 4)), SupportGroup(4, (2, 2)),
    ], 0),
])
def test_real_support_screens_recognize_hero_cost_and_apply_rule(name, groups, chosen):
    image = _image(name)
    assert is_support_screen(image)
    assert support_selection(image) == -1
    choices = recognize_support_choices(image)
    assert choices is not None
    assert [choice.group for choice in choices] == groups
    assert pick_support_group([choice.group for choice in choices]) == chosen
    assert support_confirm_button(image) is None


def test_hero_cost_precedes_other_cards_and_ties_compare_averages():
    assert pick_support_group([
        SupportGroup(2, (6, 6)), SupportGroup(3, (1, 1)), SupportGroup(5, (0, 0)),
    ]) == 0
    assert pick_support_group([
        SupportGroup(4, (4, 4)), SupportGroup(4, (1, 2)), SupportGroup(4, (2, 2)),
    ]) == 1
    assert pick_support_group([SupportGroup(4, (1, 3)), SupportGroup(4, (2, 2))]) == 0


def test_only_unknown_costs_needed_for_the_decision_prevent_a_choice():
    assert pick_support_group([SupportGroup(2, (None, 5)), SupportGroup(3, (1, 1))]) == 0
    assert pick_support_group([SupportGroup(None, (1, 1)), SupportGroup(3, (1, 1))]) is None
    assert pick_support_group([SupportGroup(2, (None, 5)), SupportGroup(2, (1, 1))]) is None
    assert pick_support_group([SupportGroup(2, (1, 1)), SupportGroup(3, (None, None))]) == 0


def test_variable_zero_cost_cannot_break_a_hero_cost_tie():
    image = _image("screens/1080p_jinx_support_selection.jpg")
    five = image[584:614, 1264:1293].copy()
    image[441:471, 328:357] = five
    image[584:614, 798:827] = five
    choices = recognize_support_choices(image)
    assert choices is not None
    assert [choice.group.hero_cost for choice in choices] == [5, 5, 5]
    assert choices[2].group.card_costs == (None, 3)
    assert pick_support_group([choice.group for choice in choices]) is None


def test_real_selected_group_and_confirm_button():
    before = _image("support/m3-travel.jpg")
    selected = _image("support/m3-supp1.jpg")
    assert support_selection(selected) == 1
    assert support_confirm_button(selected).center == (960, 1003)
    assert same_support_choices(before, selected, 1)
    assert recognize_support_choices(selected) is None


def test_uncertain_or_changed_selection_is_not_confirmed():
    before = _image("support/m3-travel.jpg")
    selected = _image("support/m3-supp1.jpg")
    # 选择按钮仍然点亮，但无法确认是哪一组时不能点击确认。
    selected[400:640, 752:1170] = 0
    assert support_selection(selected) is None
    assert support_confirm_button(selected) is None
    selected = _image("support/m3-supp1.jpg")
    selected[432:482, 378:568] = 0
    assert not same_support_choices(before, selected, 1)


def test_selected_content_and_other_groups_costs_must_remain_visible_and_unchanged():
    before = _image("support/m3-travel.jpg")
    selected = _image("support/m3-supp1.jpg")
    selected[428:466, 800:1100] = 0
    assert support_selection(selected) == 1
    assert support_confirm_button(selected) is not None
    assert not same_support_choices(before, selected, 1)

    selected = _image("support/m3-supp1.jpg")
    selected[584:614, 328:357] = before[441:471, 328:357]
    assert support_selection(selected) == 1
    assert not same_support_choices(before, selected, 1)

    selected = _image("support/m3-supp1.jpg")
    selected[592:620, 778:796] = selected[432:460, 778:796].copy()
    assert support_selection(selected) == 1
    assert not same_support_choices(before, selected, 1)


def test_missing_hero_or_obscured_screen_cannot_choose():
    image = _image("screens/1080p_jinx_support_selection.jpg")
    image[426:477, 308:321] = 0  # 遮住左组英雄标记
    assert recognize_support_choices(image) is None
    image = _image("screens/1080p_jinx_support_selection.jpg")
    image[441:471, 328:357] = 0  # 遮住左组英雄费用
    choices = recognize_support_choices(image)
    assert choices is not None
    assert pick_support_group([choice.group for choice in choices]) is None
    assert not is_support_screen(_image("screens/1080p_jinx_support_selection.jpg") // 2)


@pytest.mark.parametrize("digit", [7, 8, 9])
def test_unseen_rendered_digits_are_not_mistaken_for_known_hero_costs(digit):
    image = _image("screens/1080p_jinx_support_selection.jpg")
    x, y = 308, 422
    image[y + 17:y + 51, x + 16:x + 53] = (55, 30, 20)
    glyph = cv2.imread(f"assets/digits_unit/{digit}-24.png", cv2.IMREAD_GRAYSCALE)
    assert glyph is not None
    glyph = cv2.resize(normalize_glyph(glyph), (16, 24))
    patch = image[y + 20:y + 44, x + 23:x + 39]
    patch[glyph > 0.5] = 255
    choices = recognize_support_choices(image)
    assert choices is not None
    assert pick_support_group([choice.group for choice in choices]) is None


@pytest.mark.parametrize("second_height", [24, 18, 8])
def test_two_digit_hero_cost_is_not_truncated_to_a_single_digit(second_height):
    image = _image("screens/1080p_jinx_support_selection.jpg")
    x, y = 308, 422
    image[y + 17:y + 51, x + 16:x + 53] = (55, 30, 20)
    for name, dx, width, height in (
        ("1-m3-20.png", 17, 8, 24), ("0-jinx-20.png", 30, 15, second_height),
    ):
        digit = cv2.imread(f"assets/adventure/support_digits/{name}", cv2.IMREAD_GRAYSCALE)
        assert digit is not None
        digit = cv2.resize(digit, (width, height))
        patch = image[y + 20:y + 20 + height, x + dx:x + dx + width]
        patch[digit > 128] = 255
    choices = recognize_support_choices(image)
    assert choices is not None
    assert pick_support_group([choice.group for choice in choices]) is None


def test_other_screens_are_not_support_choices():
    for path in ("card_rewards/before.png", "support/m3-supp2.jpg", "screens/1080p_login_form.png"):
        assert not is_support_screen(_image(path))
