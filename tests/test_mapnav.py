"""mapnav 1080p 回归：最大视角，英雄节点 C3，下一关 C4。"""

import random
from pathlib import Path

import cv2
import numpy as np
import pytest

from lorwright.core.champions.jinx.vision import recognize_hero
from lorwright.core.perceive.mapnav import (
    _current_battle_node_visible,
    detect_ability_nodes,
    detect_nodes,
    empty_point,
    hero_node,
    next_node,
    next_node_by_path,
    panel_open,
    reachable_nodes,
)

FIXTURES = Path(__file__).parent / "fixtures" / "mapnav"


def _load(name: str) -> np.ndarray:
    image = cv2.imread(str(FIXTURES / name))
    assert image is not None, name
    return image


def test_completed_node_follows_cyan_route_to_visible_bottom_gold_target():
    image = _load("f1-weekly-after-hero-reward-20261116.png")
    hero = recognize_hero(image)
    assert hero is not None
    node = next_node(image, hero=hero)
    assert node is not None
    assert (node.x - 940) ** 2 + (node.y - 1040) ** 2 < 20 ** 2
    assert node.needs_reveal


@pytest.mark.parametrize("damage", ["cut", "lock", "completed", "obscured", "dim", "origin"])
def test_bottom_gold_target_rejects_missing_route_or_state_evidence(damage):
    image = _load("f1-weekly-after-hero-reward-20261116.png")
    hero = recognize_hero(image)
    assert hero is not None
    if damage == "cut":
        image[780:810, 900:990] = 0
    elif damage == "lock":
        image[1022:1058, 922:958] = image[568:604, 665:701]
    elif damage == "completed":
        image[1022:1058, 922:958] = image[520:556, 942:978]
    elif damage == "obscured":
        image[1002:1078, 902:978] = 128
    elif damage == "dim":
        image[990:1080, 885:995] //= 3
    else:
        image[515:565, 935:990] = 0
    assert next_node(image, hero=hero) is None


def test_gold_target_moves_with_map_content():
    image = _load("f1-weekly-after-hero-reward-20261116.png")
    image = cv2.warpAffine(image, np.float32([[1, 0, 50], [0, 1, -100]]), (1920, 1080))
    hero = recognize_hero(image)
    assert hero is not None
    node = next_node(image, hero=hero)
    assert node is not None
    assert (node.x - 990) ** 2 + (node.y - 940) ** 2 < 20 ** 2


def test_long_cyan_route_targets_real_diamond_instead_of_display_icon():
    image = _load("f1-weekly-panned-gold-20261116.png")
    hero = recognize_hero(image)
    assert hero is not None
    node = next_node(image, hero=hero)
    assert node is not None
    assert (node.x - 940) ** 2 + (node.y - 1003) ** 2 < 20 ** 2
    assert not node.needs_reveal


@pytest.mark.parametrize("damage", ["cut", "obscured", "dim"])
def test_long_diamond_route_rejects_missing_evidence(damage):
    image = _load("f1-weekly-panned-gold-20261116.png")
    hero = recognize_hero(image)
    assert hero is not None
    if damage == "cut":
        image[650:680, 900:990] = 0
    elif damage == "obscured":
        image[961:1046, 897:982] = 128
    else:
        image[950:1060, 885:995] //= 3
    assert all(node.needs_reveal for node in reachable_nodes(image, hero=hero))


def test_gold_icon_does_not_duplicate_its_complete_diamond_destination():
    image = _load("map-frame-1.png")
    hero = recognize_hero(image)
    assert hero is not None
    nodes = reachable_nodes(image, hero=hero)
    assert len(nodes) == 1
    assert (nodes[0].x - 937) ** 2 + (nodes[0].y - 772) ** 2 < 15 ** 2


def test_completed_weekly_round_node_follows_one_of_its_cyan_routes() -> None:
    image = _load("f1-weekly-after-second-reward-20261116.png")
    hero = recognize_hero(image)
    assert hero is not None
    found = set()
    for seed in range(6):
        node = next_node(image, hero=hero, rng=random.Random(seed))
        assert node is not None
        target = min(((689, 151), (910, 233)),
                     key=lambda p: (node.x - p[0]) ** 2 + (node.y - p[1]) ** 2)
        assert (node.x - target[0]) ** 2 + (node.y - target[1]) ** 2 < 15 ** 2
        found.add(target)
    assert len(found) == 2


