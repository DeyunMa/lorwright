"""场上单位识别测试。

识别靠攻击力方块的橙色，不靠模板匹配 —— 见 `perceive/units.py` 顶部说明。

`1080p_units_idle.png` 是**待命状态**（单位卡带蓝色发光描边）：我方 2 个、敌方 2 个。
这正是旧模板方案认不出的场景：同一张卡在「可攻击」和「待命」两种状态下样式不同，
`my_units` 会在回合中途突然变 0，策略就以为没兵可打，整局不攻击。

`1080p_units_combat.png` 是**攻击声明后**：我方 6 个、敌方 5 个。
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


def test_finds_my_units(image: np.ndarray) -> None:
    """我方 3 个里能认出 2 个：最左边那个被紫色选中光效盖住橙色，认不出。

    宁可少认一个也不要认错 —— 少认只是少打一个单位，认错会拖错卡。
    """
    badges = find_unit_badges(image, MY_BOARD)
    assert len(badges) == 2


def test_finds_enemy_units(image: np.ndarray) -> None:
    assert len(find_unit_badges(image, ENEMY_BOARD, enemy=True)) == 5


def test_idle_state_units_are_found() -> None:
    """待命状态（蓝色发光描边）也要认得出 —— 这是整局不攻击的根因。"""
    img = cv2.imread(str(SCREENS / "1080p_units_idle.png"))
    assert img is not None, "缺少 fixture 1080p_units_idle.png"
    assert len(find_unit_badges(img, MY_BOARD)) == 2
    assert len(find_unit_badges(img, ENEMY_BOARD, enemy=True)) == 2


def test_combat_state_units_are_found() -> None:
    """攻击声明后：我方 6 个、敌方 6 个，含粉色数值框的隐秘单位。"""
    img = cv2.imread(str(SCREENS / "1080p_units_combat.png"))
    assert img is not None, "缺少 fixture 1080p_units_combat.png"
    assert len(find_unit_badges(img, MY_BOARD)) == 6
    assert len(find_unit_badges(img, ENEMY_BOARD, enemy=True)) == 6


def test_buff_icon_on_same_card_is_suppressed() -> None:
    """同一张卡上的第二个橙色元素（buff 图标）不能被算成第二个单位。

    `1080p_units_combat.png` 里真实单位间距 163px，buff 图标间距 68px，
    间距抑制半径 100 正好切开。不抑制会多算出 3 个不存在的单位。
    """
    img = cv2.imread(str(SCREENS / "1080p_units_combat.png"))
    xs = [b.center[0] for b in find_unit_badges(img, MY_BOARD)]
    assert all(b - a >= 100 for a, b in zip(xs, xs[1:], strict=False))


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


def test_reads_attack_values_from_idle_units() -> None:
    img = cv2.imread(str(SCREENS / "1080p_units_idle.png"))
    mine = to_units(find_unit_badges(img, MY_BOARD), image=img)
    theirs = to_units(find_unit_badges(img, ENEMY_BOARD, enemy=True), enemy=True, image=img)
    assert [u.attack for u in mine] == [4, 6]
    assert [u.attack for u in theirs] == [8, 2]


def test_reads_attack_values_from_combat_units() -> None:
    img = cv2.imread(str(SCREENS / "1080p_units_combat.png"))
    mine = to_units(find_unit_badges(img, MY_BOARD), image=img)
    theirs = to_units(find_unit_badges(img, ENEMY_BOARD, enemy=True), enemy=True, image=img)
    assert [u.attack for u in mine] == [1, 7, 7, 1, 1, 1]
    assert [u.attack for u in theirs] == [12, 5, 3, -1, 3, 12]
    assert [u.keywords for u in theirs] == [
        frozenset(), frozenset(), frozenset(), frozenset({"Elusive"}),
        frozenset(), frozenset(),
    ]


def test_reads_visible_health_but_keeps_obscured_health_unknown() -> None:
    img = cv2.imread(str(SCREENS / "1080p_units_idle.png"))
    units = to_units(find_unit_badges(img, MY_BOARD), image=img)
    # 第一个单位的生命徽章被红色高光盖住，不能猜；第二个清晰可读。
    assert [u.health for u in units] == [-1, 6]


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
