"""两张起手牌的展开态局部模板；不确定时保留空名称。"""

from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np

from lorwright.models import CardInHand
from lorwright.perceive.hand import DRAG_OFFSET_EXPANDED

_ASSETS = Path(__file__).parent / "assets"
_NAMES = {"jinx.png": "吉茵珂絲", "jury_rig.png": "應急裝置"}
_MIN_SCORE = 0.90


def recognize_hand(image: np.ndarray, cards: list[CardInHand]) -> list[CardInHand]:
    templates = {name: cv2.imread(str(_ASSETS / filename)) for filename, name in _NAMES.items()}
    result = []
    for card in cards:
        x, y = card.rect.center
        x -= DRAG_OFFSET_EXPANDED[0]
        y -= DRAG_OFFSET_EXPANDED[1]
        region = image[max(0, y):min(image.shape[0], y + 180),
                       max(0, x - 12):min(image.shape[1], x + 155)]
        scores = []
        for name, template in templates.items():
            if template is None or region.shape[0] < template.shape[0] or region.shape[1] < template.shape[1]:
                continue
            score = cv2.minMaxLoc(cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED))[1]
            if score >= _MIN_SCORE:
                scores.append((score, name))
        result.append(replace(card, name=scores[0][1]) if len(scores) == 1 else card)
    return result
