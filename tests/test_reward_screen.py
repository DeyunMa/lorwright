"""实机能力三选一：可识别的候选、品质及未知时的弃权。"""

from pathlib import Path

import cv2

from lorwright.perceive.reward_screen import recognize_powers


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


def test_missing_candidate_or_quality_abstains():
    path = Path(__file__).parent / "fixtures/mapnav/1080p_ability_select.png"
    image = cv2.imread(str(path))
    for region in ((540, 583, 815, 1105), (584, 610, 815, 1105)):
        modified = image.copy()
        y1, y2, x1, x2 = region
        modified[y1:y2, x1:x2] = 0
        assert recognize_powers(modified) is None
