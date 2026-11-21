"""mapnav 1080p 回归：最大视角，英雄节点 C3，下一关 C4。"""

import functools
import math
import random

import cv2
import numpy as np
import pytest

from lorwright.core.champions.jinx.vision import recognize_hero
from lorwright.core.perceive.mapnav import (
    HeroToken,
    MapNode,
    _current_battle_node_visible,
    _route_origin,
    current_unfinished_node,
    detect_ability_nodes,
    detect_nodes,
    empty_point,
    hero_node,
    locate_map_hero,
    next_node,
    next_node_by_path,
    occluded_route_zoom_button,
    panel_open,
    reachable_nodes,
    recognize_map_token,
)
from tools.test_data import fixtures_root

FIXTURES = fixtures_root() / "mapnav"


def _load(name: str) -> np.ndarray:
    image = cv2.imread(str(FIXTURES / name))
    assert image is not None, name
    return image


@functools.lru_cache(maxsize=64)
def _hero(name: str) -> HeroToken | None:
    return recognize_hero(_load(name))


@functools.lru_cache(maxsize=64)
def _hero_rel(relative: str) -> HeroToken | None:
    image = cv2.imread(str(FIXTURES.parent / relative))
    assert image is not None, relative
    return recognize_hero(image)


@pytest.mark.parametrize("jpeg", [False, True])
def test_zoomed_halo_origin_exposes_both_branch_routes(jpeg):
    image = _load("f1-zoomed-branch-map-20261117.png")
    if jpeg:
        ok, encoded = cv2.imencode(".jpg", image)
        assert ok
        image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    hero = recognize_hero(image)
    assert hero is not None
    nodes = reachable_nodes(image, hero=hero)
    assert len(nodes) == 2
    for x, y in ((1132, 420), (1208, 605)):
        assert any(math.hypot(n.x - x, n.y - y) < 25 for n in nodes)


@pytest.mark.parametrize("damage", ["origin", "upper_cut", "lower_cut", "upper_lock", "lower_lock"])
def test_zoomed_halo_route_keeps_each_branch_independent(damage):
    image = _load("f1-zoomed-branch-map-20261117.png")
    hero = _hero("f1-zoomed-branch-map-20261117.png")
    assert hero is not None
    if damage == "origin":
        image[475:615, 890:1030] = 0
    elif damage == "upper_cut":
        image[468:493, 1028:1065] = 0
    elif damage == "lower_cut":
        image[550:587, 1060:1100] = 0
    else:
        x, y = (1132, 420) if damage == "upper_lock" else (1208, 605)
        image[y - 30:y + 31, x - 30:x + 31] = image[312:373, 1622:1683]
    nodes = reachable_nodes(image, hero=hero)
    if damage == "origin":
        assert nodes == []
    else:
        x, y = (1208, 605) if damage.startswith("upper") else (1132, 420)
        assert len(nodes) == 1
        assert math.hypot(nodes[0].x - x, nodes[0].y - y) < 25


@pytest.mark.parametrize("jpeg", [False, True])
def test_zoomed_route_uses_visible_completed_node(jpeg):
    image = _load("f1-after-gold-zoomed-map-20261117.png")
    if jpeg:
        ok, encoded = cv2.imencode(".jpg", image)
        assert ok
        image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    hero = recognize_hero(image)
    assert hero is not None
    nodes = reachable_nodes(image, hero=hero)
    assert len(nodes) == 1
    assert math.hypot(nodes[0].x - 1062, nodes[0].y - 331) < 20


@pytest.mark.parametrize("damage", ["hero", "origin", "target", "cut", "lock"])
def test_zoomed_route_requires_origin_line_and_unlocked_target(damage):
    image = _load("f1-after-gold-zoomed-map-20261117.png")
    hero = _hero("f1-after-gold-zoomed-map-20261117.png")
    assert hero is not None
    if damage == "hero":
        hero = None
    elif damage == "origin":
        image[490:585, 910:1010] = 0
    elif damage == "target":
        image[260:405, 990:1135] = 0
    elif damage == "cut":
        image[395:425, 1008:1042] = 0
    else:
        image[301:362, 1032:1093] = image[263:324, 1532:1593]
    assert reachable_nodes(image, hero=hero) == []


@pytest.mark.parametrize("jpeg", [False, True])
def test_short_avatar_occlusion_authorizes_zoom_but_not_node(jpeg):
    image = _load("f1-after-gold-map-20261117.png")
    if jpeg:
        ok, encoded = cv2.imencode(".jpg", image)
        assert ok
        image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    hero = recognize_hero(image)
    assert hero is not None
    assert reachable_nodes(image, hero=hero) == []
    button = occluded_route_zoom_button(image, hero)
    assert button is not None
    assert button.center == (1822, 297)


@pytest.mark.parametrize("damage", ["hero", "origin", "target", "lock", "controls"])
def test_occluded_route_zoom_requires_visible_map_origin_and_target(damage):
    image = _load("f1-after-gold-map-20261117.png")
    hero = _hero("f1-after-gold-map-20261117.png")
    if damage == "hero":
        hero = None
    elif damage == "origin":
        image[490:585, 910:1010] = 0
    elif damage == "target":
        image[325:450, 980:1100] = 0
    elif damage == "lock":
        image[354:415, 1006:1067] = image[214:275, 1328:1389]
    else:
        image[270:320, 1795:1850] = 0
    assert occluded_route_zoom_button(image, hero) is None


