"""地图控件在真实画面及遮挡时的识别回归。"""

import random

import cv2
import numpy as np
import pytest

from lorwright.core.champions import load
from lorwright.core.decide.adventure import pick_lowest_weekly
from lorwright.core.perceive.adventure_scene import (
    can_resume_adventure,
    completed_weekly_targets,
    find_resume_adventure_button,
    find_weekly_entry,
    event_leave_option,
    find_weekly_start,
    is_map,
    is_weekly_list,
    recognize_weekly_adventures,
    partial_weekly_view,
    selected_world_hero_matches,
    weekly_detail_stars,
    weekly_slot_targets,
    world_back_button,
)
from tools.test_data import fixtures_root

FIXTURES = fixtures_root()


def _image(relative: str) -> np.ndarray:
    image = cv2.imread(str(FIXTURES / relative))
    assert image is not None, relative
    return image


@pytest.mark.parametrize("name", [
    "1080p_zoommax.png",
    "1080p_map.png",
    "1080p_jinx_map.png",
    "1080p_node_panel.png",
    "1080p_jinx_support_map.jpg",
])
def test_visible_map_controls_are_recognized(name):
    assert is_map(_image("mapnav/" + name))


@pytest.mark.parametrize("relative", [
    "mapnav/1080p_jinx_exit_prompt.jpg",
    "mapnav/1080p_ability_select.png",
    "mapnav/1080p_jinx_battle_detail.png",
    "support/jinx-1080-selected-left.jpg",
    "card_rewards/before.png",
])
def test_overlay_and_other_scenes_are_not_maps(relative):
    assert not is_map(_image(relative))


@pytest.mark.parametrize("name", ["1080p_zoommax.png", "1080p_jinx_support_map.jpg"])
def test_darkened_map_is_not_authorized(name):
    image = _image("mapnav/" + name)
    darkened = cv2.convertScaleAbs(image, alpha=0.5)
    assert not is_map(darkened)


@pytest.mark.parametrize("bounds", [(1805, 275, 1840, 310), (1805, 370, 1840, 390)])
def test_partially_obscured_zoom_control_is_not_authorized(bounds):
    image = _image("mapnav/1080p_jinx_support_map.jpg")
    x1, y1, x2, y2 = bounds
    image[y1:y2, x1:x2] = 0
    assert not is_map(image)


@pytest.mark.parametrize("jpeg", [False, True])
def test_zoomed_live_map_controls_are_recognized(jpeg):
    image = _image("mapnav/f1-after-gold-zoomed-map-20261117.png")
    if jpeg:
        ok, encoded = cv2.imencode(".jpg", image)
        assert ok
        image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    assert is_map(image)


def test_fading_weekly_map_controls_are_not_authorized():
    # 会话 20261121T151728：奖励页淡出、地图淡入中途的帧与商店
    # 淡出帧同类（plus p10=121、minus=89），不能当作已稳定地图；
    # 转场核验另由等帧窗口兜底（adventure_transition 超时扩展）。
    image = _image("mapnav/f1-weekly-red-map-20261121.png")
    assert not is_map(image)


@pytest.mark.parametrize("damage", ["plus", "minus", "back", "dimmed"])
def test_zoomed_live_map_requires_visible_controls(damage):
    image = _image("mapnav/f1-after-gold-zoomed-map-20261117.png")
    if damage == "plus":
        image[275:310, 1805:1840] = 0
    elif damage == "minus":
        image[370:390, 1805:1840] = 0
    elif damage == "back":
        image[60:110, 75:125] = 0
    else:
        image = cv2.convertScaleAbs(image, alpha=0.5)
    assert not is_map(image)


@pytest.mark.parametrize("day", [14, 15])
def test_resume_adventure_recognizes_button_and_selected_jinx(day):
    image = _image(f"screens/f1-adventure-resume-202611{day}.png")
    button = find_resume_adventure_button(image)
    assert button is not None
    assert 1390 <= button.x <= 1410 and 940 <= button.y <= 955
    assert can_resume_adventure(image, load("jinx"))
    assert not can_resume_adventure(image, load("elise"))


@pytest.mark.parametrize("bounds", [
    (1535, 965, 1560, 1000),  # 按钮文字被遮挡
    (78, 60, 120, 106),       # 页面返回键被遮挡
])
def test_resume_adventure_rejects_obscured_controls(bounds):
    image = _image("screens/f1-adventure-resume-20261114.png")
    x1, y1, x2, y2 = bounds
    image[y1:y2, x1:x2] = 0
    assert find_resume_adventure_button(image) is None
    assert not can_resume_adventure(image, load("jinx"))


