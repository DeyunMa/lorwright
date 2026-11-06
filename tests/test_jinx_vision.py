from pathlib import Path

import cv2
import numpy as np
import pytest

from lorwright.champions.jinx.vision import recognize_hand
from lorwright.models import Rect
from lorwright.perceive.digits import DigitReader
from lorwright.perceive.hand import recognize_expanded


@pytest.mark.parametrize(("filename", "expected"), [
    ("battle-hand.png", [(4, "吉茵珂絲", 4), (5, "應急裝置", 1)]),
    ("battle-expand2.png", [(3, "吉茵珂絲", 2), (4, "應急裝置", 1)]),
])
def test_recognizes_cards_in_real_expanded_hands(filename, expected):
    region = cv2.imread(str(Path("tests/fixtures/jinx") / filename))
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    image[700:1080, 200:1800] = region
    digits = DigitReader()
    digits.load()
    cards = recognize_expanded(image, Rect(200, 700, 1600, 380), digits)
    actual = [(card.index, card.name, card.cost) for card in recognize_hand(image, cards)
              if card.name]
    assert actual == expected