@pytest.mark.parametrize("name", ["1080p_jinx_map.png", "f1-gold-travel-panel-20261117.png"])
def test_route_zoom_does_not_replace_navigation_or_panel_handling(name):
    image = _load(name)
    assert occluded_route_zoom_button(image, _hero(name)) is None


@pytest.mark.parametrize("jpeg", [False, True])
def test_gold_travel_panel_with_attached_shadow_blocks_navigation(jpeg):
    image = _load("f1-gold-travel-panel-20261117.png")
    if jpeg:
        ok, encoded = cv2.imencode(".jpg", image)
        assert ok
        image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    assert panel_open(image)
    assert reachable_nodes(image, hero=recognize_hero(image)) == []


def test_attached_map_shadow_without_travel_label_is_not_panel():
    image = _load("f1-gold-travel-panel-20261117.png")
    image[335:377, 1133:1213] = (125, 200, 245)
    assert not panel_open(image)


@pytest.mark.parametrize("name", ["f1-two-star-after-first-battle-20261116.png",
                                  "f1-two-star-after-first-battle-stable-20261116.png"])
@pytest.mark.parametrize("offset", [(0, 0), (100, 100)])
def test_two_star_first_victory_follows_lit_route_to_support_diamond(name, offset):
    image = _load(name)
    dx, dy = offset
    image = cv2.warpAffine(image, np.float32([[1, 0, dx], [0, 1, dy]]), (1920, 1080))
    hero = recognize_hero(image)
    assert hero is not None
    nodes = reachable_nodes(image, hero=hero)
    assert len(nodes) == 1
    assert (nodes[0].x - 792 - dx) ** 2 + (nodes[0].y - 263 - dy) ** 2 < 20 ** 2


@pytest.mark.parametrize("name", ["f1-two-star-after-first-battle-20261116.png",
                                  "f1-two-star-after-first-battle-stable-20261116.png"])
@pytest.mark.parametrize("damage", ["hero", "origin", "cut", "lock", "rim", "center"])
def test_two_star_support_route_requires_visible_origin_and_target(name, damage):
    image = _load(name)
    if damage == "hero":
        image[15:120, 605:710] = 0
        assert recognize_hero(image) is None
        return
    hero = _hero(name)
    assert hero is not None
    if damage == "origin":
        image[130:175, 630:680] = 0
    elif damage == "cut":
        image[190:215, 709:743] = 0
    elif damage == "lock":
        image[242:278, 774:810] = image[263:299, 1152:1188]
    elif damage == "rim":
        image[210:315, 737:847] //= 3
    else:
        image[251:269, 783:801] = 128
    assert reachable_nodes(image, hero=hero) == []


@pytest.mark.parametrize("name,bounds,target", [
    ("f1-two-star-after-first-battle-20261116.png", (755, 130, 830, 215), (792, 260)),
    ("f1-weekly-after-card-reward-20261116.png", (966, 390, 1023, 450), (992, 510)),
])
@pytest.mark.parametrize("replacement", [0, 128])
def test_unknown_business_marker_preserves_verified_diamond_route(name, bounds, target, replacement):
    image = _load(name)
    hero = _hero(name)
    assert hero is not None
    x1, y1, x2, y2 = bounds
    image[y1:y2, x1:x2] = replacement
    nodes = reachable_nodes(image, hero=hero)
    assert len(nodes) == 1
    assert math.dist(nodes[0].center, target) < 10
    assert not nodes[0].needs_reveal


@pytest.mark.parametrize("shape", ["round", "diamond"])
@pytest.mark.parametrize("direction", [(1, 0), (-1, 0), (0, 1), (0, -1),
                                       (1, 1), (-1, 1), (1, -1), (-1, -1)])
@pytest.mark.parametrize("broken", [False, True])
def test_shared_navigation_follows_visible_edges_in_each_direction(shape, direction, broken):
    image = np.full((1080, 1920, 3), 70, np.uint8)
    origin = _load("map-frame-1.png")
    image[400:590, 880:1040] = origin[400:590, 880:1040]
    anchor, hero = (961, 533), (963, 453)
    dx, dy = direction
    target = (anchor[0] + dx * 300, anchor[1] + dy * 280)
    if shape == "round":
        source = _load("f1-weekly-after-power-20261116.png")
        patch = source[360:500, 1193:1333]
    else:
        source = _load("f1-two-star-after-first-battle-20261116.png")
        patch = source[190:330, 722:862]
    x, y = target
    image[y - 70:y + 70, x - 70:x + 70] = patch
    length = math.dist(anchor, target)
    start = (round(anchor[0] + dx * 300 / length * 50),
             round(anchor[1] + dy * 280 / length * 50))
    end = (round(x - dx * 300 / length * 35), round(y - dy * 280 / length * 35))
    cv2.line(image, start, end, (255, 255, 110), 5)
    if broken:
        cx, cy = (anchor[0] + x) // 2, (anchor[1] + y) // 2
        image[cy - 20:cy + 21, cx - 20:cx + 21] = 70
    nodes = reachable_nodes(image, hero=hero)
    if broken:
        assert nodes == []
    else:
        assert len(nodes) == 1
        assert math.dist(nodes[0].center, target) < 15
        assert not nodes[0].needs_reveal