@pytest.mark.parametrize("target", [(689, 151), (910, 233)])
@pytest.mark.parametrize("damage", ["cut", "lock", "completed", "obscured", "dim"])
def test_completed_weekly_round_node_rejects_each_damaged_branch(target, damage) -> None:
    image = _load("f1-weekly-after-second-reward-20261116.png")
    x, y = target
    if damage == "cut":
        cut_x, cut_y = (800, 320) if x == 689 else (929, 340)
        cv2.line(image, (cut_x - 40, cut_y), (cut_x + 40, cut_y), (0, 0, 0), 20)
    elif damage == "lock":
        image[y - 18:y + 18, x - 18:x + 18] = image[137:173, 1101:1137]
    elif damage == "completed":
        image[y - 18:y + 18, x - 18:x + 18] = image[520:556, 942:978]
    elif damage == "obscured":
        image[y - 18:y + 18, x - 18:x + 18] = 128
    else:
        image[y - 70:y + 70, x - 70:x + 70] //= 3
    hero = recognize_hero(image)
    assert hero is not None
    other = (910, 233) if x == 689 else (689, 151)
    for seed in range(3):
        node = next_node(image, hero=hero, rng=random.Random(seed))
        assert node is not None
        assert (node.x - other[0]) ** 2 + (node.y - other[1]) ** 2 < 15 ** 2


def test_completed_weekly_round_node_requires_its_completion_mark() -> None:
    image = _load("f1-weekly-after-second-reward-20261116.png")
    hero = recognize_hero(image)
    image[515:565, 935:990] = 0
    assert next_node(image, hero=hero) is None


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


@pytest.mark.parametrize("name", ["f1-after-hero-item-20261115.png"]
                         + [f"map-frame-{i}.png" for i in range(1, 5)])
def test_completed_node_follows_lit_diamond(name: str) -> None:
    image = _load(name)
    hero = recognize_hero(image)
    assert hero is not None
    node = next_node(image, hero=hero)
    assert node is not None
    assert (node.x - 937) ** 2 + (node.y - 772) ** 2 < 15 ** 2


@pytest.mark.parametrize("damage", ("cut", "lock", "completed", "decoration", "obscured"))
def test_lit_diamond_rejects_unsafe_states(damage: str) -> None:
    image = _load("map-frame-3.png")
    hero = recognize_hero(image)
    assert hero is not None
    if damage == "cut":
        cv2.line(image, (920, 607), (980, 607), (0, 0, 0), 12)
    elif damage == "lock":
        # 复制同一实拍中已锁节点的锁图标。
        image[758:786, 923:951] = image[592:620, 1484:1512]
    elif damage == "completed":
        cv2.line(image, (918, 772), (932, 783), (40, 220, 40), 11)
        cv2.line(image, (932, 783), (957, 754), (40, 220, 40), 11)
    elif damage == "decoration":
        image[720:827, 883:992] = (image[720:827, 883:992] * 0.4).astype(np.uint8)
    else:
        image[762:782, 927:947] = 128
    assert next_node(image, hero=hero) is None


@pytest.mark.parametrize("name", ["f1-weekly-after-card-reward-20261116.png",
                                  "f1-weekly-support-dim-20261116.png"])
@pytest.mark.parametrize("offset", [(0, 0), (-120, 20), (100, -100)])
def test_weekly_completed_battle_follows_lit_support_node(name, offset) -> None:
    image = _load(name)
    dx, dy = offset
    image = cv2.warpAffine(image, np.float32([[1, 0, dx], [0, 1, dy]]), (1920, 1080))
    hero = recognize_hero(image)
    assert hero is not None
    node = next_node(image, hero=hero)
    assert node is not None
    assert abs(node.x - (992 + dx)) < 8 and abs(node.y - (510 + dy)) < 8


