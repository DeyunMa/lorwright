"""实机能力三选一：可识别的候选、品质及未知时的弃权。"""


import cv2
import pytest

from lorwright.core.champions.jinx import POWER_PREFERENCES
from lorwright.core.decide.rewards import pick_reward
from lorwright.core.perceive.reward_screen import (
    power_choose_enabled,
    power_selection,
    power_unselected,
    recognize_powers,
)
from tools.test_data import fixtures_root


def test_recognizes_weekly_diamond_power_screen():
    from lorwright.core.perceive.reward_screen import is_power_screen

    image = cv2.imread(str(fixtures_root() / "power_reward/f1-weekly-diamond-20261116.png"))
    assert is_power_screen(image)
    candidates = recognize_powers(image)
    assert candidates is not None
    assert [candidate.quality for candidate in candidates] == ["common", "rare", "common"]
    assert pick_reward(candidates, POWER_PREFERENCES).candidate is candidates[1]
    assert power_unselected(image)


@pytest.mark.parametrize("damage", ["missing", "dimmed", "wrong_color"])
def test_weekly_power_title_requires_visible_gold_text(damage):
    from lorwright.core.perceive.reward_screen import is_power_screen

    image = cv2.imread(str(fixtures_root() / "power_reward/f1-weekly-diamond-20261116.png"))
    if damage == "missing":
        image[25:102, 880:1036] = 0
    elif damage == "dimmed":
        image[25:102, 880:1036] //= 3
    else:
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        hsv[25:102, 880:1036, 0] = 100
        image = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    assert not is_power_screen(image)
    assert recognize_powers(image) is None


def test_recognizes_real_power_choices():
    path = fixtures_root() / "mapnav/1080p_ability_select.png"
    image = cv2.imread(str(path))
    result = recognize_powers(image)
    assert result is not None
    assert [(c.name, c.quality) for c in result] == [
        ("法術燃燒", "rare"),
        ("諾克薩斯威能", "rare"),
        ("準備過度", "common"),
    ]


def test_recognizes_f1_power_choices_and_applies_jinx_default():
    image = cv2.imread(str(fixtures_root() / "power_reward/f1-power-20261115.png"))
    result = recognize_powers(image)
    assert result is not None
    assert [(c.name, c.quality) for c in result] == [
        ("因時制宜", "common"), ("物競人擇", "common"), ("不能停，不要停", "epic"),
    ]
    assert pick_reward(result, POWER_PREFERENCES).candidate.name == "不能停，不要停"
    assert power_unselected(image)
    highlighted = image.copy()
    highlighted[270:775, 1158:1161] = 255
    assert not power_unselected(highlighted)
    obscured = image.copy()
    obscured[270:775, 815:818] = 0
    assert not power_unselected(obscured)
    image[540:583, 815:1105] = 0
    assert recognize_powers(image) is None


def test_selected_power_and_button_are_unambiguous():
    image = cv2.imread(str(fixtures_root() / "power_reward/f1-power-selected-20261115.png"))
    assert power_selection(image) == 2
    assert power_choose_enabled(image)
    assert recognize_powers(image) is not None
    obscured = image.copy()
    obscured[290:760, 1165:1168] = 0
    assert power_selection(obscured) is None
    ambiguous = image.copy()
    ambiguous[290:760, 479:482] = 255
    assert power_selection(ambiguous) is None
    disabled = image.copy()
    disabled[960:1045, 800:1120] = 0
    assert not power_choose_enabled(disabled)


def test_unknown_power_names_use_visible_quality():
    image = cv2.imread(str(fixtures_root() / "power_reward/f1-power-legendary-20261116.png"))
    candidates = recognize_powers(image)
    assert candidates is not None
    assert [(c.name, c.quality) for c in candidates] == [
        ("", "rare"), ("", "rare"), ("", "legendary"),
    ]
    assert pick_reward(candidates, POWER_PREFERENCES).candidate is candidates[2]
    assert power_unselected(image)


@pytest.mark.parametrize("target", [0, 1, 2])
def test_unknown_highest_quality_is_selected_in_any_slot(target):
    image = cv2.imread(str(fixtures_root() / "power_reward/f1-power-legendary-20261116.png"))
    slots = (472, 815, 1158)
    rare = image[584:610, 472:762].copy()
    legendary = image[584:610, 1158:1448].copy()
    for index, x in enumerate(slots):
        image[584:610, x:x + 290] = legendary if index == target else rare
    candidates = recognize_powers(image)
    assert candidates is not None
    assert pick_reward(candidates).candidate is candidates[target]


@pytest.mark.parametrize("change", ["dimmed", "unknown_quality", "wrong_color"])
def test_uncertain_power_quality_does_not_authorize_selection(change):
    image = cv2.imread(str(fixtures_root() / "power_reward/f1-power-legendary-20261116.png"))
    if change == "dimmed":
        image = (image * 0.3).astype("uint8")
    elif change == "unknown_quality":
        image[584:610, 1158:1448] = 0
    else:
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        hsv[584:610, 1158:1448, 0] = 70
        image = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    assert recognize_powers(image) is None


def test_missing_candidate_or_quality_abstains():
    path = fixtures_root() / "mapnav/1080p_ability_select.png"
    image = cv2.imread(str(path))
    for region in ((540, 583, 815, 1105), (584, 610, 815, 1105)):
        modified = image.copy()
        y1, y2, x1, x2 = region
        modified[y1:y2, x1:x2] = 0
        assert recognize_powers(modified) is None