@pytest.mark.parametrize("offset", [(0, 0), (100, 100)])
def test_short_display_edge_uses_visible_rim_contact(offset):
    image = _load("f1-short-display-edge-20261117.png")
    dx, dy = offset
    image = cv2.warpAffine(image, np.float32([[1, 0, dx], [0, 1, dy]]), (1920, 1080))
    hero = recognize_hero(image)
    assert hero is not None
    nodes = reachable_nodes(image, hero=hero)
    assert len(nodes) == 1
    assert math.dist(nodes[0].center, (1026 + dx, 426 + dy)) < 12
    assert not nodes[0].needs_reveal


@pytest.mark.parametrize("damage", ["cut", "origin", "rim", "center", "lock", "completed"])
def test_short_display_edge_requires_route_and_unfinished_target(damage):
    image = _load("f1-short-display-edge-20261117.png")
    hero = _hero("f1-short-display-edge-20261117.png")
    assert hero is not None
    if damage == "cut":
        image[266:282, 964:1007] = 0
    elif damage == "origin":
        image[165:225, 930:990] = 0
    elif damage == "rim":
        image[370:480, 970:1082] //= 3
    elif damage == "center":
        image[412:440, 1012:1040] = 128
    elif damage == "lock":
        source = _load("f1-weekly-two-home-20261116.png")
        image[408:444, 1008:1044] = source[515:551, 717:753]
    else:
        source = _load("f1-weekly-after-hero-reward-20261116.png")
        image[408:444, 1008:1044] = source[520:556, 942:978]
    assert reachable_nodes(image, hero=hero) == []


def test_weekly_home_follows_lit_route_to_first_power_diamond():
    image = _load("f1-weekly-two-home-20261116.png")
    hero = recognize_hero(image)
    assert hero is not None
    nodes = reachable_nodes(image, hero=hero)
    assert len(nodes) == 1
    assert (nodes[0].x - 514) ** 2 + (nodes[0].y - 273) ** 2 < 20 ** 2
    assert not nodes[0].needs_reveal


@pytest.mark.parametrize("damage", ["cut", "origin", "arrow", "lock", "completed", "dim", "edge"])
def test_weekly_home_rejects_missing_route_or_state_evidence(damage):
    image = _load("f1-weekly-two-home-20261116.png")
    hero = _hero("f1-weekly-two-home-20261116.png")
    assert hero is not None
    if damage == "cut":
        image[220:250, 395:435] = 0
    elif damage == "origin":
        image[165:207, 270:315] = 0
    elif damage == "arrow":
        image[249:288, 490:531] = 128
    elif damage == "lock":
        image[251:287, 496:532] = image[515:551, 717:753]
    elif damage == "completed":
        source = _load("f1-weekly-after-hero-reward-20261116.png")
        image[251:287, 496:532] = source[520:556, 942:978]
    elif damage == "dim":
        image //= 3
    else:
        image[198:229, 328:365] = 0
    assert reachable_nodes(image, hero=hero) == []


def test_weekly_home_target_moves_with_map_content():
    image = _load("f1-weekly-two-home-20261116.png")
    image = cv2.warpAffine(image, np.float32([[1, 0, 100], [0, 1, 100]]), (1920, 1080))
    hero = recognize_hero(image)
    assert hero is not None
    nodes = reachable_nodes(image, hero=hero)
    assert len(nodes) == 1
    assert (nodes[0].x - 614) ** 2 + (nodes[0].y - 373) ** 2 < 20 ** 2


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
    hero = _hero("f1-weekly-after-hero-reward-20261116.png")
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
    hero = _hero("f1-weekly-panned-gold-20261116.png")
    assert hero is not None
    if damage == "cut":
        image[650:680, 900:990] = 0
    elif damage == "obscured":
        image[961:1046, 897:982] = 128
    else:
        image[950:1060, 885:995] //= 3
    assert all(node.needs_reveal for node in reachable_nodes(image, hero=hero))


def test_completed_power_diamond_follows_cyan_route_to_battle():
    image = _load("f1-weekly-after-power-20261116.png")
    hero = recognize_hero(image)
    assert hero is not None
    nodes = reachable_nodes(image, hero=hero)
    assert len(nodes) == 1
    assert (nodes[0].x - 1263) ** 2 + (nodes[0].y - 430) ** 2 < 20 ** 2


@pytest.mark.parametrize("damage", ["origin", "cut", "lock", "completed", "obscured", "dim"])
def test_power_diamond_route_rejects_missing_evidence(damage):
    image = _load("f1-weekly-after-power-20261116.png")
    hero = _hero("f1-weekly-after-power-20261116.png")
    assert hero is not None
    if damage == "origin":
        image[516:565, 930:991] = 0
    elif damage == "cut":
        image[450:520, 1090:1110] = 0
    elif damage == "lock":
        image[412:448, 1245:1281] = image[62:98, 1512:1548]
    elif damage == "completed":
        image[412:448, 1245:1281] = image[352:388, 525:561]
    elif damage == "obscured":
        image[390:470, 1223:1303] = 128
    else:
        image[360:500, 1193:1333] //= 3
    assert reachable_nodes(image, hero=hero) == []