@pytest.mark.parametrize("damage", ["cut", "marker", "locked", "completed", "rim", "current"])
def test_weekly_support_node_requires_complete_route_evidence(damage) -> None:
    image = _load("f1-weekly-after-card-reward-20261116.png")
    hero = recognize_hero(image)
    assert hero is not None
    if damage == "cut":
        image[566:583, 960:1010] = 0
    elif damage == "marker":
        image[390:450, 966:1023] = 0
    elif damage == "locked":
        image[496:524, 978:1006] = image[245:273, 1684:1712]
    elif damage == "completed":
        cv2.line(image, (974, 510), (986, 520), (40, 220, 40), 11)
        cv2.line(image, (986, 520), (1010, 493), (40, 220, 40), 11)
    elif damage == "rim":
        image[463:558, 945:1042] = (image[463:558, 945:1042] * 0.4).astype(np.uint8)
    else:
        image[683:753, 908:1018] = 0
    assert next_node(image, hero=hero) is None


def test_weekly_support_fork_follows_either_verified_lit_battle() -> None:
    image = _load("f1-weekly-after-support-20261116.png")
    hero = recognize_hero(image)
    assert hero is not None
    choices = {next_node(image, hero=hero, rng=random.Random(seed)).center for seed in range(8)}
    assert len(choices) == 2
    assert all(min((x - tx) ** 2 + (y - ty) ** 2 for tx, ty in ((825, 345), (1107, 337)))
               < 12 ** 2 for x, y in choices)


@pytest.mark.parametrize("damage", ["cut", "lock", "completed", "obscured", "dim", "current"])
def test_weekly_support_fork_does_not_choose_damaged_left_branch(damage) -> None:
    image = _load("f1-weekly-after-support-20261116.png")
    hero = recognize_hero(image)
    assert hero is not None
    if damage == "cut":
        cv2.line(image, (855, 455), (895, 415), (0, 0, 0), 20)
    elif damage == "lock":
        image[327:363, 807:843] = image[270:306, 1651:1687]
    elif damage == "completed":
        cv2.line(image, (807, 345), (819, 355), (40, 220, 40), 11)
        cv2.line(image, (819, 355), (843, 328), (40, 220, 40), 11)
    elif damage == "obscured":
        image[335:355, 815:835] = 0
    elif damage == "dim":
        image[280:410, 760:890] = (image[280:410, 760:890] * 0.4).astype(np.uint8)
    else:
        image[516:565, 930:991] = 0
    for seed in range(3):
        node = next_node(image, hero=hero, rng=random.Random(seed))
        if damage == "current":
            assert node is None
        else:
            assert node is not None and (node.x - 1107) ** 2 + (node.y - 337) ** 2 < 12 ** 2


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


@pytest.mark.parametrize("name", ["f1-karma-current-20261114.png",
                                  "f1-reentry-cave-20261115.png"])
def test_current_unfinished_battle_can_be_reentered(name: str) -> None:
    image = _load(name)
    assert not panel_open(image)
    hero = recognize_hero(image)
    assert hero is not None
    node = next_node(image, hero=hero)
    assert node is not None
    assert abs(node.x - 960) <= 15 and abs(node.y - 540) <= 15


@pytest.mark.parametrize("name", [
    "f1-after-shop-20261114.png",
    "f1-before-healer-1080.png",
    "1080p_jinx_fork_after_support.png",
    "1080p_map.png",
])
def test_other_current_nodes_are_not_unfinished_battles(name: str) -> None:
    image = _load(name)
    hero = recognize_hero(image)
    assert hero is not None
    assert not _current_battle_node_visible(image, hero)


@pytest.mark.parametrize("name", ["f1-karma-current-20261114.png",
                                  "f1-reentry-cave-20261115.png"])
def test_obscured_or_dimmed_current_battle_is_not_reentered(name: str) -> None:
    image = _load(name)
    hero = recognize_hero(image)
    assert hero is not None
    obscured = image.copy()
    x, y = hero[0], hero[1] + 95
    obscured[y - 10:y + 10, x - 10:x + 10] = 128
    assert not _current_battle_node_visible(obscured, hero)
    assert not _current_battle_node_visible((image * 0.75).astype(np.uint8), hero)


