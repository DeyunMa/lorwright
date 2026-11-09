"""伊莉絲手牌身份识别：真实 1080p 展开态截图回归。"""

from pathlib import Path

import cv2
import numpy as np

from lorwright.champions.elise.vision import recognize_hand
from lorwright.models import CardInHand, Rect
from lorwright.perceive.digits import DigitReader
from lorwright.perceive.hand import recognize_expanded


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


def test_blank_frame_keeps_names_empty():
    blank = np.zeros((1080, 1920, 3), dtype=np.uint8)
    cards = [CardInHand(index=0, name="", cost=1, rect=Rect(500, 900, 8, 8))]
    assert recognize_hand(blank, cards)[0].name == ""