def test_gold_icon_does_not_duplicate_its_complete_diamond_destination():
    image = _load("map-frame-1.png")
    hero = recognize_hero(image)
    assert hero is not None
    nodes = reachable_nodes(image, hero=hero)
    assert len(nodes) == 1
    assert (nodes[0].x - 937) ** 2 + (nodes[0].y - 772) ** 2 < 15 ** 2


def test_completed_weekly_round_node_follows_one_of_its_cyan_routes() -> None:
    image = _load("f1-weekly-after-second-reward-20261116.png")
    hero = _hero("f1-weekly-after-second-reward-20261116.png")
    assert hero is not None
    nodes = reachable_nodes(image, hero=hero)
    assert len(nodes) == 2
    found = set()
    for node in nodes:
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
    nodes = reachable_nodes(image, hero=hero)
    assert len(nodes) == 1
    assert (nodes[0].x - other[0]) ** 2 + (nodes[0].y - other[1]) ** 2 < 15 ** 2


def test_completed_weekly_round_node_requires_its_completion_mark() -> None:
    image = _load("f1-weekly-after-second-reward-20261116.png")
    hero = _hero("f1-weekly-after-second-reward-20261116.png")
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
    token = locate_map_hero(image)
    assert token is not None
    nxt = next_node(image, hero=token)
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
    token = locate_map_hero(image)
    assert token is not None
    nxt = next_node(image, hero=token)
    assert nxt is not None and (nxt.x, nxt.y) == (1189, 370)


@pytest.mark.parametrize("name", ["f1-after-hero-item-20261115.png"]
                         + [f"map-frame-{i}.png" for i in range(1, 5)])
def test_completed_node_follows_lit_diamond(name: str) -> None:
    image = _load(name)
    hero = _hero(name)
    assert hero is not None
    node = next_node(image, hero=hero)
    assert node is not None
    assert (node.x - 937) ** 2 + (node.y - 772) ** 2 < 15 ** 2


@pytest.mark.parametrize("damage", ("cut", "lock", "completed", "decoration", "obscured"))
def test_lit_diamond_rejects_unsafe_states(damage: str) -> None:
    image = _load("map-frame-3.png")
    hero = _hero("map-frame-3.png")
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


@pytest.mark.parametrize("damage", ["cut", "locked", "completed", "rim", "current"])
def test_weekly_support_node_requires_complete_route_evidence(damage) -> None:
    image = _load("f1-weekly-after-card-reward-20261116.png")
    hero = _hero("f1-weekly-after-card-reward-20261116.png")
    assert hero is not None
    if damage == "cut":
        image[566:583, 960:1010] = 0
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
    hero = _hero("f1-weekly-after-support-20261116.png")
    assert hero is not None
    nodes = reachable_nodes(image, hero=hero)
    choices = {node.center for node in nodes}
    assert len(choices) == 2
    assert all(min((x - tx) ** 2 + (y - ty) ** 2 for tx, ty in ((825, 345), (1107, 337)))
               < 12 ** 2 for x, y in choices)


@pytest.mark.parametrize("damage", ["cut", "lock", "completed", "obscured", "dim", "current"])
def test_weekly_support_fork_does_not_choose_damaged_left_branch(damage) -> None:
    image = _load("f1-weekly-after-support-20261116.png")
    hero = _hero("f1-weekly-after-support-20261116.png")
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
    nodes = reachable_nodes(image, hero=hero)
    if damage == "current":
        assert nodes == []
    else:
        assert len(nodes) == 1
        assert (nodes[0].x - 1107) ** 2 + (nodes[0].y - 337) ** 2 < 12 ** 2


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
    hero = _hero(name)
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
    hero = _hero(name)
    assert hero is not None
    assert not _current_battle_node_visible(image, hero)


@pytest.mark.parametrize("name", ["f1-karma-current-20261114.png",
                                  "f1-reentry-cave-20261115.png"])
def test_obscured_or_dimmed_current_battle_is_not_reentered(name: str) -> None:
    image = _load(name)
    hero = _hero(name)
    assert hero is not None
    obscured = image.copy()
    x, y = hero[0], hero[1] + 95
    obscured[y - 10:y + 10, x - 10:x + 10] = 128
    assert not _current_battle_node_visible(obscured, hero)
    assert not _current_battle_node_visible((image * 0.75).astype(np.uint8), hero)


def test_reentry_cave_completed_or_locked_node_is_not_reentered() -> None:
    image = _load("f1-reentry-cave-20261115.png")
    hero = _hero("f1-reentry-cave-20261115.png")
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
    nxt = next_node(image, hero=_hero("1080p_map.png"))
    assert nxt is not None
    assert abs(nxt.x - 1252) <= 20
    assert abs(nxt.y - 322) <= 20


def test_map_panels_are_not_navigable() -> None:
    for name in ("1080p_panel.png", "1080p_node_panel.png", "1080p_gold_node_panel.png"):
        image = _load(name)
        assert panel_open(image), name
        assert next_node(image, hero=_hero(name)) is None


def test_jinx_map_next_node_uses_observed_hero_and_is_not_a_panel() -> None:
    image = _load("1080p_jinx_map.png")
    assert not panel_open(image)
    nxt = next_node(image, hero=_hero("1080p_jinx_map.png"))
    assert nxt is not None
    assert abs(nxt.x - 982) <= 20
    assert abs(nxt.y - 334) <= 20