def test_reentry_cave_completed_or_locked_node_is_not_reentered() -> None:
    image = _load("f1-reentry-cave-20261115.png")
    hero = recognize_hero(image)
    assert hero is not None
    x, y = hero[0], hero[1] + 95
    completed = image.copy()
    cv2.line(completed, (x - 18, y), (x - 6, y + 10), (40, 220, 40), 11)
    cv2.line(completed, (x - 6, y + 10), (x + 18, y - 17), (40, 220, 40), 11)
    assert not _current_battle_node_visible(completed, hero)
    locked = image.copy()
    locked[y - 18:y + 18, x - 18:x + 18] = image[415:451, 1290:1326]
    assert not _current_battle_node_visible(locked, hero)


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


def test_completed_current_node_follows_verified_jpeg_route() -> None:
    image = _load("f1-healer-route-20261113.jpg")
    hero = recognize_hero(image)
    assert hero is not None
    node = next_node(image, hero=hero)
    assert node is not None
    assert (node.x - 1173) ** 2 + (node.y - 521) ** 2 <= 35 ** 2


@pytest.mark.parametrize(
    ("relative", "target"),
    [
        ("mapnav/f1-after-shop-20261114.png", (1185, 573)),
        ("mapnav/f1-resumed-map-20261114.png", (1203, 575)),
        ("mapnav/f1-before-healer-1080.png", (1191, 603)),
        ("healer/f1-after-heal.png", (1166, 444)),
        ("healer/f1-after-heal-alt.png", (1166, 444)),
        ("healer/f1-after-heal-dim.png", (1166, 444)),
    ],
)
def test_completed_current_node_follows_real_lit_route(relative, target) -> None:
    image = cv2.imread(str(FIXTURES.parent / relative))
    assert image is not None
    hero = recognize_hero(image)
    assert hero is not None
    node = next_node(image, hero=hero)
    assert node is not None
    assert (node.x - target[0]) ** 2 + (node.y - target[1]) ** 2 <= 35 ** 2


@pytest.mark.parametrize(
    ("relative", "start", "target"),
    [
        ("mapnav/f1-after-shop-20261114.png", (959, 535), (1185, 573)),
        ("mapnav/f1-resumed-map-20261114.png", (959, 534), (1203, 575)),
        ("mapnav/f1-before-healer-1080.png", (958, 511), (1191, 603)),
        ("healer/f1-after-heal.png", (959, 534), (1166, 444)),
        ("healer/f1-after-heal-alt.png", (958, 537), (1167, 435)),
        ("healer/f1-after-heal-dim.png", (958, 537), (1165, 436)),
    ],
)
@pytest.mark.parametrize("position", (0.13, 0.2, 0.5, 0.8))
def test_completed_node_rejects_cut_paths_in_both_directions(
    relative, start, target, position
) -> None:
    image = cv2.imread(str(FIXTURES.parent / relative))
    assert image is not None
    hero = recognize_hero(image)
    assert hero is not None
    dx, dy = target[0] - start[0], target[1] - start[1]
    distance = (dx * dx + dy * dy) ** 0.5
    x, y = int(start[0] + dx * position), int(start[1] + dy * position)
    a = (int(x - dy / distance * 30), int(y + dx / distance * 30))
    b = (int(x + dy / distance * 30), int(y - dx / distance * 30))
    cv2.line(image, a, b, (0, 0, 0), 15)
    assert next_node(image, hero=hero) is None


@pytest.mark.parametrize("relative,target", [
    ("mapnav/f1-after-shop-20261114.png", (1185, 573)),
    ("mapnav/f1-resumed-map-20261114.png", (1203, 575)),
    ("mapnav/f1-before-healer-1080.png", (1191, 603)),
    ("healer/f1-after-heal.png", (1166, 444)),
    ("healer/f1-after-heal-alt.png", (1167, 435)),
    ("healer/f1-after-heal-dim.png", (1165, 436)),
])
def test_completed_node_does_not_revisit_a_completed_target(relative, target) -> None:
    image = cv2.imread(str(FIXTURES.parent / relative))
    assert image is not None
    hero = recognize_hero(image)
    assert hero is not None
    x, y = target
    cv2.line(image, (x - 20, y), (x - 5, y + 15), (40, 220, 40), 11)
    cv2.line(image, (x - 5, y + 15), (x + 23, y - 20), (40, 220, 40), 11)
    assert next_node(image, hero=hero) is None


