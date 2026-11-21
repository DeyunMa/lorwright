"""识别弃牌选择中的可点击卡面；坐标基于归一化的 1080p 画面。"""

import cv2
import numpy as np

from lorwright.core.models import DiscardCandidates, Rect
from lorwright.core.perceive.digits import DigitReader
from lorwright.core.perceive.hand import read_cost_glyphs

#: 费用单字的最低分与对第二名数字的最低领先幅度，见 `_read_cost`。
_COST_MIN_SCORE = 0.80
_COST_MIN_MARGIN = 0.15


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
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    blue = cv2.inRange(hsv, (90, 140, 160), (115, 255, 255))
    cards, artwork, costs = [], [], []
    for x, y in anchors:
        # 证据不足的锚点直接丢弃：Hough 会把卡面装饰（如砰砰的关键字徽记）
        # 当成圆；被屏幕边缘裁掉的卡牌费用圆也可能只露出半边。丢弃只收窄
        # 可选范围，点击始终落在已验证的完整候选上，不会点到错误的牌。
        if x < 65 or x + 215 >= frame.shape[1] or y + 190 >= 1050:
            continue
        border = blue[y - 35:y + 105, x - 65:x - 30]
        if cv2.countNonZero(border) < 100:
            continue
        art = frame[y + 15:y + 165, x + 42:x + 207]
        if art.shape != (150, 165, 3):
            continue
        # 费用圆内必然含数字笔画；关键字徽记之类的伪圆提取不出字模，
        # 同理丢弃。数字在但分类不到置信阈的锚点保留，交给 choose_discard
        # 的“费用未知则不动”规则兜底。
        glyphs = read_cost_glyphs(frame, (x, y), rad=26, ignore_perimeter_highlights=True)
        if glyphs is None:
            continue
        cards.append(Rect(x + 80, y + 65, 50, 50))
        artwork.append(cv2.resize(art, (80, 80)))
        costs.append(_read_cost(digits, glyphs))
    if not 1 <= len(cards) <= 5:
        return None
    matches = [[_artwork_match(a, b) for b in artwork] for a in artwork]
    scores = tuple(tuple(min(matches[i][j], matches[j][i]) for j in range(len(artwork)))
                   for i in range(len(artwork)))
    return DiscardCandidates(tuple(cards), scores, tuple(costs))


def _read_cost(digits: DigitReader, glyphs: list[np.ndarray]) -> int | None:
    """每位须明确是某个数字：分数过下限，且领先其他数字足够多。

    弃牌徽章比手牌大（字高约 30px 对 20px），现有原型多采自手牌字号，
    清晰字形的绝对分随数字与倾斜在 0.84~1.0 间浮动（如 2 在 0.842/0.864
    间跳），单一 0.85 绝对阈让同一画面时读时不读。真实字形领先第二名
    均 ≥0.19，被遮挡的残字领先 <0.1，故按领先幅度判定，并保留下限。
    """
    value = ""
    for glyph in glyphs:
        ranked = digits.rank(glyph, rotations=(-15, -10, -5, 0, 5, 10, 15))
        if not ranked or not 0 <= ranked[0][0] <= 9:
            return None
        runner_up = ranked[1][1] if len(ranked) > 1 else -1.0
        if ranked[0][1] < _COST_MIN_SCORE or ranked[0][1] - runner_up < _COST_MIN_MARGIN:
            return None
        value += str(ranked[0][0])
    return int(value) if value else None


def _artwork_match(source: np.ndarray, target: np.ndarray) -> float:
    """扇形卡面允许小角度与位移，中央插画须双向吻合才能视为重复牌。"""
    best = -1.0
    for angle in range(-15, 16, 3):
        rotated = cv2.warpAffine(source, cv2.getRotationMatrix2D((40, 40), angle, 1), (80, 80))
        score = cv2.matchTemplate(target, rotated[8:72, 8:72], cv2.TM_CCOEFF_NORMED)
        best = max(best, float(score.max()))
    return best
