"""伊莉絲手牌身份识别：真实 1080p 展开态截图与邻牌防借名回归。"""

from pathlib import Path

import cv2
import numpy as np

from lorwright.core.champions.elise.vision import recognize_hand
from lorwright.core.models import CardInHand, Rect
from lorwright.core.perceive.digits import DigitReader
from lorwright.core.perceive.hand import DRAG_OFFSET_EXPANDED, recognize_expanded


def test_recognizes_all_six_cards_in_real_expanded_hand():
    image = cv2.imread(str(Path("tests/fixtures/screens/1080p_hand_expanded.png")))
    assert image is not None
    digits = DigitReader()
    digits.load()
    cards = recognize_expanded(image, Rect(200, 700, 1600, 380), digits)
    assert [card.cost for card in cards] == [1, 4, 3, 3, 2, 0]

    named = recognize_hand(image, cards)
    assert [(card.index, card.name, card.cost) for card in named] == [
        (0, "小蜘蛛", 1),
        (1, "尖嘯蜘蛛", 4),
        (2, "蜘蛛哨兵", 3),
        (3, "發狂疾行蛛", 3),
        (4, "伊莉絲", 2),
        (5, "闇影島泰爾石", 0),
    ]


def test_occluded_slot_does_not_borrow_adjacent_card_identity():
    """裁剪窗口包含右侧邻牌时，未知/被遮挡卡面必须保留空名，不能借用邻牌身份。"""
    image = cv2.imread(str(Path("tests/fixtures/screens/1080p_hand_expanded.png")))
    assert image is not None
    digits = DigitReader()
    digits.load()
    cards = recognize_expanded(image, Rect(200, 700, 1600, 380), digits)

    for target_slot in (2, 4):
        occluded = image.copy()
        cx, _ = cards[target_slot].rect.center
        bx = cx - DRAG_OFFSET_EXPANDED[0]
        occluded[780:1080, bx - 10 : bx + 170] = 40
        named = recognize_hand(occluded, cards)
        assert named[target_slot].name == ""
        assert named[target_slot + 1].name != ""


def test_blank_frame_keeps_names_empty():
    blank = np.zeros((1080, 1920, 3), dtype=np.uint8)
    cards = [CardInHand(index=0, name="", cost=1, rect=Rect(500, 900, 8, 8))]
    assert recognize_hand(blank, cards)[0].name == ""
