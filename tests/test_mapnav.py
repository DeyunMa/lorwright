"""mapnav 1080p 回归：最大视角，英雄节点 C3，下一关 C4。"""

from pathlib import Path

import cv2
import numpy as np

from lorwright.champions.jinx.vision import recognize_hero
from lorwright.perceive.mapnav import (
    detect_ability_nodes,
    detect_nodes,
    empty_point,
    hero_node,
    next_node,
    next_node_by_path,
    panel_open,
)

FIXTURES = Path(__file__).parent / "fixtures" / "mapnav"


def _load(name: str) -> np.ndarray:
    image = cv2.imread(str(FIXTURES / name))
    assert image is not None, name
    return image


def test_hero_node_is_nearest_center_real_node() -> None:
    image = _load("1080p_zoommax.png")
    hero = hero_node(image)
    assert (hero.x, hero.y) == (1011, 507)


def test_only_two_real_circle_nodes_survive_filters() -> None:
    image = _load("1080p_zoommax.png")
    nodes = {(n.x, n.y) for n in detect_nodes(image)}
    assert nodes == {(1011, 507), (1189, 370)}


def test_next_node_is_jhin_stage() -> None:
    image = _load("1080p_zoommax.png")
    nxt = next_node(image)
    assert nxt is not None
    assert (nxt.x, nxt.y) == (1189, 370)


def test_open_panel_does_not_navigate() -> None:
    image = _load("1080p_panel.png")
    assert panel_open(image)
    assert next_node(image) is None


def test_empty_point_is_far_from_nodes() -> None:
    image = _load("1080p_zoommax.png")
    point = empty_point(image)
    assert point is not None
    nodes = detect_nodes(image) + detect_ability_nodes(image)
    assert all(
        ((point[0] - n.x) ** 2 + (point[1] - n.y) ** 2) ** 0.5 >= 150
        for n in nodes
    )


def test_gold_diamond_ability_node_is_not_next() -> None:
    image = _load("1080p_zoommax.png")
    abilities = detect_ability_nodes(image)
    assert any(abs(n.x - 824) <= 10 and abs(n.y - 635) <= 10 for n in abilities)
    nxt = next_node(image)
    assert nxt is not None and (nxt.x, nxt.y) == (1189, 370)


def test_blank_frame_has_no_next() -> None:
    blank = np.zeros((1080, 1920, 3), np.uint8)
    assert next_node(blank) is None


def test_solid_gold_terrain_is_not_an_ability_node() -> None:
    # 节点面板打开时的真实截图：只有 (1110,326) 是金环+深色中心的辅助英雄节点，
    # 其余同色地形/装饰都是实心金块，不能算能力节点。
    image = _load("1080p_gold_node_panel.png")
    nodes = detect_ability_nodes(image)
    assert [(n.x, n.y) for n in nodes] == [(1110, 326)]


def test_jinx_hero_portrait_is_found() -> None:
    image = _load("1080p_jinx_map.png")
    hero = recognize_hero(image)
    assert hero is not None
    assert abs(hero[0] - 735) <= 8
    assert abs(hero[1] - 285) <= 8


def test_jinx_portrait_finds_map_avatar_instead_of_fixed_hud() -> None:
    image = _load("1080p_map.png")
    hero = recognize_hero(image)
    assert hero is not None
    assert abs(hero[0] - 960) <= 15
    assert abs(hero[1] - 445) <= 15
    # 最大视角图中地图头像太小，当前匹配不足，应拒识而不是返回左下角。
    assert recognize_hero(_load("1080p_zoommax.png")) is None


def test_jinx_second_map_next_node() -> None:
    image = _load("1080p_map.png")
    nxt = next_node(image, hero=recognize_hero(image))
    assert nxt is not None
    assert abs(nxt.x - 1252) <= 20
    assert abs(nxt.y - 322) <= 20


def test_map_panels_are_not_navigable() -> None:
    for name in ("1080p_panel.png", "1080p_node_panel.png", "1080p_gold_node_panel.png"):
        image = _load(name)
        assert panel_open(image), name
        assert next_node(image, hero=recognize_hero(image)) is None


def test_jinx_map_next_node_uses_observed_hero_and_is_not_a_panel() -> None:
    image = _load("1080p_jinx_map.png")
    assert not panel_open(image)
    nxt = next_node(image, hero=recognize_hero(image))
    assert nxt is not None
    assert abs(nxt.x - 982) <= 20
    assert abs(nxt.y - 334) <= 20


def test_map_fallback_accepts_detected_hero_node() -> None:
    image = _load("1080p_map.png")
    # 此图旧代码将 MapNode 当作 tuple，在路径回退时报 TypeError；
    # 唯一检出的远处节点是下一节点，不能将其误判为当前位置。
    nxt = next_node(image)
    assert nxt is not None
    assert abs(nxt.x - 1252) <= 20
    assert abs(nxt.y - 322) <= 20


def test_path_endpoint_finds_next_node_when_rings_fail() -> None:
    image = _load("1080p_jinx_map.png")
    nxt = next_node_by_path(image, hero=(735, 285))
    assert nxt is not None
    assert abs(nxt.x - 982) <= 20
    assert abs(nxt.y - 334) <= 20
