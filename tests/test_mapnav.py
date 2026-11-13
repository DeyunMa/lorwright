"""mapnav 1080p 回归：最大视角，英雄节点 C3，下一关 C4。"""

import random
from pathlib import Path

import cv2
import numpy as np
import pytest

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


def test_disconnected_glow_is_not_a_path_from_the_hero() -> None:
    image = np.zeros((1080, 1920, 3), np.uint8)
    cv2.circle(image, (1500, 250), 55, (255, 255, 255), 8)
    assert next_node_by_path(image, hero=(500, 500)) is None


def test_path_without_a_detected_node_is_not_clickable() -> None:
    image = np.zeros((1080, 1920, 3), np.uint8)
    cv2.rectangle(image, (500, 500), (800, 510), (255, 255, 255), -1)
    assert next_node_by_path(image, hero=(500, 500)) is None


def test_jinx_support_fork_selects_only_lit_neighboring_nodes() -> None:
    image = _load("1080p_jinx_fork_after_support.png")
    hero = recognize_hero(image)
    assert hero is not None

    targets = ((1141, 513), (1044, 841))
    found = set()
    for seed in (0, 1):
        node = next_node(image, hero=hero, rng=random.Random(seed))
        assert node is not None
        matching = [i for i, (x, y) in enumerate(targets)
                    if abs(node.x - x) <= 20 and abs(node.y - y) <= 20]
        assert len(matching) == 1
        found.add(matching[0])
    assert found == {0, 1}


def test_jinx_support_fork_rejects_disconnected_paths() -> None:
    image = _load("1080p_jinx_fork_after_support.png")
    hero = recognize_hero(image)
    assert hero is not None
    # 保留两端的节点环，将两条路线靠近英雄的一段变暗。
    image[445:515, 940:1120] = (image[445:515, 940:1120] * 0.35).astype(np.uint8)
    assert next_node(image, hero=hero) is None


@pytest.mark.parametrize(
    ("target", "position"),
    [((1141, 513), t) for t in (0.1, 0.15, 0.2, 0.65, 0.8, 0.85, 0.9)]
    + [((1044, 841), t) for t in (0.1, 0.15, 0.2, 0.65, 0.8, 0.85, 0.9)],
)
def test_jinx_support_fork_never_selects_a_cut_path(target, position) -> None:
    image = _load("1080p_jinx_fork_after_support.png")
    hero = recognize_hero(image)
    assert hero is not None
    anchor = (960, 411)
    dx, dy = target[0] - anchor[0], target[1] - anchor[1]
    length = (dx * dx + dy * dy) ** 0.5
    x, y = int(anchor[0] + dx * position), int(anchor[1] + dy * position)
    start = (int(x - dy / length * 30), int(y + dx / length * 30))
    end = (int(x + dy / length * 30), int(y - dx / length * 30))
    cv2.line(image, start, end, (0, 0, 0), 12)
    for seed in (0, 1):
        node = next_node(image, hero=hero, rng=random.Random(seed))
        assert node is None or (node.x - target[0]) ** 2 + (node.y - target[1]) ** 2 > 40 ** 2


def test_jinx_support_fork_rejects_completed_nodes() -> None:
    image = _load("1080p_jinx_fork_after_support.png")
    hero = recognize_hero(image)
    assert hero is not None
    # 在两处候选中心加上绿色完成勾，不能把它们当作下一节点。
    for x, y in ((1141, 513), (1044, 841)):
        check = np.array([(x - 20, y), (x - 5, y + 15), (x + 23, y - 20)])
        cv2.polylines(image, [check], False, (35, 225, 35), thickness=11)
    assert next_node(image, hero=hero) is None


