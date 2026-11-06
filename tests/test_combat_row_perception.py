"""用真实徽章裁片构造换行场景，验证配置→识别→后验的连接。

图片位置变换是合成案例，不代表一次实际手势成功。
"""

from dataclasses import replace

import cv2
import numpy as np
import pytest

from lorwright.config import load_settings
from lorwright.loop.outcome import ActionOutcome, OutcomeStatus
from lorwright.models import Action, ActionType, UIState
from lorwright.perceive.hand import find_badges, find_badges_expanded
from lorwright.perceive.state import StateParser
from lorwright.perceive.units import find_unit_badges


class UI:
    def __init__(self, kind=UIState.MY_TURN_IDLE):
        self.kind = kind

    def detect(self, image):
        return self.kind


def frame_with_badge(y):
    layout = load_settings().layout.to_layout()
    source = cv2.imread("tests/fixtures/screens/1080p_units_idle.png")
    badge = find_unit_badges(source, layout.my_board)[0].rect
    patch = source[badge.y:badge.y + badge.h, badge.x:badge.x + badge.w]
    frame = np.zeros_like(source)
    frame[y:y + badge.h, 700:700 + badge.w] = patch
    return frame


def test_declared_unit_remains_visible_to_parser_and_outcome():
    layout = load_settings().layout.to_layout()
    parser = StateParser(layout, UI())
    before = parser.parse(frame_with_badge(850))
    after = parser.parse(frame_with_badge(650))
    assert len(before.my_units) == len(after.my_units) == 1
    assert before.my_units[0].rect.center[1] - after.my_units[0].rect.center[1] == 200
    outcome = ActionOutcome(Action(ActionType.ATTACK, raw={"attackers": [0]}), before, 8)
    assert outcome.observe(after, 1).status is OutcomeStatus.SUCCEEDED
    # 去掉声明行配置时重现原先的漏识别，证明测试覆盖到了实际区域连接。
    old_parser = StateParser(replace(layout, my_combat=None), UI())
    assert old_parser.parse(frame_with_badge(650)).my_units == []


def test_target_preview_area_is_not_scanned_as_combat_units():
    parser = StateParser(load_settings().layout.to_layout(), UI(UIState.TARGETING))
    assert parser.parse(frame_with_badge(650)).my_units == []


@pytest.mark.parametrize("find", [find_badges, find_badges_expanded])
def test_blank_region_does_not_create_phantom_hand_badges(find):
    layout = load_settings().layout.to_layout()
    assert find(np.zeros((1080, 1920, 3), np.uint8), layout.hand_expanded) == []
    assert find(frame_with_badge(650), layout.hand_expanded) == []
