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

from lorwright.core.champions.jinx.deck import BY_CODE
from lorwright.core.models import CardInHand, MulliganCard, Rect, TargetedSpell, Unit
from lorwright.core.perceive.hand import DRAG_OFFSET_EXPANDED
from lorwright.core.perceive.mulligan import MULLIGAN_REPLACE_POINTS

_ASSETS = Path(__file__).parent / "assets"
HERO_ITEM_ART = _ASSETS / "01PZ040.png"
_RATIO = 0.75
_MIN_GOOD = 60
_MIN_MARGIN = 20
_NFEATURES = 2000
_HERO_NFEATURES = 8000
_HERO_TEMPLATE = _ASSETS / "hero_portrait.png"
# 完整卡图的费用徽章中心为 (32, 34)；纯卡面/裁图锚点由已有实拍投影标定。
_HAND_BADGE_ANCHORS = {
    "99PZ104": (385, 17),
    "99PZ130": (-7, 33),
    "01PZ040T1": (18, 47),
}

@lru_cache(maxsize=1)
def _targeted_spell_template():
    return cv2.imread(str(_ASSETS / "pow_pow_target.png"))


def recognize_targeted_spell(image: np.ndarray) -> TargetedSpell | None:
    """仅在标定区域内匹配清晰的砰砰图标。"""
    template = _targeted_spell_template()
    if template is None:
        return None
    region = image[480:600, 900:1020]
    if region.shape[0] < template.shape[0] or region.shape[1] < template.shape[1]:
        return None
    scores = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, (x, y) = cv2.minMaxLoc(scores)
    if score < 0.95:
        return None
    return TargetedSpell("砰砰", Rect(900 + x, 480 + y, template.shape[1], template.shape[0]))


@lru_cache(maxsize=1)
def _board_template():
    return cv2.imread(str(_ASSETS / "board_leveled.png"))


def recognize_my_units(image: np.ndarray, units: list[Unit]) -> list[Unit]:
    """仅在已检出单位的卡身内确认升级 Jinx，不从全屏借用邻牌。"""
    template = _board_template()
    if template is None:
        return units
    result = []
    for unit in units:
        x, y = unit.rect.center
        # 单位 rect 为攻击徽章中心加 (40, 55) 的拖点；卡面位于其下方。
        x0, y0 = max(0, x - 65), max(0, y - 25)
        crop = image[y0:min(image.shape[0], y + 65), x0:min(image.shape[1], x + 55)]
        if crop.shape[0] >= template.shape[0] and crop.shape[1] >= template.shape[1]:
            _, score, _, _ = cv2.minMaxLoc(
                cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED),
            )
            if score < 0.95:
                # 动态光效可能覆盖一个象限；其余四分之三须在同一位置匹配，
                # 不把各处零散卡面拼成身份，也不降低原相关门槛。
                h, w = template.shape[:2]
                for row in range(2):
                    for col in range(2):
                        mask = np.ones((h, w), np.uint8)
                        mask[row * h // 2:(row + 1) * h // 2,
                             col * w // 2:(col + 1) * w // 2] = 0
                        local = cv2.matchTemplate(
                            crop, template, cv2.TM_CCOEFF_NORMED, mask=mask,
                        )
                        finite = local[np.isfinite(local)]
                        if finite.size:
                            score = max(score, float(finite.max()))
            if score >= 0.95:
                unit = replace(unit, name="吉茵珂絲")
        result.append(unit)
    return result


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
        points, descriptors = orb.detectAndCompute(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), None)
        if descriptors is not None:
            templates.append((card, points, descriptors))
    return orb, matcher, templates


def _good_matches(matcher, query, train, query_points, train_points, badge, anchor) -> int:
    pairs = matcher.knnMatch(query, train, k=2)
    good = [pair[0] for pair in pairs
            if len(pair) == 2 and pair[0].distance < _RATIO * pair[1].distance]
    if len(good) < 30:
        return 0
    source = np.float32([train_points[match.trainIdx].pt for match in good])
    target = np.float32([query_points[match.queryIdx].pt for match in good])
    transform, inliers = cv2.findHomography(source, target, cv2.RANSAC, 3.0)
    count = int(inliers.sum()) if inliers is not None else 0
    if transform is None or count < 30:
        return 0
    projected = cv2.perspectiveTransform(np.float32([[anchor]]), transform)[0, 0]
    # 卡面必须投影到本牌徽章附近，不能借用裁剪区域内的邻牌身份。
    if not np.isfinite(projected).all() or np.linalg.norm(projected - badge) > 36:
        return 0
    return len(good)


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


