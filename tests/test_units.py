"""场上单位识别测试。

`1080p_my_units.png` 是实机截图：我方 3 个单位（1|1 / 7|7 / 5|5），
敌方 5 个（8|9 / 8|2 / 5|6 / 5|3 / 3|2）。
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from lorwright.models import Rect
from lorwright.perceive.units import find_unit_badges, to_units

SCREENS = Path(__file__).parent / "fixtures" / "screens"
MY_BOARD = Rect(200, 820, 1500, 260)
ENEMY_BOARD = Rect(200, 100, 1500, 200)
ATTACK_TOKEN_REGION = Rect(1640, 700, 140, 130)


@pytest.fixture(scope="module")
def image() -> np.ndarray:
    img = cv2.imread(str(SCREENS / "1080p_my_units.png"))
    assert img is not None, "缺少 fixture 1080p_my_units.png"
    return img


def test_finds_three_my_units(image: np.ndarray) -> None:
    badges = find_unit_badges(image, MY_BOARD)
    assert len(badges) == 3
    assert all(b.score >= 0.98 for b in badges)


def test_finds_five_enemy_units(image: np.ndarray) -> None:
    assert len(find_unit_badges(image, ENEMY_BOARD, enemy=True)) == 5


def test_my_template_does_not_match_enemy_board(image: np.ndarray) -> None:
    """跨区互匹必须为 0，否则会把我方单位算成敌方（反之亦然）。"""
    assert find_unit_badges(image, ENEMY_BOARD) == []


def test_drag_point_lands_on_card_body(image: np.ndarray) -> None:
    """拖拽点要落在卡身中部——徽章本身拖不动（实测）。"""
    units = to_units(find_unit_badges(image, MY_BOARD))
    # 实机成功拖拽的坐标是 (970, 930)
    assert any(
        abs(u.rect.center[0] - 970) <= 15 and abs(u.rect.center[1] - 930) <= 15 for u in units
    )


def test_empty_board_yields_no_units() -> None:
    blank = np.zeros((1080, 1920, 3), np.uint8)
    assert find_unit_badges(blank, MY_BOARD) == []
    assert find_unit_badges(blank, ENEMY_BOARD, enemy=True) == []


def test_attack_token_detected() -> None:
    """有令牌：按钮左侧橙色箭头，实测最大连通域 8446px。"""
    from lorwright.perceive.attack_token import has_attack_token

    img = cv2.imread(str(SCREENS / "1080p_attack_token.png"))
    assert has_attack_token(img, ATTACK_TOKEN_REGION)


def test_no_attack_token() -> None:
    """无令牌：同一区域只有 30px 的宝石边缘。"""
    from lorwright.perceive.attack_token import has_attack_token

    img = cv2.imread(str(SCREENS / "1080p_no_attack_token.png"))
    assert not has_attack_token(img, ATTACK_TOKEN_REGION)