def test_resume_adventure_rejects_dimmed_page():
    image = _image("screens/f1-adventure-resume-20261114.png")
    image = (image * 0.5).astype(np.uint8)
    assert find_resume_adventure_button(image) is None
    assert not can_resume_adventure(image, load("jinx"))


@pytest.mark.parametrize("damage", ["none", "shifted", "nameplate", "partial-name", "art"])
def test_resume_adventure_elise_synthetic_local_artwork(damage):
    # Synthetic local artwork substitution. The button and the visible nameplate
    # are inherited from the Jinx frame. No Elise resume screenshot is available.
    image = _image("screens/f1-adventure-resume-20261114.png")
    pack = load("elise")
    art = cv2.imread(str(pack.hero_item_art))
    assert art is not None
    anchor_x = 184 if damage == "shifted" else 154
    transform = np.float32([[0.68, 0, anchor_x - 0.68 * 119], [0, 0.68, 943 - 0.68 * 128]])
    crop = cv2.warpAffine(art, transform, (265, 1070))
    yy, xx = np.ogrid[:1070, :265]
    mask = ((xx - anchor_x + 4) / 75) ** 2 + ((yy - 952) / 62) ** 2 <= 1
    image[835:1070, 45:265] = 26
    image[:1070, :265][mask] = crop[mask]
    if damage == "nameplate":
        image[946:991, 320:485] = 0
    elif damage == "partial-name":
        image[953:989, 430:469] = 0
    elif damage == "art":
        image[885:1020, 65:240] = 0
    assert find_resume_adventure_button(image) is not None
    assert can_resume_adventure(image, pack) is (damage == "none")
    # 铭牌名字未被遮时写的是「吉茵珂絲」，名字模板即判 Jinx 匹配。
    assert can_resume_adventure(image, load("jinx")) is (
        damage not in ("nameplate", "partial-name"))


def test_resume_adventure_does_not_recognize_home_or_map():
    assert find_resume_adventure_button(_image("screens/1080p_home_adventure_entry.png")) is None
    assert find_resume_adventure_button(_image("mapnav/1080p_map.png")) is None


@pytest.mark.parametrize(("stars", "expected"), [
    ([2, 2, 1.5], 2), ([1.5, 2, 2], 0), ([2, 0.5, 1.5], 1),
    ([6.5, 6, 5.5], 2), ([], None),
    ([None, 2, 1.5], None), ([2, float("nan"), 1.5], None),
    ([0, 1.5, 2], None), ([7, 1.5, 2], None), ([1.2, 1.5, 2], None),
])
def test_pick_lowest_weekly(stars, expected):
    assert pick_lowest_weekly(stars, rng=random.Random(0)) == expected


def test_weekly_entry_requires_label_and_icon_and_moves_with_them():
    image = _image("screens/world-weekly-20261115.png")
    entry = find_weekly_entry(image)
    assert entry is not None
    assert abs(entry.center[0] - 1380) < 3
    assert abs(entry.center[1] - 465) < 3
    patch = image[410:520, 1180:1440].copy()
    image[410:520, 1180:1440] = 0
    image[510:620, 830:1090] = patch
    moved = find_weekly_entry(image)
    assert moved is not None
    assert moved.center == (entry.center[0] - 350, entry.center[1] + 100)


@pytest.mark.parametrize("bounds", [(1190, 450, 1302, 482), (1334, 420, 1427, 509)])
def test_weekly_entry_obscured_does_not_authorize_click(bounds):
    image = _image("screens/world-weekly-20261115.png")
    x1, y1, x2, y2 = bounds
    image[y1:y2, x1:x2] = 0
    assert find_weekly_entry(image) is None


@pytest.mark.parametrize("stars,choices", [([2, 2], {0, 1}), ([3, 2, 2], {1, 2}),
                                           ([2], {0})])
def test_weekly_randomizes_only_lowest_star_ties(stars, choices):
    picked = {pick_lowest_weekly(stars, rng=random.Random(seed)) for seed in range(20)}
    assert picked == choices


