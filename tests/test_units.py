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

from lorwright.core.models import Rect
from lorwright.core.perceive.units import find_unit_badges, to_units

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


def test_unit_with_connected_gold_frame_is_found() -> None:
    image = cv2.imread(str(SCREENS / "f1-karma-eight-mana-20261114.png"))
    assert image is not None
    units = to_units(find_unit_badges(image, MY_BOARD), image=image)
    assert len(units) == 2
    assert any(1000 <= unit.rect.center[0] <= 1065 and unit.attack == 6 for unit in units)


@pytest.mark.parametrize("shade", (0, 80, 160))
@pytest.mark.parametrize("bounds", ((970, 850, 1045, 905), (1045, 850, 1120, 905)))
def test_connected_gold_frame_without_visible_badges_is_not_a_unit(shade, bounds) -> None:
    image = cv2.imread(str(SCREENS / "f1-karma-eight-mana-20261114.png"))
    assert image is not None
    x1, y1, x2, y2 = bounds
    image[y1:y2, x1:x2] = shade
    units = to_units(find_unit_badges(image, MY_BOARD))
    assert all(not 1000 <= unit.rect.center[0] <= 1065 for unit in units)


@pytest.mark.parametrize("name,attack", [
    ("f1-jinx-short-gold-spill-20261116.png", 6),
    ("f1-jinx-buffed-badges-20261116.png", 9),
])
def test_gold_spill_below_attack_badge_keeps_the_visible_unit(name, attack):
    image = cv2.imread(str(SCREENS / name))
    assert image is not None
    units = to_units(find_unit_badges(image, Rect(0, 0, 280, 260)), image=image)
    assert len(units) == 1
    assert units[0].attack == attack
    assert 150 <= units[0].rect.center[0] <= 175
    assert 105 <= units[0].rect.center[1] <= 125


@pytest.mark.parametrize("name", ["f1-paired-unit-frames-20261116.png",
                                  "f1-paired-unit-frames-timeout-20261116.png"])
@pytest.mark.parametrize("offset", [(0, 0), (130, 65)])
def test_paired_badges_survive_connected_card_frames(name, offset):
    crop = cv2.imread(str(SCREENS / name))
    assert crop is not None
    dx, dy = offset
    image = np.zeros((400, 600, 3), np.uint8)
    image[dy:dy + 260, dx:dx + 370] = crop
    units = to_units(find_unit_badges(image, Rect(0, 0, 600, 400)), image=image)
    assert len(units) == 2
    assert [unit.attack for unit in units] == [7, 7]
    assert [unit.health for unit in units] == [8, 5]
    assert 80 <= units[0].rect.center[0] - dx <= 110
    assert 250 <= units[1].rect.center[0] - dx <= 290
    assert all(100 <= unit.rect.center[1] - dy <= 125 for unit in units)


@pytest.mark.parametrize("badge", ["attack", "health"])
@pytest.mark.parametrize("shade", [0, 80, 160])
def test_connected_card_frame_requires_visible_badge_pair(badge, shade):
    image = cv2.imread(str(SCREENS / "f1-paired-unit-frames-timeout-20261116.png"))
    assert image is not None
    left, right = (20, 90) if badge == "attack" else (90, 165)
    image[25:90, left:right] = shade
    units = to_units(find_unit_badges(image, Rect(0, 0, 370, 260)), image=image)
    assert len(units) == 1
    assert units[0].rect.center[0] > 250


@pytest.mark.parametrize("badge", ["attack", "health"])
def test_connected_card_frame_requires_readable_badge_pair(badge):
    image = cv2.imread(str(SCREENS / "f1-paired-unit-frames-timeout-20261116.png"))
    assert image is not None
    left, right = (20, 90) if badge == "attack" else (90, 165)
    patch = image[25:90, left:right]
    blue, green, red = (patch[:, :, i] for i in range(3))
    digits = (green >= 180) & (red <= 120) & (blue <= 120)
    patch[digits] = (20, 20, 20)
    units = to_units(find_unit_badges(image, Rect(0, 0, 370, 260)), image=image)
    assert len(units) == 1
    assert units[0].rect.center[0] > 250


@pytest.mark.parametrize("name", ["f1-jinx-short-gold-spill-20261116.png",
                                  "f1-jinx-buffed-badges-20261116.png"])
