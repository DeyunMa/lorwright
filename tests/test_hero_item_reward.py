"""英雄道具奖励页面识别，不依赖英雄、道具或生命值内容。"""

from pathlib import Path

import cv2
import pytest

from lorwright.core.perceive.reward_screen import (
    hero_item_choose_disabled,
    hero_item_choose_enabled,
    hero_item_hero_selection,
    hero_item_item_selection,
    is_hero_item_reward_screen,
    recognize_hero_item_cards,
    recognize_hero_items,
)

FIXTURES = Path(__file__).parent / "fixtures"


def short_title_reward():
    import numpy as np

    image = np.zeros((1080, 1920, 3), np.uint8)
    image[18:1050, 450:1470] = cv2.imread(str(
        FIXTURES / "hero_item_reward" / "f1-short-title-20261117.png"
    ))
    return image


def test_two_character_item_name_does_not_block_known_hero_and_quality():
    image = short_title_reward()
    assert recognize_hero_item_cards(image) == ("", "jinx")
    assert hero_item_hero_selection(image) == -1
    assert hero_item_item_selection(image) == -1
    items = recognize_hero_items(image)
    assert items is not None
    assert [(item.name, item.quality) for item in items] == [
        ("", "rare"), ("", "common"), ("吸血鬼權杖", "rare"),
    ]


@pytest.mark.parametrize("damage", ["missing", "dimmed", "one_character", "short_strokes"])
def test_short_item_name_requires_two_visible_characters(damage):
    image = short_title_reward()
    if damage == "missing":
        image[700:726, 906:1036] = 0
    elif damage == "dimmed":
        image[700:726, 906:1036] //= 3
    elif damage == "one_character":
        image[700:726, 925:1036] = 0
    else:
        image[700:726, 906:1036] = 0
        image[710:713, 909:923] = 255
        image[710:713, 926:940] = 255
    assert recognize_hero_items(image) is None


def test_main_hero_and_item_quality_survive_other_unknown_identities():
    from random import Random

    from lorwright.core.champions import load
    from lorwright.core.decide.rewards import pick_hero_item_reward

    image = cv2.imread(str(FIXTURES / "hero_item_reward" / "f1-weekly-reksai-20261116.png"))
    assert recognize_hero_item_cards(image) == ("jinx", "")
    assert hero_item_hero_selection(image) == -1
    items = recognize_hero_items(image)
    assert items is not None
    assert items[1].name == "吸血鬼權杖"
    assert items[2].name == "" and items[2].quality == "epic"
    pick = pick_hero_item_reward(items, load("jinx").item_preferences, Random(1))
    assert pick is not None and pick.candidate is items[2]


def test_real_unknown_item_preserves_visible_known_items():
    image = cv2.imread(str(FIXTURES / "hero_item_reward" / "f1-weekly-reksai-20261116.png"))
    items = recognize_hero_items(image)
    assert items is not None
    assert [item.name for item in items] == ["鑽探衝鋒", "吸血鬼權杖", ""]


@pytest.mark.parametrize("region", [
    (275, 455, 680, 875),  # 主英雄插画
    (700, 726, 563, 693),
    (700, 726, 906, 1036),
    (700, 726, 1249, 1379),
    (725, 744, 1249, 1329),
    (690, 816, 1157, 1161),
])
def test_unknown_candidates_do_not_relax_visibility_checks(region):
    image = cv2.imread(str(FIXTURES / "hero_item_reward" / "f1-weekly-reksai-20261116.png"))
    y1, y2, x1, x2 = region
    image[y1:y2, x1:x2] = 0
    if y1 == 275:
        assert recognize_hero_item_cards(image) is None
    else:
        assert recognize_hero_items(image) is None


def test_hero_item_reward_with_variable_content():
    image = cv2.imread(str(FIXTURES / "hero_item_reward" / "f1-20261115.png"))
    assert is_hero_item_reward_screen(image)
    image[220:955, 450:1470] = 0
    assert is_hero_item_reward_screen(image)


@pytest.mark.parametrize("region", [(18, 110, 760, 1160), (125, 195, 450, 1460)])
def test_obscured_title_or_subtitle_is_not_recognized(region):
    image = cv2.imread(str(FIXTURES / "hero_item_reward" / "f1-20261115.png"))
    y1, y2, x1, x2 = region
    image[y1:y2, x1:x2] = 0
    assert not is_hero_item_reward_screen(image)


def test_recognize_hero_item_cards_and_reject_missing_identity():
    image = cv2.imread(str(FIXTURES / "hero_item_reward" / "f1-20261115.png"))
    assert recognize_hero_item_cards(image) == ("jinx", "elise")
    image[275:455, 1020:1210] = 0
    assert recognize_hero_item_cards(image) is None


def test_hero_highlight_and_items_on_real_frames():
    before = cv2.imread(str(FIXTURES / "hero_item_reward" / "before-sample.png"))
    selected = cv2.imread(str(FIXTURES / "hero_item_reward" / "jinx-selected.png"))
    assert hero_item_hero_selection(before) == -1
    assert hero_item_hero_selection(selected) == 0
    assert [(c.name, c.quality) for c in recognize_hero_items(selected)] == [
        ("吸血鬼權杖", "rare"), ("鑽探衝鋒", "rare"), ("軍隊長劍", "common")
    ]
    selected[245:625, 642:646] = 0
    assert hero_item_hero_selection(selected) is None
    before[700:745, 906:1036] = 0
    assert recognize_hero_items(before) is None


def test_item_selection_and_enabled_button_real_and_ambiguous():
    folder = FIXTURES / "hero_item_reward"
    before = cv2.imread(str(folder / "jinx-selected.png"))
    selected = cv2.imread(str(folder / "both-selected.png"))
    assert hero_item_item_selection(before) == -1
    assert not hero_item_choose_enabled(before)
    assert hero_item_item_selection(selected) == 0
    assert hero_item_choose_enabled(selected)
    obscured = selected.copy()
    obscured[690:816, 471:475] = 0
    assert hero_item_item_selection(obscured) is None
    ambiguous = selected.copy()
    ambiguous[690:816, 815:819] = selected[690:816, 471:475]
    assert hero_item_item_selection(ambiguous) is None
    selected[975:1030, 815:1105] = 0
    assert not hero_item_choose_enabled(selected)


def test_sampling_requires_disabled_button():
    image = cv2.imread(str(FIXTURES / "hero_item_reward" / "f1-20261115.png"))
    assert hero_item_choose_disabled(image)
    image[975:1030, 815:1105] = (0, 180, 220)
    assert not hero_item_choose_disabled(image)


def test_hero_cards_on_other_screen_are_rejected():
    image = cv2.imread(str(FIXTURES / "hero_item_reward" / "f1-20261115.png"))
    image[18:110, 760:1160] = 0
    assert recognize_hero_item_cards(image) is None


def test_dimmed_and_other_reward_screens_are_not_recognized():
    image = cv2.imread(str(FIXTURES / "hero_item_reward" / "f1-20261115.png"))
    assert not is_hero_item_reward_screen(image // 2)
    other = cv2.imread(str(FIXTURES / "card_rewards" / "before.png"))
    assert not is_hero_item_reward_screen(other)
