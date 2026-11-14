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
from lorwright.models import CardInHand, MulliganCard, Rect
from lorwright.perceive.hand import DRAG_OFFSET_EXPANDED
from lorwright.perceive.mulligan import MULLIGAN_REPLACE_POINTS

_ASSETS = Path(__file__).parent / "assets"
_RATIO = 0.75
_MIN_GOOD = 60
_MIN_MARGIN = 20
_NFEATURES = 2000
_HERO_NFEATURES = 8000
_HERO_TEMPLATE = _ASSETS / "hero_portrait.png"

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


@lru_cache(maxsize=1)
def _mulligan_templates():
    """换牌只需匹配目标 Jinx，不维护其他牌的名称库。"""
    orb = cv2.ORB_create(nfeatures=_NFEATURES)
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    image = cv2.imread(str(_ASSETS / "01PZ040.png"))
    if image is None:
        return orb, matcher, None, None
    keypoints, descriptors = orb.detectAndCompute(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), None)
    return orb, matcher, keypoints, descriptors


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
        # 减费牌仍然参与 ORB 打分。应急装置也可能被增费至 3 费，
        # 必须参与比较，否则可能被误认成其他 3 费牌。
        # 此前只给英雄牌开口子，导致 1 费砰砰被误认成 Jinx。
        candidates = [
            (definition, train)
            for definition, train in templates
            if card.cost < 0
            or definition.cost >= card.cost
            or (definition.code == "01PZ028" and card.cost <= 3)
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


def recognize_mulligan(image: np.ndarray) -> list[MulliganCard]:
    """判断各槽是否为 Jinx；画面不完整或匹配模糊时保持未知。

    非目标判断依赖可见的非英雄品质标志，不需要辨认其他牌名；
    其他英雄无法可靠区分时保持未知。
    已选中的紫色特效遮挡卡面，不能用这一帧判断身份。
    """
    if image.shape != (1080, 1920, 3):
        return []
    from lorwright.perceive.mulligan import recognize_mulligan_selection

    orb, matcher, target_points, target_descriptors = _mulligan_templates()
    selected = recognize_mulligan_selection(image)
    cards: list[MulliganCard] = []
    for index, (bx, by) in enumerate(MULLIGAN_REPLACE_POINTS):
        x0 = bx - 94
        crop = image[330:560, x0:x0 + 284]
        result: bool | None = None
        if (selected[index] is False and target_descriptors is not None
                and target_points is not None and crop.shape == (230, 284, 3)):
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            # 检查卡面多个区域的纹理，拒绝整块遮挡；不能仅凭
            # 「没匹配到 Jinx」就把缺失的牌当作其他牌。
            interior = gray[10:220, 19:259]
            visible = all(
                float(interior[y:y + 70, x:x + 80].std()) >= 12
                for y in (0, 70, 140) for x in (0, 80, 160)
            )
            keypoints, descriptors = orb.detectAndCompute(gray, None)
            if visible and descriptors is not None and len(keypoints) >= 250:
                pairs = matcher.knnMatch(descriptors, target_descriptors, k=2)
                good = [pair[0] for pair in pairs
                        if len(pair) == 2 and pair[0].distance < _RATIO * pair[1].distance]
                if len(good) >= 45:
                    source = np.float32([target_points[match.trainIdx].pt for match in good])
                    target = np.float32([keypoints[match.queryIdx].pt for match in good])
                    _, inliers = cv2.findHomography(source, target, cv2.RANSAC, 3.0)
                    count = int(inliers.sum()) if inliers is not None else 0
                    if count >= 30 and count / len(good) >= 0.7:
                        result = True
                else:
                    # 不能把「没匹配到 Jinx」直接当成非 Jinx。实图中的
                    # 绿色/蓝色品质标志可提供独立反证；
                    # 金色英雄标志及看不清的标志不能排除 Jinx。
                    cx = (486, 802, 1118, 1434)[index]
                    gem = image[726:743, cx - 11:cx + 11]
                    hsv = cv2.cvtColor(gem, cv2.COLOR_BGR2HSV)
                    green = cv2.inRange(hsv, (35, 65, 80), (90, 255, 255))
                    blue = cv2.inRange(hsv, (90, 60, 100), (130, 255, 255))
                    if max(cv2.countNonZero(green), cv2.countNonZero(blue)) >= 100:
                        result = False
        cards.append(MulliganCard(index, result, Rect(bx - 4, by - 4, 8, 8)))
    return cards


__all__ = ["recognize_hand", "recognize_hero", "recognize_mulligan"]