@lru_cache(maxsize=1)
def _other_mulligan_templates():
    """已登记的其他卡面可提供非目标身份的正向证据。"""
    orb = cv2.ORB_create(nfeatures=_NFEATURES)
    templates = []
    for path in sorted(Path("assets/mulligan/cards").glob("*.png")):
        if path.stem == "01PZ040":
            continue
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if image is not None:
            points, descriptors = orb.detectAndCompute(image, None)
            if descriptors is not None:
                templates.append((points, descriptors))
    return templates


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
        points, descriptors = orb.detectAndCompute(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), None)
        if descriptors is None:
            result.append(card)
            continue

        # 费用是强约束，但 PoC 道具会把任意牌减费（实测砰砰 2→1），
        # 减费牌仍然参与 ORB 打分。应急装置也可能被增费至 3 费，
        # 必须参与比较，否则可能被误认成其他 3 费牌。
        # 此前只给英雄牌开口子，导致 1 费砰砰被误认成 Jinx。
        candidates = [
            (definition, train_points, train)
            for definition, train_points, train in templates
            if card.cost < 0
            or definition.cost >= card.cost
            or (definition.code == "01PZ028" and card.cost <= 3)
        ]
        badge = np.float32((cx - DRAG_OFFSET_EXPANDED[0] - x0,
                            cy - DRAG_OFFSET_EXPANDED[1] - y0))
        scores = sorted(
            ((_good_matches(matcher, descriptors, train, points, train_points, badge,
                            _HAND_BADGE_ANCHORS.get(definition.code, (32, 34))), definition)
             for definition, train_points, train in candidates),
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


@lru_cache(maxsize=1)
def _selected_name_template():
    return cv2.imread(str(_ASSETS / "selected_name.png"), cv2.IMREAD_GRAYSCALE)


def recognize_selected_hero(image: np.ndarray) -> bool:
    """冒险选择页只有明确显示金克丝名字时才认可英雄匹配。"""
    template = _selected_name_template()
    if image.shape != (1080, 1920, 3) or template is None:
        return False
    region = cv2.cvtColor(image[930:1005, 300:520], cv2.COLOR_BGR2GRAY)
    scores = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, (x, y) = cv2.minMaxLoc(scores)
    if score < 0.92:
        return False
    h, w = template.shape
    white = template >= 200
    return bool(white.any() and float(region[y:y + h, x:x + w][white].mean()) >= 170)


def recognize_hero(image: np.ndarray) -> tuple[int, int] | None:
    """地图上的 Jinx 头像：ORB 匹配模板，返回头像中心。"""
    orb, template_keypoints, template_descriptors = _hero_template()
    if template_descriptors is None:
        return None
    # 左下固定状态栏也有 Jinx 头像；只搜索地图区域，不能把它当当前位置。
    x0, y0 = 240, 0
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
    from lorwright.core.perceive.mulligan import recognize_mulligan_selection

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
                    # 明显不匹配 Jinx 的卡面可直接判为非目标；边界情况或明显的
                    # 英雄品质标志仍保留未知，避免把难以分辨的英雄误判成可替换牌。
                    cx = (486, 802, 1118, 1434)[index]
                    gem = image[726:743, cx - 11:cx + 11]
                    hsv = cv2.cvtColor(gem, cv2.COLOR_BGR2HSV)
                    green = cv2.inRange(hsv, (35, 65, 80), (90, 255, 255))
                    blue = cv2.inRange(hsv, (90, 60, 100), (130, 255, 255))
                    gold = cv2.inRange(hsv, (15, 80, 80), (35, 255, 255))
                    if len(good) < 20:
                        if cv2.countNonZero(gold) < 150:
                            result = False
                        else:
                            for other_points, other_descriptors in _other_mulligan_templates():
                                pairs = matcher.knnMatch(descriptors, other_descriptors, k=2)
                                matches = [pair[0] for pair in pairs if len(pair) == 2
                                           and pair[0].distance < _RATIO * pair[1].distance]
                                if len(matches) < 45:
                                    continue
                                source = np.float32([other_points[m.trainIdx].pt for m in matches])
                                target = np.float32([keypoints[m.queryIdx].pt for m in matches])
                                _, inliers = cv2.findHomography(source, target, cv2.RANSAC, 3.0)
                                count = int(inliers.sum()) if inliers is not None else 0
                                if count >= 30 and count / len(matches) >= 0.7:
                                    result = False
                                    break
                    elif max(cv2.countNonZero(green), cv2.countNonZero(blue)) >= 100:
                        result = False
        cards.append(MulliganCard(index, result, Rect(bx - 4, by - 4, 8, 8)))
    return cards


__all__ = ["recognize_hand", "recognize_hero", "recognize_mulligan"]
