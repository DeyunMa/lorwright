"""伊莉絲手牌身份识别：卡面 ORB 特征 + RANSAC 单应内点 + 本牌费用徽章几何归属。

展开态手牌裁剪框宽 290px，会覆盖右侧相邻手牌的左侧卡面；仅统计原始 knnMatch 数量
会让未知新卡借用邻牌身份。这里与 Jinx 手牌识别一致，要求单应矩阵内点充分且模板费用
徽章锚点 `(32, 34)` 投影到本槽实际费用徽章附近，不满足一律保留空名。
"""

from __future__ import annotations

from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from lorwright.core.models import CardInHand
from lorwright.core.perceive.hand import DRAG_OFFSET_EXPANDED

_ASSETS = Path(__file__).parent / "assets"
HERO_ITEM_ART = _ASSETS / "01SI053.png"
WORLD_NAMEPLATE_NAME = _ASSETS / "world_nameplate_name.png"

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
_MIN_GOOD = 60
_MIN_INLIERS = 30
_MIN_MARGIN = 20
_NFEATURES = 2000
_BADGE_ANCHOR = (32.0, 34.0)
_MAX_BADGE_DIST = 36.0


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
            templates.append((name, keypoints, descriptors))
    return orb, cv2.BFMatcher(cv2.NORM_HAMMING), templates


def _good_matches(
    matcher,
    query: np.ndarray,
    train: np.ndarray,
    query_points,
    train_points,
    badge: np.ndarray,
) -> int:
    pairs = matcher.knnMatch(query, train, k=2)
    good = [
        pair[0]
        for pair in pairs
        if len(pair) == 2 and pair[0].distance < _RATIO * pair[1].distance
    ]
    if len(good) < _MIN_INLIERS:
        return 0
    source = np.float32([train_points[match.trainIdx].pt for match in good])
    target = np.float32([query_points[match.queryIdx].pt for match in good])
    transform, inliers = cv2.findHomography(source, target, cv2.RANSAC, 3.0)
    count = int(inliers.sum()) if inliers is not None else 0
    if transform is None or count < _MIN_INLIERS:
        return 0
    projected = cv2.perspectiveTransform(np.float32([[_BADGE_ANCHOR]]), transform)[0, 0]
    if not np.isfinite(projected).all() or float(np.linalg.norm(projected - badge)) > _MAX_BADGE_DIST:
        return 0
    return len(good)


def recognize_hand(image: np.ndarray, cards: list[CardInHand]) -> list[CardInHand]:
    """给展开态手牌补名字；几何不归属本牌或低置信度卡片保留空名。"""
    orb, matcher, templates = _templates()
    if not templates:
        return cards

    result = []
    for card in cards:
        cx, cy = card.rect.center
        bx_full = cx - DRAG_OFFSET_EXPANDED[0]
        by_full = cy - DRAG_OFFSET_EXPANDED[1]
        x0 = max(0, bx_full - 6)
        y0 = max(0, by_full - 40)
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

        badge = np.float32((bx_full - x0, by_full - y0))
        scores = sorted(
            (
                (
                    _good_matches(matcher, descriptors, train, keypoints, train_points, badge),
                    name,
                )
                for name, train_points, train in templates
            ),
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