@pytest.mark.parametrize("position", (0.13, 0.25, 0.5, 0.75, 0.9))
def test_round_current_node_does_not_follow_cut_path(position) -> None:
    image = _load("1080p_map.png")
    hero = recognize_hero(image)
    assert hero is not None
    start, target = (959, 534), (1252, 322)
    dx, dy = target[0] - start[0], target[1] - start[1]
    distance = (dx * dx + dy * dy) ** 0.5
    x, y = int(start[0] + dx * position), int(start[1] + dy * position)
    a = (int(x - dy / distance * 30), int(y + dx / distance * 30))
    b = (int(x + dy / distance * 30), int(y - dx / distance * 30))
    cv2.line(image, a, b, (0, 0, 0), 15)
    assert next_node(image, hero=hero) is None


@pytest.mark.parametrize("position", (0.13, 0.2, 0.4, 0.5, 0.6, 0.7))
def test_completed_node_does_not_follow_a_cut_path(position) -> None:
    image = _load("f1-healer-route-20261113.jpg")
    hero = recognize_hero(image)
    assert hero is not None
    # 包括靠近当前节点的断线，不能将另一端的亮环视作已连接。
    start, end = (963, 454), (1173, 521)
    x = int(start[0] + (end[0] - start[0]) * position)
    y = int(start[1] + (end[1] - start[1]) * position)
    cv2.line(image, (x - 15, y + 30), (x + 15, y - 30), (0, 0, 0), 15)
    assert next_node(image, hero=hero) is None


def test_completed_node_does_not_select_obscured_healer() -> None:
    image = _load("f1-healer-route-20261113.jpg")
    hero = recognize_hero(image)
    assert hero is not None
    cv2.rectangle(image, (1140, 490), (1205, 555), (0, 0, 0), -1)
    assert next_node(image, hero=hero) is None


@pytest.mark.parametrize("name", (
    "f1-after-shop-20261114.png", "f1-resumed-map-20261114.png",
))
@pytest.mark.parametrize("shade", (0, 80, 160))
def test_shop_node_does_not_navigate_when_current_marker_is_obscured(name, shade) -> None:
    image = _load(name)
    hero = recognize_hero(image)
    assert hero is not None
    cv2.rectangle(image, (hero[0] - 34, hero[1] + 55),
                  (hero[0] + 34, hero[1] + 117), (shade,) * 3, -1)
    assert next_node(image, hero=hero) is None


@pytest.mark.parametrize(("name", "target"), (
    ("f1-after-shop-20261114.png", (1185, 573)),
    ("f1-resumed-map-20261114.png", (1203, 575)),
))
def test_shop_node_does_not_select_obscured_target(name, target) -> None:
    image = _load(name)
    hero = recognize_hero(image)
    assert hero is not None
    x, y = target
    cv2.rectangle(image, (x - 35, y - 35), (x + 35, y + 35), (0, 0, 0), -1)
    assert next_node(image, hero=hero) is None


def test_shop_node_rejects_dimmed_map() -> None:
    image = _load("f1-after-shop-20261114.png")
    hero = recognize_hero(image)
    assert hero is not None
    assert next_node((image * 0.75).astype(np.uint8), hero=hero) is None


@pytest.mark.parametrize("shade", (0, 80, 160))
def test_completed_node_does_not_navigate_when_current_marker_is_obscured(shade) -> None:
    image = _load("f1-healer-route-20261113.jpg")
    hero = recognize_hero(image)
    assert hero is not None
    cv2.rectangle(image, (hero[0] - 34, hero[1] + 55),
                  (hero[0] + 34, hero[1] + 117), (shade,) * 3, -1)
    assert next_node(image, hero=hero) is None


def test_jinx_support_fork_rejects_dimmed_map() -> None:
    image = _load("1080p_jinx_fork_after_support.png")
    hero = recognize_hero(image)
    assert hero is not None
    dimmed = (image * 0.5).astype(np.uint8)
    assert next_node(dimmed, hero=hero) is None