@pytest.mark.parametrize("target", ((1141, 513), (1044, 841)))
@pytest.mark.parametrize("shade", (20, 30, 70, 120, 200))
@pytest.mark.parametrize("half_size", (20, 28, 35))
def test_jinx_support_fork_does_not_select_obscured_target(target, shade, half_size) -> None:
    image = _load("1080p_jinx_fork_after_support.png")
    hero = recognize_hero(image)
    assert hero is not None
    x, y = target
    # 即使完成勾被遮住，也不能把被遮住的目标当作可走节点。
    cv2.line(image, (x - 15, y), (x - 4, y + 10), (40, 220, 40), 8)
    cv2.line(image, (x - 4, y + 10), (x + 15, y - 12), (40, 220, 40), 8)
    cv2.rectangle(image, (x - half_size, y - half_size),
                  (x + half_size, y + half_size), (shade, shade, shade), -1)
    for seed in (0, 1):
        node = next_node(image, hero=hero, rng=random.Random(seed))
        assert node is None or (node.x - x) ** 2 + (node.y - y) ** 2 > 40 ** 2


@pytest.mark.parametrize("target", ((1141, 513), (1044, 841)))
@pytest.mark.parametrize("shade", (0, 30, 90, 150, 220))
def test_jinx_support_fork_rejects_small_center_occlusion(target, shade) -> None:
    image = _load("1080p_jinx_fork_after_support.png")
    hero = recognize_hero(image)
    assert hero is not None
    x, y = target
    cv2.rectangle(image, (x - 10, y - 10), (x + 10, y + 10), (shade,) * 3, -1)
    for seed in (0, 1):
        node = next_node(image, hero=hero, rng=random.Random(seed))
        assert node is None or (node.x - x) ** 2 + (node.y - y) ** 2 > 40 ** 2


def test_jinx_support_fork_does_not_use_loose_fallback_for_completed_node() -> None:
    image = _load("1080p_jinx_fork_after_support.png")
    hero = recognize_hero(image)
    assert hero is not None
    cv2.line(image, (1024, 841), (1039, 856), (40, 220, 40), 12)
    cv2.line(image, (1039, 856), (1069, 821), (40, 220, 40), 12)
    # 一帧亮线变长时，不能让宽松的旧回退绕过完成标记检查。
    cv2.line(image, (965, 445), (965, 430), (255, 255, 255), 8)
    node = next_node(image, hero=hero, rng=random.Random(0))
    assert node is None or (node.x - 1044) ** 2 + (node.y - 841) ** 2 > 40 ** 2


def test_jinx_support_fork_does_not_return_to_completed_node() -> None:
    image = _load("1080p_jinx_fork_after_support.png")
    hero = recognize_hero(image)
    assert hero is not None
    # 已完成节点及其旧路径变亮，不能绕过分叉路线检查。
    cv2.line(image, hero, (737, 371), (255, 255, 255), 8)
    for seed in (0, 1):
        node = next_node(image, hero=hero, rng=random.Random(seed))
        assert node is None or (node.x - 737) ** 2 + (node.y - 371) ** 2 > 40 ** 2


@pytest.mark.parametrize("shade", (0, 30, 90, 150))
def test_jinx_support_fork_stops_when_current_node_is_obscured(shade) -> None:
    image = _load("1080p_jinx_fork_after_support.png")
    hero = recognize_hero(image)
    assert hero is not None
    cv2.rectangle(image, (930, 380), (990, 430), (shade, shade, shade), -1)
    cv2.line(image, (965, 445), (965, 430), (255, 255, 255), 8)
    assert next_node(image, hero=hero) is None


def test_jinx_stops_when_current_round_node_is_obscured() -> None:
    image = _load("1080p_map.png")
    hero = recognize_hero(image)
    assert hero is not None
    cv2.rectangle(image, (hero[0] - 30, hero[1] + 65),
                  (hero[0] + 30, hero[1] + 125), (90, 90, 90), -1)
    assert next_node(image, hero=hero) is None


def test_jinx_support_fork_rejects_dimmed_map() -> None:
    image = _load("1080p_jinx_fork_after_support.png")
    hero = recognize_hero(image)
    assert hero is not None
    dimmed = (image * 0.5).astype(np.uint8)
    assert next_node(dimmed, hero=hero) is None