@pytest.mark.parametrize("badge", ["attack", "health"])
@pytest.mark.parametrize("shade", [0, 80, 160])
def test_short_gold_spill_requires_both_visible_badges(name, badge, shade):
    image = cv2.imread(str(SCREENS / name))
    assert image is not None
    left, right = (80, 145) if badge == "attack" else (145, 215)
    image[25:100, left:right] = shade
    assert find_unit_badges(image, Rect(0, 0, 280, 260)) == []


@pytest.mark.parametrize("badge", ["attack", "health"])
def test_partial_badge_pair_requires_both_readable_numbers(badge):
    image = cv2.imread(str(SCREENS / "f1-jinx-buffed-badges-20261116.png"))
    assert image is not None
    left, right = (80, 145) if badge == "attack" else (145, 215)
    patch = image[25:100, left:right]
    blue, green, red = (patch[:, :, i].astype(np.int16) for i in range(3))
    digits = (green >= 180) & (red <= 120) & (blue <= 120)
    patch[digits] = (20, 20, 20)
    assert find_unit_badges(image, Rect(0, 0, 280, 260)) == []


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


def test_reads_white_and_green_health_values() -> None:
    img = cv2.imread(str(SCREENS / "1080p_units_idle.png"))
    units = to_units(find_unit_badges(img, MY_BOARD), image=img)
    assert [u.health for u in units] == [3, 6]


@pytest.mark.parametrize("shade", [0, 80, 160])
def test_covered_health_stays_unknown(shade):
    img = cv2.imread(str(SCREENS / "1080p_units_idle.png"))
    img[850:910, 870:945] = shade
    units = to_units(find_unit_badges(img, MY_BOARD), image=img)
    assert [unit.health for unit in units] == [-1, 6]


@pytest.mark.parametrize("offset", [(0, 0), (130, 65)])
def test_badge_glow_does_not_mix_with_green_health_digit(offset):
    crop = cv2.imread(str(SCREENS.parent / "jinx" / "board-summoned-badge-glow-20261117.png"))
    dx, dy = offset
    image = np.zeros((400, 600, 3), np.uint8)
    image[dy:dy + 210, dx:dx + 390] = crop
    units = to_units(find_unit_badges(image, Rect(0, 0, 600, 400)), image=image)
    assert [unit.attack for unit in units] == [1, 6]
    from lorwright.core.perceive.unit_stats import UnitStatsReader

    # 定位入口仍须核验成对数字；to_units 的独立生命框定位可能继续弃权。
    assert UnitStatsReader().read_badge(
        image, Rect(dx + 295, dy + 23, 56, 48), health=True,
    ) == 7


@pytest.mark.parametrize("colors,expected", [("white", 1), ("green", 7), ("both", None)])
def test_stat_colors_must_agree_when_independently_readable(colors, expected):
    from lorwright.core.perceive.unit_stats import UnitStatsReader

    source = cv2.imread(str(SCREENS.parent / "jinx" / "board-summoned-badge-glow-20261117.png"))
    white = source[28:66, 61:107].min(axis=2) >= 170
    green_patch = source[28:66, 300:346]
    blue, green, red = (green_patch[:, :, i] for i in range(3))
    buffed = (green >= 180) & (red <= 120) & (blue <= 120)
    image = np.zeros((48, 110, 3), np.uint8)
    if colors in {"white", "both"}:
        image[5:43, 5:51][white] = (255, 255, 255)
    if colors in {"green", "both"}:
        image[5:43, 57:103][buffed] = (0, 255, 0)
    assert UnitStatsReader().read_badge(image, Rect(0, 0, 110, 48)) == expected


def test_attack_token_detected() -> None:
    """有令牌：按钮左侧橙色箭头，实测最大连通域 8446px。"""
    from lorwright.core.perceive.attack_token import has_attack_token

    img = cv2.imread(str(SCREENS / "1080p_attack_token.png"))
    assert has_attack_token(img, ATTACK_TOKEN_REGION)


def test_no_attack_token() -> None:
    """无令牌：同一区域只有 30px 的宝石边缘。"""
    from lorwright.core.perceive.attack_token import has_attack_token

    img = cv2.imread(str(SCREENS / "1080p_no_attack_token.png"))
    assert not has_attack_token(img, ATTACK_TOKEN_REGION)
