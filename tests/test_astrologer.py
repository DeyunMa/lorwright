"""占星家实拍、购买排序和未知证据保护；扣款帧为合成。"""

from pathlib import Path

import cv2
import pytest

from lorwright.core.decide.adventure import pick_affordable_power
from lorwright.core.decide.rewards import RewardCandidate
from lorwright.core.perceive.astrologer import (
    astrologer_buy_button,
    astrologer_gold,
    astrologer_map_gold,
    astrologer_offers,
    astrologer_selection,
    is_power_vendor,
    same_astrologer_offers,
)


def image():
    result = cv2.imread(str(Path(__file__).parent / "fixtures/screens/f1-astrologer-20261116.png"))
    assert result is not None
    return result


def test_soloist_reuses_paid_power_offer_contract():
    frame = cv2.imread(str(Path(__file__).parent / "fixtures/screens/f1-soloist-20261116.png"))
    assert frame is not None
    offers = astrologer_offers(frame)
    assert offers is not None
    assert [(c.quality, c.cost) for c in offers] == [("rare", 300), ("rare", 300), ("epic", 400)]
    assert astrologer_gold(frame) == 1070
    assert pick_affordable_power(offers, 1070) == 2
    assert astrologer_selection(frame) == -1
    assert astrologer_buy_button(frame) is None
    assert is_power_vendor(frame)


@pytest.mark.parametrize("damage", ["title", "leave", "balance", "quality", "price"])
def test_soloist_missing_evidence_does_not_authorize_purchase(damage):
    frame = cv2.imread(str(Path(__file__).parent / "fixtures/screens/f1-soloist-20261116.png"))
    if damage == "title":
        frame[350:425, 560:850] = 0
    elif damage == "leave":
        frame[910:990, 630:755] = 0
    elif damage == "balance":
        frame[977:1029, 1064:1204] = 0
    elif damage == "quality":
        frame[503:529, 1629:1899] = 0
    else:
        frame[700:734, 1759:1814] = 0
    assert astrologer_gold(frame) is None or astrologer_offers(frame) is None
    assert astrologer_buy_button(frame) is None


def test_real_astrologer_reads_prices_gold_and_unknown_power_qualities():
    frame = image()
    assert is_power_vendor(frame)
    assert astrologer_gold(frame) == 950
    offers = astrologer_offers(frame)
    assert offers is not None
    assert [(c.quality, c.cost) for c in offers] == [("common", 200), ("rare", 300), ("epic", 400)]
    assert pick_affordable_power(offers, 950) == 2
    assert astrologer_selection(frame) == -1
    assert astrologer_buy_button(frame) is None


@pytest.mark.parametrize("gold,expected", [(950, 2), (400, 2), (399, 1), (300, 1),
                                           (299, 0), (199, None)])
def test_purchase_requires_affordability_before_quality(gold, expected):
    offers = [RewardCandidate("", q, c) for q, c in [("common", 200), ("rare", 300), ("epic", 400)]]
    assert pick_affordable_power(offers, gold) == expected


def test_equal_quality_prefers_cheaper_without_hero_preferences():
    offers = [RewardCandidate("", "epic", 400), RewardCandidate("", "epic", 300)]
    assert pick_affordable_power(offers, 950) == 1
    assert pick_affordable_power([RewardCandidate("", "unknown", 200)], 950) is None
    assert pick_affordable_power([RewardCandidate("", "epic", None)], 950) is None


@pytest.mark.parametrize("region", [(469, 503, 1629, 1899), (503, 529, 1629, 1899),
                                    (280, 390, 1709, 1819), (700, 734, 1759, 1814)])
def test_obscured_astrologer_offer_is_not_a_purchase_candidate(region):
    frame = image()
    y1, y2, x1, x2 = region
    frame[y1:y2, x1:x2] = 0
    assert astrologer_offers(frame) is None


def test_obscured_balance_cannot_reuse_previous_value():
    frame = image()
    assert astrologer_gold(frame) == 950
    frame[977:1029, 1064:1204] = 0
    assert astrologer_gold(frame) is None


def test_real_selected_astrologer_preserves_offers_and_enables_purchase():
    selected = cv2.imread(str(Path(__file__).parent / "fixtures/screens/f1-astrologer-selected-20261116.png"))
    assert selected is not None
    assert astrologer_selection(selected) == 2
    assert astrologer_gold(selected) == 950
    assert same_astrologer_offers(image(), selected)
    assert astrologer_buy_button(selected) is not None


def test_soloist_purchased_map_reads_exact_balance():
    frame = cv2.imread(str(Path(__file__).parent / "fixtures/screens/f1-soloist-purchased-map-20261116.jpg"))
    assert frame is not None
    assert astrologer_map_gold(frame) == 670
    for left, right in [(483, 497), (500, 513), (516, 530)]:
        obscured = frame.copy()
        obscured[1010:1034, left:right] = 0
        assert astrologer_map_gold(obscured) != 670


def test_real_purchased_map_reads_exact_balance_and_rejects_obscured_digits():
    frame = cv2.imread(str(Path(__file__).parent / "fixtures/screens/f1-astrologer-purchased-map-20261116.png"))
    assert frame is not None
    assert astrologer_map_gold(frame) == 550
    assert astrologer_map_gold(selected_frame()) is None
    assert astrologer_map_gold(cv2.resize(frame, (1280, 720))) is None
    for left, right in [(483, 496), (500, 512), (516, 528)]:
        obscured = frame.copy()
        obscured[1012:1031, left:right] = 0
        assert astrologer_map_gold(obscured) != 550
    frame[1003:1038, 477:542] = 0
    assert astrologer_map_gold(frame) is None


def selected_frame():
    frame = cv2.imread(str(Path(__file__).parent / "fixtures/screens/f1-astrologer-selected-20261116.png"))
    assert frame is not None
    return frame


def paid_frame():
    frame = selected_frame()
    five = frame[984:1023, 1099:1125].copy()
    frame[984:1023, 1068:1094] = five
    return frame


@pytest.mark.parametrize("damage", ["left", "right", "multiple"])
def test_real_selection_requires_both_edges_and_one_selected_slot(damage):
    frame = selected_frame()
    if damage == "left":
        frame[300:680, 1629:1632] = 0
    elif damage == "right":
        frame[300:680, 1896:1899] = 0
    else:
        frame[300:680, 985:988] = 240
        frame[300:680, 1252:1255] = 240
    assert astrologer_selection(frame) is None


def test_real_selection_and_synthetic_exact_balance_change():
    before = image()
    selected = selected_frame()
    assert astrologer_selection(selected) == 2
    assert same_astrologer_offers(before, selected)
    assert astrologer_buy_button(selected) is not None
    assert astrologer_gold(paid_frame()) == 550
    changed = selected.copy()
    changed[280:390, 1709:1819] = 128
    assert not same_astrologer_offers(before, changed)
