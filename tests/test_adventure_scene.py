"""地图控件在真实画面及遮挡时的识别回归。"""

import random

import cv2
import numpy as np
import pytest

from lorwright.core.champions import load
from lorwright.core.decide.adventure import pick_lowest_weekly
from lorwright.core.perceive.adventure_scene import (
    can_resume_adventure,
    find_resume_adventure_button,
    find_weekly_entry,
    find_weekly_start,
    is_map,
    is_weekly_list,
    recognize_weekly_adventures,
    weekly_detail_stars,
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
    assert not can_resume_adventure(image, load("jinx"))


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
