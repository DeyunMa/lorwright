"""mapnav 在真实地图截图上的回归验证。

Fixtures 是 2026-11-05/06 月度挑战的实机截图（960x540，与
AdventureLoop 运行时喂给 mapnav 的尺寸一致）。

标注依据（2026-11-06 搭基准时确认的语义链）：
- 英雄头像所在节点 = 当前节点（glow 指标跟随头像）；
- 节点中心的青绿徽章 = 已完成（用连续帧的移动链验证：
  m3-g7 英雄在 (406,237) → m3-g6 英雄在 (535,174)，(406,237)
  在 g6 里带徽章）；
- 亮白蓝发光线 = 当前可走（节点事件完成后才点亮；
  m3-g6 商店事件未完成时全图无可走线，shopD 完成后 (240,373) 亮起）；
- 金色菱形 = 能力/辅助节点类型图标，不是位置标记。
"""

from pathlib import Path

import cv2
import pytest

from lorwright.perceive.mapnav import (
    _hero_by_gold,
    blue_glow_mask,
    detect_nodes,
    glow_mask,
    has_checkmark,
    hero_node,
    next_node,
)

FIXTURES = Path(__file__).parent / "fixtures" / "mapnav"

#: (图, 当前节点, 期望 next 或 None)。None = 事件未完成/面板态/无图。
CASES = {
    "m3-g7.jpg": ((406, 237), (538, 177)),
    "m3-g6.jpg": ((535, 174), None),
    "m3-re.jpg": ((535, 174), None),
    "m3-shopD.jpg": ((508, 174), (240, 373)),
    "m3-zoom.jpg": ((535, 174), None),
    "m3-green.jpg": ((535, 174), None),
    "m3-node3.jpg": ((535, 174), None),
    "n-green.jpg": ((546, 167), (256, 381)),
    "m3-heroicon.jpg": ((616, 174), None),
    "m3-node1.jpg": ((479, 331), None),
    "m3-node2.jpg": ((479, 331), None),
    "monthly2-map.jpg": ((478, 226), None),
    "monthly2-event-node.jpg": ((545, 204), (647, 275)),
    "re2-map2.jpg": ((513, 438), (390, 459)),
}

#: 面板打开/非地图画面：不导航、不崩溃。
GATED_CASES = ["poppy-node.jpg", "item-chest-travel.jpg", "monthly2-boss-node.jpg", "re2-map.jpg", "m3-map.jpg", "r2-map.jpg"]


def load(name):
    image = cv2.imread(str(FIXTURES / name))
    assert image is not None, f"missing fixture {name}"
    return image


def test_hero_node_detected_legacy_region():
    # 旧断言保留：三张图英雄节点都在上半屏中部区域
    for name in ["m3-re", "m3-g7", "m3-shopD"]:
        image = load(f"{name}.jpg")
        mask = blue_glow_mask(image)
        nodes = detect_nodes(image)
        assert nodes, name
        hero = hero_node(nodes, mask)
        assert hero is not None, name
        assert 400 < hero.x < 700, (name, hero)
        assert 100 < hero.y < 260, (name, hero)


@pytest.mark.parametrize("name", sorted(CASES))
def test_hero_and_next(name):
    want_hero, want_next = CASES[name]
    image = load(name)
    nxt = next_node(image)
    nodes = detect_nodes(image)
    hero = hero_node(nodes, glow_mask(image)) or _hero_by_gold(image, nodes)
    assert hero is not None, name
    assert (hero.x, hero.y) == want_hero, (name, hero, want_hero)
    if want_next is None:
        assert nxt is None, (name, nxt)
    else:
        assert nxt is not None, name
        assert (nxt.x, nxt.y) == want_next, (name, nxt, want_next)


@pytest.mark.parametrize("name", GATED_CASES)
def test_gated_cases_never_navigate(name):
    image = load(name)
    assert next_node(image) is None, name


def test_checkmark_follows_movement_chain():
    # g7 里英雄在 (406,237)（事件已完成，带徽章）；g6 里英雄已走到
    # (535,174)，(406,237) 徽章保留，(535,174) 尚未完成
    g7 = load("m3-g7.jpg")
    g6 = load("m3-g6.jpg")
    g7_nodes = {(n.x, n.y): n for n in detect_nodes(g7)}
    g6_nodes = {(n.x, n.y): n for n in detect_nodes(g6)}
    assert has_checkmark(g7, g7_nodes[(406, 237)])
    assert not has_checkmark(g7, g7_nodes[(538, 177)])
    assert has_checkmark(g6, g6_nodes[(399, 228)])
    assert not has_checkmark(g6, g6_nodes[(535, 174)])
    # shopD：离开商店节点后，来路 (372,227) 带徽章，前方 (240,373) 没有
    shop = load("m3-shopD.jpg")
    shop_nodes = {(n.x, n.y): n for n in detect_nodes(shop)}
    assert has_checkmark(shop, shop_nodes[(372, 227)])
    assert not has_checkmark(shop, shop_nodes[(240, 373)])
