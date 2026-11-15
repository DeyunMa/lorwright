"""实机能力三选一：可识别的候选、品质及未知时的弃权。"""

from pathlib import Path

import cv2

from lorwright.core.champions.jinx import POWER_PREFERENCES
from lorwright.core.decide.rewards import pick_reward
from lorwright.core.perceive.reward_screen import (
    power_choose_enabled,
    power_selection,
    power_unselected,
    recognize_powers,
)


def test_recognizes_real_power_choices():
    path = Path(__file__).parent / "fixtures/mapnav/1080p_ability_select.png"
    image = cv2.imread(str(path))
    result = recognize_powers(image)
    assert result is not None
    assert [(c.name, c.quality) for c in result] == [
        ("法術燃燒", "rare"),
        ("諾克薩斯威能", "rare"),
        ("準備過度", "common"),
    ]


def test_recognizes_f1_power_choices_and_applies_jinx_default():
    image = cv2.imread(str(Path(__file__).parent / "fixtures/power_reward/f1-power-20261115.png"))
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
    image = cv2.imread(str(Path(__file__).parent / "fixtures/power_reward/f1-power-selected-20261115.png"))
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


def test_missing_candidate_or_quality_abstains():
    path = Path(__file__).parent / "fixtures/mapnav/1080p_ability_select.png"
    image = cv2.imread(str(path))
    for region in ((540, 583, 815, 1105), (584, 610, 815, 1105)):
        modified = image.copy()
        y1, y2, x1, x2 = region
        modified[y1:y2, x1:x2] = 0
        assert recognize_powers(modified) is None
