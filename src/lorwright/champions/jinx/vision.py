"""Jinx 手牌身份：9 张卡面 ORB 匹配 + 费用约束。

卡面模板来自 Data Dragon（01PZ*）和 PoC AssetBundle（99PZ*），
放在 `assets/<code>.png`。低置信度或费用对不上时保留空名。
"""

from __future__ import annotations

from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from lorwright.champions.jinx.deck import BY_CODE
from lorwright.models import CardInHand, Rect
from lorwright.perceive.hand import DRAG_OFFSET_EXPANDED

_ASSETS = Path(__file__).parent / "assets"
_RATIO = 0.75
_MIN_GOOD = 60
_MIN_MARGIN = 20
_NFEATURES = 2000
_HERO_NFEATURES = 8000
_HERO_TEMPLATE = _ASSETS / "hero_portrait.png"

#: 起手换牌界面的 4 个「替換」按钮中心（1920×1080 实测）。
MULLIGAN_REPLACE_POINTS = ((438, 820), (756, 820), (1068, 817), (1386, 817))
#: 每个按钮上方的卡面区域：宽 320、高 340。
_MULLIGAN_CARD_SIZE = (320, 340)


@lru_cache(maxsize=1)
def _templates():
    orb = cv2.ORB_create(nfeatures=_NFEATURES)
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    templates = []
    for path in sorted(_ASSETS.glob("*.png")):
        card = BY_CODE.get(path.stem)
        if card is None:
            continue
        image = cv2.imread(str(path))
        if image is None:
            continue
        _, descriptors = orb.detectAndCompute(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), None)
        if descriptors is not None:
            templates.append((card, descriptors))
    return orb, matcher, templates


def _good_matches(matcher, query, train) -> int:
    pairs = matcher.knnMatch(query, train, k=2)
    return sum(1 for first, second in pairs if first.distance < _RATIO * second.distance)


def recognize_hand(image: np.ndarray, cards: list[CardInHand]) -> list[CardInHand]:
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
        _, descriptors = orb.detectAndCompute(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), None)
        if descriptors is None:
            result.append(card)
            continue

        # 费用是强约束，但 PoC 道具会把任意牌减费（实测砰砰 2→1），
        # 所以只排除「显示费用高于卡牌基础费用」的候选；减费牌仍然参与
        # ORB 打分。此前只给英雄牌开口子，导致 1 费砰砰被误认成 Jinx。
        candidates = [
            (definition, train)
            for definition, train in templates
            if card.cost < 0
            or definition.cost >= card.cost
        ]
        scores = sorted(
            ((_good_matches(matcher, descriptors, train), definition) for definition, train in candidates),
            key=lambda item: item[0],
            reverse=True,
        )
        if not scores:
            result.append(card)
            continue
        best_score, best = scores[0]
        second_score = scores[1][0] if len(scores) > 1 else 0
        if best_score >= _MIN_GOOD and best_score - second_score >= _MIN_MARGIN:
            result.append(replace(card, name=best.name))
        else:
            result.append(card)
    return result


@lru_cache(maxsize=1)
def _hero_template():
    orb = cv2.ORB_create(nfeatures=_HERO_NFEATURES)
    template = cv2.imread(str(_HERO_TEMPLATE))
    if template is None:
        return None, None, None
    keypoints, descriptors = orb.detectAndCompute(
        cv2.cvtColor(template, cv2.COLOR_BGR2GRAY), None
    )
    return orb, keypoints, descriptors


def recognize_hero(image: np.ndarray) -> tuple[int, int] | None:
    """地图上的 Jinx 头像：ORB 匹配模板，返回头像中心。"""
    orb, template_keypoints, template_descriptors = _hero_template()
    if template_descriptors is None:
        return None
    # 左下固定状态栏也有 Jinx 头像；只搜索地图区域，不能把它当当前位置。
    x0, y0 = 240, 60
    map_area = image[y0:min(image.shape[0], 820), x0:min(image.shape[1], 1750)]
    if map_area.size == 0:
        return None
    keypoints, descriptors = orb.detectAndCompute(
        cv2.cvtColor(map_area, cv2.COLOR_BGR2GRAY), None
    )
    if descriptors is None:
        return None
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    pairs = matcher.knnMatch(template_descriptors, descriptors, k=2)
    good = [first for first, second in pairs if first.distance < _RATIO * second.distance]
    if len(good) < 12:
        return None
    # 模板左上角 = 匹配点平移的中位数；中心再加模板半宽/半高。
    dx = np.median([keypoints[g.trainIdx].pt[0] - template_keypoints[g.queryIdx].pt[0]
                    for g in good])
    dy = np.median([keypoints[g.trainIdx].pt[1] - template_keypoints[g.queryIdx].pt[1]
                    for g in good])
    template = cv2.imread(str(_HERO_TEMPLATE))
    if template is None:
        return None
    height, width = template.shape[:2]
    return (int(round(x0 + dx + width / 2)), int(round(y0 + dy + height / 2)))


def recognize_mulligan(image: np.ndarray) -> list[CardInHand]:
    """起手换牌界面：识别 4 张牌，rect 指向对应的「替換」按钮。"""
    orb, matcher, templates = _templates()
    if not templates:
        return []
    cards: list[CardInHand] = []
    width, height = _MULLIGAN_CARD_SIZE
    for index, (bx, by) in enumerate(MULLIGAN_REPLACE_POINTS):
        x0 = max(0, bx - width // 2)
        y0 = max(0, by - height - 40)
        crop = image[y0 : min(image.shape[0], y0 + height), x0 : min(image.shape[1], x0 + width)]
        if crop.size == 0:
            cards.append(CardInHand(index, "", -1, Rect(bx - 4, by - 4, 8, 8)))
            continue
        _, descriptors = orb.detectAndCompute(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), None)
        name = ""
        if descriptors is not None:
            scores = sorted(
                ((_good_matches(matcher, descriptors, train), card.name) for card, train in templates),
                reverse=True,
            )
            if scores and scores[0][0] >= _MIN_GOOD:
                best = scores[0][0]
                second = scores[1][0] if len(scores) > 1 else 0
                if best - second >= _MIN_MARGIN:
                    name = scores[0][1]
        cards.append(CardInHand(index, name, -1, Rect(bx - 4, by - 4, 8, 8)))
    return cards


__all__ = ["recognize_hand", "recognize_hero", "recognize_mulligan"]