def test_weekly_two_remaining_candidates_and_two_star_detail():
    candidates = recognize_weekly_adventures(_image("screens/weekly-two-remaining-20261116.png"))
    assert candidates is not None and len(candidates) == 2
    assert [candidate.stars for candidate in candidates] == [2, 2]
    image = _image("screens/weekly-two-detail-20261116.png")
    assert weekly_detail_stars(image) == 2
    assert find_weekly_start(image) is not None
    assert find_weekly_start(image, replay=True) is None


def test_weekly_slot_targets_orders_incomplete_clock_list():
    # f1 实机停帧：三个周常全部未完成，只显示时钟。
    slots = weekly_slot_targets(_image("screens/f1-weekly-list-incomplete-20261121.png"))
    assert slots is not None and len(slots) == 3
    top, left, right = slots
    assert not any(slot.completed for slot in slots)
    assert top.target.y < min(left.target.y, right.target.y)
    assert left.target.x < top.target.x < right.target.x


def test_weekly_detail_replay_button_after_clock_slot_selection():
    # 时钟槽位进入的详情仍可显示「重玩冒險」（该槽本周已由其他英雄完成）。
    image = _image("screens/f1-weekly-detail-replay-from-clock-20261121.png")
    assert weekly_detail_stars(image) == 2.0
    assert find_weekly_start(image, replay=True) is not None
    assert find_weekly_start(image) is None


@pytest.mark.parametrize("name", [
    "f1-weekly-detail-open-on-resume-20261121.png",
    "weekly-detail-20261115.png",
    "f1-weekly-detail-replay-from-clock-20261121.png",
    "f1-weekly-list-panned-after-detail-20261121.png",
])
def test_world_back_button_finds_return_button(name):
    back = world_back_button(_image(f"screens/{name}"))
    assert back is not None and back.center[0] < 150 and back.center[1] < 120


def test_event_leave_option_finds_row_on_card_removal_event():
    # f1 实机停帧：卡剔除事件「獨身修女」，下方选项行「離開」。
    option = event_leave_option(
        _image("screens/f1-event-card-removal-20261121.png"))
    assert option is not None and option.center == (690, 949)


@pytest.mark.parametrize("name", [
    "healer/f1-abbey-heal-event-20261121.png",
    "mapnav/f1-shop-20261114.png",
    "mapnav/f1-spell-chest-panel-20261121.png",
    "screens/world-weekly-20261115.png",
    "screens/weekly-detail-20261115.png",
])
def test_event_leave_option_rejects_other_panels(name):
    # 商店/宝箱的同款离开行由其标题面板优先核验，不计为事件选项。
    assert event_leave_option(_image(name)) is None


def test_partial_weekly_view_recognizes_panned_list():
    # f1 实机停帧：详情返回后相机停在左侧，只剩两个时钟露出。
    assert partial_weekly_view(
        _image("screens/f1-weekly-list-panned-after-detail-20261121.png"))


@pytest.mark.parametrize("name", [
    "weekly-list-20261115.png", "f1-weekly-list-zoomed-20261121.png",
    "f1-weekly-list-incomplete-20261121.png", "weekly-detail-20261115.png",
    "weekly-two-detail-20261116.png",
    "f1-weekly-detail-open-on-resume-20261121.png",
    "f1-weekly-detail-replay-from-clock-20261121.png",
    "world-weekly-20261115.png",
])
def test_partial_weekly_view_rejects_full_and_other_weekly_scenes(name):
    assert not partial_weekly_view(_image(f"screens/{name}"))


@pytest.mark.parametrize("name", [
    "f1-weekly-detail-replay-from-clock-20261121.png",
    "f1-weekly-list-zoomed-20261121.png",
    "f1-weekly-list-incomplete-20261121.png",
])
def test_nameplate_name_recognizes_elise_not_jinx(name):
    image = _image(f"screens/{name}")
    assert selected_world_hero_matches(image, load("elise"))
    assert not selected_world_hero_matches(image, load("jinx"))


@pytest.mark.parametrize("name", [
    "weekly-detail-20261115.png", "weekly-two-detail-20261116.png",
    "weekly-list-20261115.png", "weekly-one-remaining.png",
    "weekly-two-remaining-20261116.png", "world-weekly-20261115.png",
])
def test_nameplate_name_rejects_elise_on_jinx_frames(name):
    image = _image(f"screens/{name}")
    assert not selected_world_hero_matches(image, load("elise"))
    assert selected_world_hero_matches(image, load("jinx"))