def test_map_navigation_uses_detected_token() -> None:
    image = _load("1080p_map.png")
    token = locate_map_hero(image)
    assert token is not None
    nxt = next_node(image, hero=token)
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
    hero = _hero("1080p_jinx_fork_after_support.png")
    assert hero is not None

    targets = ((1141, 513), (1044, 841))
    nodes = reachable_nodes(image, hero=hero)
    assert len(nodes) == 2
    found = set()
    for node in nodes:
        matching = [i for i, (x, y) in enumerate(targets)
                    if abs(node.x - x) <= 20 and abs(node.y - y) <= 20]
        assert len(matching) == 1
        found.add(matching[0])
    assert found == {0, 1}


def test_jinx_support_fork_rejects_disconnected_paths() -> None:
    image = _load("1080p_jinx_fork_after_support.png")
    hero = _hero("1080p_jinx_fork_after_support.png")
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
    hero = _hero("1080p_jinx_fork_after_support.png")
    assert hero is not None
    anchor = (960, 411)
    dx, dy = target[0] - anchor[0], target[1] - anchor[1]
    length = (dx * dx + dy * dy) ** 0.5
    x, y = int(anchor[0] + dx * position), int(anchor[1] + dy * position)
    start = (int(x - dy / length * 30), int(y + dx / length * 30))
    end = (int(x + dy / length * 30), int(y - dx / length * 30))
    cv2.line(image, start, end, (0, 0, 0), 12)
    nodes = reachable_nodes(image, hero=hero)
    assert all((node.x - target[0]) ** 2 + (node.y - target[1]) ** 2 > 40 ** 2 for node in nodes)


def test_jinx_support_fork_rejects_completed_nodes() -> None:
    image = _load("1080p_jinx_fork_after_support.png")
    hero = _hero("1080p_jinx_fork_after_support.png")
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
    hero = _hero("1080p_jinx_fork_after_support.png")
    assert hero is not None
    x, y = target
    # 即使完成勾被遮住，也不能把被遮住的目标当作可走节点。
    cv2.line(image, (x - 15, y), (x - 4, y + 10), (40, 220, 40), 8)
    cv2.line(image, (x - 4, y + 10), (x + 15, y - 12), (40, 220, 40), 8)
    cv2.rectangle(image, (x - half_size, y - half_size),
                  (x + half_size, y + half_size), (shade, shade, shade), -1)
    nodes = reachable_nodes(image, hero=hero)
    assert all((node.x - x) ** 2 + (node.y - y) ** 2 > 40 ** 2 for node in nodes)


@pytest.mark.parametrize("target", ((1141, 513), (1044, 841)))
@pytest.mark.parametrize("shade", (0, 30, 90, 150, 220))
def test_jinx_support_fork_rejects_small_center_occlusion(target, shade) -> None:
    image = _load("1080p_jinx_fork_after_support.png")
    hero = _hero("1080p_jinx_fork_after_support.png")
    assert hero is not None
    x, y = target
    cv2.rectangle(image, (x - 10, y - 10), (x + 10, y + 10), (shade,) * 3, -1)
    nodes = reachable_nodes(image, hero=hero)
    assert all((node.x - x) ** 2 + (node.y - y) ** 2 > 40 ** 2 for node in nodes)


def test_jinx_support_fork_does_not_use_loose_fallback_for_completed_node() -> None:
    image = _load("1080p_jinx_fork_after_support.png")
    hero = _hero("1080p_jinx_fork_after_support.png")
    assert hero is not None
    cv2.line(image, (1024, 841), (1039, 856), (40, 220, 40), 12)
    cv2.line(image, (1039, 856), (1069, 821), (40, 220, 40), 12)
    # 一帧亮线变长时，不能让宽松的旧回退绕过完成标记检查。
    cv2.line(image, (965, 445), (965, 430), (255, 255, 255), 8)
    node = next_node(image, hero=hero, rng=random.Random(0))
    assert node is None or (node.x - 1044) ** 2 + (node.y - 841) ** 2 > 40 ** 2


def test_jinx_support_fork_does_not_return_to_completed_node() -> None:
    image = _load("1080p_jinx_fork_after_support.png")
    hero = _hero("1080p_jinx_fork_after_support.png")
    assert hero is not None
    # 已完成节点及其旧路径变亮，不能绕过分叉路线检查。
    cv2.line(image, hero, (737, 371), (255, 255, 255), 8)
    nodes = reachable_nodes(image, hero=hero)
    assert all((node.x - 737) ** 2 + (node.y - 371) ** 2 > 40 ** 2 for node in nodes)


@pytest.mark.parametrize("shade", (0, 30, 90, 150))
def test_jinx_support_fork_stops_when_current_node_is_obscured(shade) -> None:
    image = _load("1080p_jinx_fork_after_support.png")
    hero = _hero("1080p_jinx_fork_after_support.png")
    assert hero is not None
    cv2.rectangle(image, (930, 380), (990, 430), (shade, shade, shade), -1)
    cv2.line(image, (965, 445), (965, 430), (255, 255, 255), 8)
    assert next_node(image, hero=hero) is None


def test_jinx_stops_when_current_round_node_is_obscured() -> None:
    image = _load("1080p_map.png")
    hero = _hero("1080p_map.png")
    assert hero is not None
    cv2.rectangle(image, (hero[0] - 30, hero[1] + 65),
                  (hero[0] + 30, hero[1] + 125), (90, 90, 90), -1)
    assert next_node(image, hero=hero) is None


