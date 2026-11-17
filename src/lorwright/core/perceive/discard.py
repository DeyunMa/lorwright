"""识别弃牌选择中的可点击卡面；坐标基于归一化的 1080p 画面。"""

import cv2
import numpy as np

from lorwright.core.models import DiscardCandidates, Rect
from lorwright.core.perceive.digits import DigitReader
from lorwright.core.perceive.hand import read_cost_glyphs


def discard_candidates(frame: np.ndarray, digits: DigitReader) -> DiscardCandidates | None:
    if frame.shape != (1080, 1920, 3):
        return None
    region = frame[500:750, 70:1800]
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    circles = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, 1, 150,
                               param1=100, param2=36, minRadius=27, maxRadius=42)
    if circles is None:
        return None
    anchors = sorted((int(round(x + 70)), int(round(y + 500)))
                     for x, y, _ in circles[0])
    if not 1 <= len(anchors) <= 5:
        return None
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    blue = cv2.inRange(hsv, (90, 140, 160), (115, 255, 255))
    cards, artwork, costs = [], [], []
    for x, y in anchors:
        # 费用圆标左侧需有可选卡牌的蓝色边框；图像和点击点均在牌内。
        if x < 65 or x + 215 >= frame.shape[1] or y + 190 >= 1050:
            return None
        border = blue[y - 35:y + 105, x - 65:x - 30]
        if cv2.countNonZero(border) < 100:
            return None
        art = frame[y + 15:y + 165, x + 42:x + 207]
        if art.shape != (150, 165, 3):
            return None
        cards.append(Rect(x + 80, y + 65, 50, 50))
        artwork.append(cv2.resize(art, (80, 80)))
        glyphs = read_cost_glyphs(frame, (x, y), rad=26)
        hit = digits.classify_sequence(
            glyphs, rotations=(-15, -10, -5, 0, 5, 10, 15),
        ) if glyphs is not None else None
        costs.append(hit[0] if hit is not None and hit[1] >= 0.85 else None)
    matches = [[_artwork_match(a, b) for b in artwork] for a in artwork]
    scores = tuple(tuple(min(matches[i][j], matches[j][i]) for j in range(len(artwork)))
                   for i in range(len(artwork)))
    return DiscardCandidates(tuple(cards), scores, tuple(costs))


def _artwork_match(source: np.ndarray, target: np.ndarray) -> float:
    """扇形卡面允许小角度与位移，中央插画须双向吻合才能视为重复牌。"""
    best = -1.0
    for angle in range(-15, 16, 3):
        rotated = cv2.warpAffine(source, cv2.getRotationMatrix2D((40, 40), angle, 1), (80, 80))
        score = cv2.matchTemplate(target, rotated[8:72, 8:72], cv2.TM_CCOEFF_NORMED)
        best = max(best, float(score.max()))
    return best
