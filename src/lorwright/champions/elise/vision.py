"""伊莉絲手牌身份识别：用卡面 ORB 特征匹配。

展开态手牌的卡片是完整卡面，和 Data Dragon 卡图只差缩放；ORB 对缩放/
轻微旋转不敏感，比整图模板匹配稳。模板放在 `assets/`，文件名是卡码
（`01SI002.png` 等），运行时按卡码映射到牌表中的中文名。

只在高置信度时写名字：匹配数不足、或第一名与第二名差距太小，都保留空名，
让策略退回“只按费用出牌”，不猜。
"""

from __future__ import annotations

from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from lorwright.models import CardInHand
from lorwright.perceive.hand import DRAG_OFFSET_EXPANDED

_ASSETS = Path(__file__).parent / "assets"

#: 卡码 → 牌表中文名（与 champions/elise/deck.py 一致）。
_CODE_TO_NAME = {
    "01SI002": "小蜘蛛",
    "06SI037": "闇影島泰爾石",
    "01SI053": "伊莉絲",
    "06NX013": "蜘術士",
    "01NX046": "蜘蛛哨兵",
    "01SI056": "發狂疾行蛛",
    "04NX016": "尖嘯蜘蛛",
    "01NX023": "群蛛之主",
    "01SI050": "傾巢而出",
}

_RATIO = 0.75
_MIN_GOOD = 20
_MIN_MARGIN = 10
_NFEATURES = 2000


@lru_cache(maxsize=1)
def _templates():
    orb = cv2.ORB_create(nfeatures=_NFEATURES)
    templates = []
    for path in sorted(_ASSETS.glob("*.png")):
        name = _CODE_TO_NAME.get(path.stem)
        if name is None:
            continue
        image = cv2.imread(str(path))
        if image is None:
            continue
        keypoints, descriptors = orb.detectAndCompute(
            cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), None
        )
        if descriptors is not None:
            templates.append((name, descriptors))
    return orb, cv2.BFMatcher(cv2.NORM_HAMMING), templates


def _good_matches(matcher, query, train) -> int:
    pairs = matcher.knnMatch(query, train, k=2)
    return sum(1 for first, second in pairs if first.distance < _RATIO * second.distance)


def recognize_hand(image: np.ndarray, cards: list[CardInHand]) -> list[CardInHand]:
    """给展开态手牌补名字；低置信度卡片保留空名。"""
    orb, matcher, templates = _templates()
    if not templates:
        return cards

    result = []
    for card in cards:
        cx, cy = card.rect.center
        x0 = max(0, cx - DRAG_OFFSET_EXPANDED[0] - 6)
        y0 = max(0, cy - DRAG_OFFSET_EXPANDED[1] - 40)
        crop = image[y0 : min(image.shape[0], y0 + 330), x0 : min(image.shape[1], x0 + 290)]
        if crop.size == 0:
            result.append(card)
            continue
        keypoints, descriptors = orb.detectAndCompute(
            cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), None
        )
        if descriptors is None:
            result.append(card)
            continue

        scores = sorted(
            ((_good_matches(matcher, descriptors, train), name) for name, train in templates),
            reverse=True,
        )
        best_score, best_name = scores[0]
        second_score = scores[1][0] if len(scores) > 1 else 0
        if best_score >= _MIN_GOOD and best_score - second_score >= _MIN_MARGIN:
            result.append(replace(card, name=best_name))
        else:
            result.append(card)
    return result


__all__ = ["recognize_hand"]