def test_completed_current_node_follows_verified_jpeg_route() -> None:
    image = _load("f1-healer-route-20261113.jpg")
    hero = _hero("f1-healer-route-20261113.jpg")
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
    hero = _hero_rel(relative)
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
    hero = _hero_rel(relative)
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
    hero = _hero_rel(relative)
    assert hero is not None
    x, y = target
    cv2.line(image, (x - 20, y), (x - 5, y + 15), (40, 220, 40), 11)
    cv2.line(image, (x - 5, y + 15), (x + 23, y - 20), (40, 220, 40), 11)
    assert next_node(image, hero=hero) is None


@pytest.mark.parametrize("position", (0.13, 0.25, 0.5, 0.75, 0.9))
def test_round_current_node_does_not_follow_cut_path(position) -> None:
    image = _load("1080p_map.png")
    hero = _hero("1080p_map.png")
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
    hero = _hero("f1-healer-route-20261113.jpg")
    assert hero is not None
    # 包括靠近当前节点的断线，不能将另一端的亮环视作已连接。
    start, end = (963, 454), (1173, 521)
    x = int(start[0] + (end[0] - start[0]) * position)
    y = int(start[1] + (end[1] - start[1]) * position)
    cv2.line(image, (x - 15, y + 30), (x + 15, y - 30), (0, 0, 0), 15)
    assert next_node(image, hero=hero) is None


def test_completed_node_does_not_select_obscured_healer() -> None:
    image = _load("f1-healer-route-20261113.jpg")
    hero = _hero("f1-healer-route-20261113.jpg")
    assert hero is not None
    cv2.rectangle(image, (1140, 490), (1205, 555), (0, 0, 0), -1)
    assert next_node(image, hero=hero) is None


@pytest.mark.parametrize("name", (
    "f1-after-shop-20261114.png", "f1-resumed-map-20261114.png",
))
@pytest.mark.parametrize("shade", (0, 80, 160))
def test_shop_node_does_not_navigate_when_current_marker_is_obscured(name, shade) -> None:
    image = _load(name)
    hero = _hero(name)
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
    hero = _hero(name)
    assert hero is not None
    x, y = target
    cv2.rectangle(image, (x - 35, y - 35), (x + 35, y + 35), (0, 0, 0), -1)
    assert next_node(image, hero=hero) is None


def test_shop_node_rejects_dimmed_map() -> None:
    image = _load("f1-after-shop-20261114.png")
    hero = _hero("f1-after-shop-20261114.png")
    assert hero is not None
    assert next_node((image * 0.75).astype(np.uint8), hero=hero) is None


@pytest.mark.parametrize("shade", (0, 80, 160))
def test_completed_node_does_not_navigate_when_current_marker_is_obscured(shade) -> None:
    image = _load("f1-healer-route-20261113.jpg")
    hero = _hero("f1-healer-route-20261113.jpg")
    assert hero is not None
    cv2.rectangle(image, (hero[0] - 34, hero[1] + 55),
                  (hero[0] + 34, hero[1] + 117), (shade,) * 3, -1)
    assert next_node(image, hero=hero) is None


def test_jinx_support_fork_rejects_dimmed_map() -> None:
    image = _load("1080p_jinx_fork_after_support.png")
    hero = _hero("1080p_jinx_fork_after_support.png")
    assert hero is not None
    dimmed = (image * 0.5).astype(np.uint8)
    assert next_node(dimmed, hero=hero) is None


def test_generic_map_hero_zoommax_and_missing_hero():
    image = _load("1080p_zoommax.png")
    token = locate_map_hero(image)
    assert token is not None
    assert math.hypot(token.x - 1011, token.y - 450) < 8
    assert 24 <= token.radius <= 36
    assert recognize_map_token(image) == token.center
    assert [node.center for node in reachable_nodes(image, hero=token)] == [(1189, 370)]
    assert reachable_nodes(image, hero=None) == []


def test_generic_map_hero_rejects_dim_and_obscured():
    image = _load("1080p_zoommax.png")
    assert locate_map_hero((image * 0.5).astype(np.uint8)) is None
    cv2.rectangle(image, (970, 410), (1050, 490), (0, 0, 0), -1)
    assert locate_map_hero(image) is None


@pytest.mark.parametrize(("name", "center"), [
    ("1080p_jinx_map.png", (735, 285)),
    ("f1-two-star-after-first-battle-stable-20261116.png", (659, 67)),
    ("f1-weekly-two-home-20261116.png", (296, 99)),
    ("f1-weekly-panned-gold-20261116.png", (960, 320)),
    ("f1-weekly-after-power-20261116.png", (963, 452)),
])
def test_token_geometry_handles_camera_and_terrain_changes(name, center):
    token = locate_map_hero(_load(name))
    assert token is not None
    assert math.dist(token.center, center) <= 8


def test_generic_elise_token_and_current_battle():
    source = cv2.imread(str(FIXTURES.parent / "screens" / "720p_map.png"))
    image = cv2.resize(source, (1920, 1080), interpolation=cv2.INTER_LINEAR)
    token = locate_map_hero(image)
    assert token is not None and math.dist(token.center, (959, 444)) <= 8
    nodes = reachable_nodes(image, hero=token)
    assert len(nodes) == 1 and math.dist(nodes[0].center, (959, 539)) <= 10