def test_weekly_slot_targets_recognizes_zoomed_dim_clock_variant():
    # f1 实机停帧：相机拉近后顶部时钟为更暗渲染变体，原模板只有 0.852。
    image = _image("screens/f1-weekly-list-zoomed-20261121.png")
    assert is_weekly_list(image)
    slots = weekly_slot_targets(image)
    assert slots is not None and not any(slot.completed for slot in slots)
    top, left, right = slots
    assert top.target.y < min(left.target.y, right.target.y)
    assert left.target.x < top.target.x < right.target.x
    # 顶部关卡肖像在时钟正下方的菱形内。
    assert 840 <= top.target.center[0] <= 930 and 290 <= top.target.center[1] <= 380


@pytest.mark.parametrize(("name", "targets"), [
    ("weekly-list-20261115.png",
     ((915, 168, 60, 50), (691, 531, 60, 50), (1236, 508, 60, 50))),
    ("f1-weekly-list-incomplete-20261121.png",
     ((906, 168, 60, 50), (677, 534, 60, 50), (1227, 510, 60, 50))),
])
def test_weekly_slot_targets_unchanged_on_existing_lists(name, targets):
    slots = weekly_slot_targets(_image(f"screens/{name}"))
    assert slots is not None
    assert [(slot.target.x, slot.target.y, slot.target.w, slot.target.h)
            for slot in slots] == list(targets)
    assert not any(slot.completed for slot in slots)


def test_weekly_slot_targets_marks_completed_and_matches_legacy_targets():
    image = _image("screens/weekly-one-remaining.png")
    marker = image[637:717, 665:745].copy()
    image[108:320, 850:1020] = 0
    image[150:230, 895:975] = marker
    slots = weekly_slot_targets(image)
    assert slots is not None and all(slot.completed for slot in slots)
    assert tuple(slot.target for slot in slots) == completed_weekly_targets(image)


def test_weekly_list_remains_recognizable_after_all_three_are_completed():
    image = _image("screens/weekly-one-remaining.png")
    marker = image[637:717, 665:745].copy()
    image[108:320, 850:1020] = 0
    assert not is_weekly_list(image)
    image[150:230, 895:975] = marker
    assert is_weekly_list(image)
    assert recognize_weekly_adventures(image) is None
    image[637:717, 665:745] = 0
    assert not is_weekly_list(image)


def test_weekly_remaining_candidate_with_different_completed_portraits():
    image = _image("screens/weekly-one-remaining.png")
    candidates = recognize_weekly_adventures(image)
    assert candidates is not None and len(candidates) == 1
    assert candidates[0].stars == 2
    assert abs(candidates[0].target.center[0] - 936) < 3


def test_weekly_last_candidate_needs_two_completed_markers():
    image = _image("screens/weekly-two-remaining-20261116.png")
    marker = image[614:694, 1215:1295].copy()
    image[108:320, 850:1020] = 0
    assert recognize_weekly_adventures(image) is None  # 时钟消失不能假定已完成。
    image[150:230, 895:975] = marker
    candidates = recognize_weekly_adventures(image)
    assert candidates is not None and len(candidates) == 1
    assert candidates[0].stars == 2


@pytest.mark.parametrize("bounds", [(1395, 116, 1543, 143), (1444, 340, 1487, 368)])
def test_two_star_detail_requires_visible_label_and_rating(bounds):
    image = _image("screens/weekly-two-detail-20261116.png")
    x1, y1, x2, y2 = bounds
    image[y1:y2, x1:x2] = 0
    assert weekly_detail_stars(image) is None
    assert find_weekly_start(image) is None


def test_weekly_list_reads_real_half_stars_at_dynamic_positions():
    candidates = recognize_weekly_adventures(_image("screens/weekly-list-20261115.png"))
    assert candidates is not None
    assert sorted(candidate.stars for candidate in candidates) == [1.5, 2, 2]
    lowest = candidates[pick_lowest_weekly([candidate.stars for candidate in candidates], rng=random.Random(0))]
    assert abs(lowest.target.center[0] - 1265) < 3
    assert abs(lowest.target.center[1] - 530) < 5


