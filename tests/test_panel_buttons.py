"""节点面板金色按钮检测回归（2026-11-07 f1 1080p 实机截图）。"""

from pathlib import Path

import cv2
import pytest

from lorwright.perceive.panels import action_button

FIXTURES = Path(__file__).parent / "fixtures" / "mapnav"


def _img(name: str):
    img = cv2.imread(str(FIXTURES / name))
    assert img is not None, name
    return img


@pytest.mark.parametrize(
    ("name", "center"),
    [
        ("1080p_node_panel.png", (817, 485)),
        ("1080p_battle_detail.png", (1581, 1010)),
    ],
)
def test_detects_gold_action_button(name: str, center: tuple[int, int]) -> None:
    button = action_button(_img(name))
    assert button is not None
    assert abs(button.center[0] - center[0]) <= 3
    assert abs(button.center[1] - center[1]) <= 3


@pytest.mark.parametrize(
    "name",
    [
        "1080p_zoommax.png",  # 纯地图
        "1080p_ability_select.png",  # 能力三选一
        "1080p_panel.png",  # 辅助英雄信息面板
        "1080p_map.png",  # 另一张地图
    ],
)
def test_no_false_positive(name: str) -> None:
    assert action_button(_img(name)) is None