def test_generic_zoomed_token_preserves_visible_route():
    image = _load("f1-after-gold-zoomed-map-20261117.png")
    token = locate_map_hero(image)
    assert token is not None and 52 <= token.radius <= 64
    assert [node.center for node in reachable_nodes(image, hero=token)] == [(1062, 331)]


@pytest.mark.parametrize("name", ["1080p_panel.png", "1080p_jinx_exit_prompt.jpg",
                                   "1080p_jinx_battle_detail.png"])
def test_generic_token_rejects_non_navigation_scenes(name):
    assert locate_map_hero(_load(name)) is None


def test_visible_token_without_foot_evidence_is_rejected():
    image = _load("1080p_zoommax.png")
    # Preserve the entire token silhouette and map controls, removing the node and route.
    image[493:576, 945:1077] = (35, 42, 49)
    assert locate_map_hero(image) is None


def test_duplicate_verified_tokens_are_ambiguous():
    image = _load("1080p_zoommax.png")
    image[365:575, 420:600] = image[365:575, 920:1100]
    assert locate_map_hero(image) is None


def test_route_origin_uses_measured_token_occlusion():
    anchor = MapNode(100, 100, 30)
    target = MapNode(300, 100, 30)
    assert _route_origin(anchor, HeroToken(170, 151, 44), target) == anchor
    # At 51 px from the edge, only the larger token overlaps the route.
    assert _route_origin(anchor, HeroToken(170, 151, 56), target).radius == 106


@pytest.mark.parametrize(("path", "center", "target"), [
    ("screens/weekly-after-start-20261115.png", (608, 625), (816, 664)),
    ("mapnav/f1-weekly-two-home-20261116.png", (296, 99), (514, 269)),
    ("mapnav/f1-two-star-after-first-battle-20261116.png", (659, 67), (792, 260)),
    ("mapnav/f1-two-star-after-first-battle-stable-20261116.png", (659, 67), (792, 260)),
    ("screens/f1-astrologer-remaining-purchased-map-20261118.png", (1047, 452), None),
])
def test_weekly_early_map_routes_use_generic_token(path, center, target):
    image = cv2.imread(str(FIXTURES.parent / path))
    assert image is not None
    token = locate_map_hero(image)
    assert token is not None and math.dist(token.center, center) <= 8
    nodes = reachable_nodes(image, hero=token)
    if target is None:
        assert nodes == []
        zoom = occluded_route_zoom_button(image, token)
        assert zoom is not None and zoom.center == (1822, 297)
    else:
        assert len(nodes) == 1 and math.dist(nodes[0].center, target) <= 8
        assert not nodes[0].needs_reveal


@pytest.mark.parametrize("damage", ["occlusion", "foot", "ambiguous"])
def test_weekly_gold_terrain_does_not_substitute_for_token(damage):
    image = cv2.imread(str(FIXTURES.parent / "screens/weekly-after-start-20261115.png"))
    assert image is not None
    if damage == "occlusion":
        image[577:680, 553:657] = 0
    elif damage == "foot":
        image[681:752, 535:697] = 0
    else:
        image[555:751, 1120:1300] = image[555:751, 515:695]
    assert locate_map_hero(image) is None


def _boss_map(kind):
    image = _load(f"f1-zoomed-boss-{kind}-20261118.png")
    # 脱敏素材仅保留地图中央。补入已知控件，使测试也走运行时场景门控。
    controls = _load("f1-after-gold-zoomed-map-20261117.png")
    image[65:105, 80:118] = controls[65:105, 80:118]
    image[240:430, 1780:1864] = controls[240:430, 1780:1864]
    return image


@pytest.mark.parametrize(("kind", "expected"), [("route", (1103, 66)), ("live", (1103, 69))])
def test_zoomed_boss_crest_is_the_only_reachable_node(kind, expected):
    image = _boss_map(kind)
    hero = locate_map_hero(image)
    assert hero is not None and math.dist(hero.center, (1084, 420)) <= 8
    nodes = reachable_nodes(image, hero=hero)
    assert len(nodes) == 1  # 独立 ADB 帧上的亮塔墙不应成为第二个节点。
    assert math.dist(nodes[0].center, expected) < 8
    assert not nodes[0].needs_reveal


@pytest.mark.parametrize("damage", ["origin", "cut", "lock", "completed", "obscured", "dim"])
def test_zoomed_boss_crest_rejects_missing_route_or_target_evidence(damage):
    image = _boss_map("route")
    if damage == "origin":
        image[485:580, 1030:1130] = 0
    elif damage == "cut":
        image[230:260, 1070:1120] = 0
    elif damage == "lock":
        source = _load("f1-weekly-two-home-20261116.png")
        image[48:84, 1085:1121] = source[515:551, 717:753]
    elif damage == "completed":
        image[48:84, 1085:1121] = image[516:552, 1063:1099]
    elif damage == "obscured":
        image[56:76, 1093:1113] = 128
    else:
        image[0:180, 990:1220] //= 3
    hero = locate_map_hero(image)
    if damage != "origin":
        assert hero is not None
    assert reachable_nodes(image, hero=hero) == []