@pytest.mark.parametrize("lowest", [0, 1, 2])
def test_weekly_lowest_follows_badge_when_moved_to_another_node(lowest):
    image = _image("screens/weekly-list-20261115.png")
    boxes = [(894, 236), (670, 598), (1215, 576)]
    two = image[236:316, 894:995].copy()
    half = image[576:656, 1215:1316].copy()
    for index, (x, y) in enumerate(boxes):
        image[y:y + 80, x:x + 101] = half if index == lowest else two
    candidates = recognize_weekly_adventures(image)
    assert candidates is not None
    assert all(candidate.stars is not None for candidate in candidates)
    chosen = candidates[pick_lowest_weekly([candidate.stars for candidate in candidates], rng=random.Random(0))]
    x, y = boxes[lowest]
    assert abs(chosen.target.center[0] - (x + 50)) < 3
    assert abs(chosen.target.center[1] - (y - 43)) < 5


@pytest.mark.parametrize("bounds", [
    (933, 283, 956, 306),  # 未知/消失的 2
    (1258, 637, 1266, 646),  # 1.5 的小数点
    (1243, 623, 1287, 647),  # 整个 1.5
    (900, 240, 986, 279),  # 星标
])
def test_weekly_unknown_or_obscured_rating_abstains(bounds):
    image = _image("screens/weekly-list-20261115.png")
    x1, y1, x2, y2 = bounds
    image[y1:y2, x1:x2] = 0
    candidates = recognize_weekly_adventures(image)
    assert candidates is not None
    assert pick_lowest_weekly([candidate.stars for candidate in candidates], rng=random.Random(0)) is None


@pytest.mark.parametrize("name", [
    "world-weekly-20261115.png", "weekly-list-20261115.png",
    "weekly-detail-20261115.png", "weekly-start-animation-20261115.png",
])
def test_weekly_dimmed_and_animation_do_not_authorize_actions(name):
    image = _image("screens/" + name) // 2
    assert find_weekly_entry(image) is None
    assert recognize_weekly_adventures(image) is None
    assert find_weekly_start(image) is None


def test_weekly_detail_stars_and_start_match_real_frame():
    image = _image("screens/weekly-detail-20261115.png")
    assert weekly_detail_stars(image) == 1.5
    button = find_weekly_start(image)
    assert button is not None
    assert abs(button.center[0] - 1576) < 3 and abs(button.center[1] - 980) < 3
    assert recognize_weekly_adventures(image) is None


@pytest.mark.parametrize("bounds", [
    (1395, 116, 1543, 143), (1444, 340, 1487, 368), (1460, 357, 1466, 365),
    (1508, 963, 1645, 1000),
])
def test_weekly_detail_obscured_label_decimal_or_start_abstains(bounds):
    image = _image("screens/weekly-detail-20261115.png")
    x1, y1, x2, y2 = bounds
    image[y1:y2, x1:x2] = 0
    assert find_weekly_start(image) is None


@pytest.mark.parametrize("name", [
    "weekly-start-animation-20261115.png", "weekly-after-start-20261115.png",
    "1080p_home_adventure_entry.png", "f1-adventure-resume-20261114.png",
])
def test_weekly_does_not_authorize_other_scenes(name):
    image = _image("screens/" + name)
    assert find_weekly_entry(image) is None
    assert recognize_weekly_adventures(image) is None
    assert find_weekly_start(image) is None


@pytest.mark.parametrize("name", [
    "f1-world-cloud-occludes-weekly-20261121.png",
    "world-weekly-20261115.png",
])
def test_world_map_with_or_without_occluded_weekly_label(name):
    # 云遮与清晰可见「每週冒險」的世界地图都算世界视野。
    from lorwright.core.perceive.adventure_scene import is_world_map

    assert is_world_map(_image(f"screens/{name}"))


@pytest.mark.parametrize("name", [
    "mapnav/1080p_map.png",
    "mapnav/1080p_zoommax.png",
    "mapnav/1080p_jinx_map.png",
    "mapnav/f1-resumed-map-20261114.png",
    "mapnav/f1-boss-crest-map-20261120.png",
])
def test_adventure_maps_are_not_world_map(name):
    from lorwright.core.perceive.adventure_scene import is_world_map

    assert not is_world_map(_image(name))


def test_720p_adventure_map_is_not_world_map():
    from lorwright.core.perceive.adventure_scene import is_world_map
    from lorwright.core.perceive.normalize import Normalizer

    design = Normalizer((1920, 1080)).fit(_image("screens/720p_map.png"))[0]
    assert is_map(design)
    assert not is_world_map(design)