def _interrupted_event_map() -> np.ndarray:
    # 2026-11-19 断线后恢复的停止实拍，不在 491dc94 基线内；缺图时跳过。
    image = cv2.imread(str(FIXTURES / "f1-soloist-interrupted-map-20261119.png"))
    if image is None:
        pytest.skip("缺少 f1-soloist-interrupted-map-20261119.png")
    return image


def test_interrupted_event_node_is_reentry_target_while_routes_stay_locked():
    image = _interrupted_event_map()
    hero = locate_map_hero(image)
    assert reachable_nodes(image, hero=hero) == []
    node = current_unfinished_node(image, hero)
    assert node is not None and abs(node.x - 959) <= 10 and abs(node.y - 534) <= 10


def test_interrupted_event_node_requires_halo_and_unlocked_center():
    image = _interrupted_event_map()
    hero = locate_map_hero(image)
    dimmed = image.copy()
    yy, xx = np.ogrid[:1080, :1920]
    ring = ((xx - 959) ** 2 + (yy - 534) ** 2 >= 40 ** 2) & ((xx - 959) ** 2 + (yy - 534) ** 2 <= 75 ** 2)
    dimmed[ring] = (dimmed[ring] * 0.4).astype(np.uint8)
    assert current_unfinished_node(dimmed, hero) is None
    assert current_unfinished_node(image, None) is None


def test_completed_current_node_is_not_reentry_target():
    image = _load("f1-weekly-after-second-reward-20261116.png")
    assert current_unfinished_node(image, locate_map_hero(image)) is None


def _interrupted_power_map() -> np.ndarray:
    # 20261120T052533 的 map_no_next 停止实拍；不在 491dc94 基线内，缺图时跳过。
    image = cv2.imread(str(FIXTURES / "f1-power-interrupted-map-20261120.png"))
    if image is None:
        pytest.skip("缺少 f1-power-interrupted-map-20261120.png")
    return image


def test_glowing_current_diamond_is_reentry_target_while_routes_stay_locked():
    image = _interrupted_power_map()
    hero = locate_map_hero(image)
    assert reachable_nodes(image, hero=hero) == []
    node = current_unfinished_node(image, hero)
    assert node is not None and abs(node.x - 960) <= 10 and abs(node.y - 546) <= 10


def test_unfinished_support_diamond_is_reentry_target():
    image = cv2.imread(str(FIXTURES / "1080p_jinx_support_map.jpg"))
    if image is None:
        pytest.skip("缺少 1080p_jinx_support_map.jpg")
    node = current_unfinished_node(image, locate_map_hero(image))
    assert node is not None and abs(node.x - 960) <= 10 and abs(node.y - 413) <= 10


@pytest.mark.parametrize("name", [
    "f1-weekly-after-support-20261116.png",
    "1080p_jinx_map.png",
    "f1-weekly-after-power-20261116.png",
    "1080p_jinx_fork_after_support.png",
])
def test_completed_current_diamond_is_not_reentry_target(name):
    image = _load(name)
    assert current_unfinished_node(image, locate_map_hero(image)) is None


def test_current_diamond_reentry_requires_glow():
    image = _interrupted_power_map()
    hero = locate_map_hero(image)
    dimmed = image.copy()
    yy, xx = np.ogrid[:1080, :1920]
    distance = np.abs(xx - 960) + np.abs(yy - 546)
    ring = (distance >= 36) & (distance <= 62)
    dimmed[ring] = (dimmed[ring] * 0.6).astype(np.uint8)
    assert current_unfinished_node(dimmed, hero) is None


def _boss_crest_full_map(name="f1-boss-crest-map-20261120.png") -> np.ndarray:
    # 20261120T091043 / 093328 治疗后 map_no_next 停止实拍；不在 491dc94 基线内，缺图时跳过。
    image = cv2.imread(str(FIXTURES / name))
    if image is None:
        pytest.skip(f"缺少 {name}")
    return image


@pytest.mark.parametrize("name", ["f1-boss-crest-map-20261120.png", "f1-boss-crest-dim-glow-20261120.png"])
def test_full_boss_crest_is_not_a_second_hero_and_is_reachable(name):
    image = _boss_crest_full_map(name)
    hero = locate_map_hero(image)
    assert hero is not None and math.dist(hero.center, (1250, 453)) <= 8
    nodes = reachable_nodes(image, hero=hero)
    assert len(nodes) == 1 and math.dist(nodes[0].center, (1266, 188)) <= 8


def test_full_boss_crest_requires_the_lit_route():
    image = _boss_crest_full_map()
    image[300:360, 1220:1310] = image[300:360, 1420:1510]
    hero = locate_map_hero(image)
    assert hero is not None
    assert reachable_nodes(image, hero=hero) == []


def test_next_node_samples_all_reachable_branches_with_rng(monkeypatch) -> None:
    branches = [MapNode(100, 200, 30), MapNode(300, 400, 30)]
    monkeypatch.setattr("lorwright.core.perceive.mapnav.reachable_nodes", lambda *a, **kw: branches)
    image = np.zeros((1080, 1920, 3), np.uint8)
    picked = {next_node(image, rng=random.Random(seed)) for seed in range(8)}
    assert picked == set(branches)
    monkeypatch.setattr("lorwright.core.perceive.mapnav.reachable_nodes", lambda *a, **kw: [])
    assert next_node(image, rng=random.Random(0)) is None
