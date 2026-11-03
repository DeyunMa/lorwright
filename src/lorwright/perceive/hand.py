"""手牌识别：右下角扇形手牌 → 卡槽 + 费用。

手机版手牌收起来是一把扇形，每张卡左上角有个圆形费用徽章。徽章是固定图案
的圆环，所以用「只保留圆环」的掩膜做模板匹配：真实徽章得分 0.97~1.0，
误报 ≤0.96。手牌展开成大图后徽章尺度不同（58px vs 48px），这个模板不再匹配
—— 正好可以拿来区分「收起 / 展开」两种状态。

费用数字在徽章圆心里，随卡片倾斜旋转 -20°~0°，所以读数要带角度搜索。
数字抠图要先按圆盘掩膜去掉徽章高光和描边，否则 2 会被高光粘成 1。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from lorwright.models import CardInHand, Rect
from lorwright.perceive.digits import DigitReader, normalize_glyph

__all__ = ["Badge", "find_badges", "read_cost", "recognize"]

#: 收起态徽章模板（48×48，采自 1920×1080 截图）
BADGE_TEMPLATE = Path("assets/ui/badge.png")
#: 低于这个分数就当地址上没徽章（实测误报上限 0.956）
BADGE_MIN_SCORE = 0.96
#: 非极大值抑制半径：徽章直径约 48px，取 45 够去重
BADGE_MIN_DIST = 45

#: 抠费用字形的半边长。徽章半径 24，取 15 只覆盖中间的数字区
_GLYPH_RAD = 15
#: 字形随卡片倾斜的角度搜索范围（度）
_ROTATIONS = tuple(range(-28, 29, 3))
#: 拖拽起点相对徽章中心的偏移：徽章在卡片左上角，卡身朝右下
DRAG_OFFSET = (15, 45)


@dataclass(frozen=True)
class Badge:
    """手牌里的一个费用徽章。"""

    center: tuple[int, int]
    score: float


def _ring_mask(size: int) -> np.ndarray:
    """只保留圆环的掩膜。圆环位置对得上就得分高，环内图案（数字）不参与。"""
    yy, xx = np.mgrid[0:size, 0:size]
    r = np.hypot(yy - size / 2 + 0.5, xx - size / 2 + 0.5)
    return (((r > size * 0.31) & (r < size * 0.48)) * 255).astype(np.uint8)


def find_badges(
    image: np.ndarray,
    region: Rect,
    template: str | Path = BADGE_TEMPLATE,
    threshold: float = BADGE_MIN_SCORE,
) -> list[Badge]:
    """在手牌区域里找费用徽章，按从左到右排序（= 手牌序号）。"""
    tpl = cv2.imread(str(template), cv2.IMREAD_GRAYSCALE)
    if tpl is None:
        return []

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    sub = gray[region.y : region.y + region.h, region.x : region.x + region.w]
    h, w = tpl.shape
    if sub.shape[0] < h or sub.shape[1] < w:
        return []

    res = cv2.matchTemplate(sub, tpl, cv2.TM_CCORR_NORMED, mask=_ring_mask(h))
    found: list[Badge] = []
    while True:
        _, score, _, loc = cv2.minMaxLoc(res)
        if score < threshold:
            break
        found.append(
            Badge(
                center=(region.x + loc[0] + w // 2, region.y + loc[1] + h // 2),
                score=float(score),
            )
        )
        cv2.circle(res, loc, BADGE_MIN_DIST, 0, -1)   # 抑制邻近重复

    return sorted(found, key=lambda b: b.center[0])


def read_glyph(image: np.ndarray, center: tuple[int, int], rad: int = _GLYPH_RAD):
    """从徽章圆心抠出费用字形，返回归一化后的 0..1 图（认不出返回 None）。

    用 `max(axis=2)` 而不是灰度：0 费（减费高亮）是绿字，灰度会把它压暗。
    """
    cx, cy = center
    v = image.max(axis=2)
    patch = v[cy - rad : cy + rad, cx - rad : cx + rad]
    if patch.shape != (rad * 2, rad * 2):
        return None

    yy, xx = np.mgrid[0 : rad * 2, 0 : rad * 2]
    c = rad - 0.5
    disc = np.hypot(xx - c, yy - c) <= rad - 2

    # 只在圆盘内部做 Otsu：把环和外面的卡面排除掉
    thr, _ = cv2.threshold(
        patch[disc].reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    binary = np.zeros_like(patch)
    binary[disc] = (patch[disc] >= thr) * 255

    # 开运算断开「徽章高光」和数字之间的粘连（2 会被粘出一条尾巴）
    binary = cv2.morphologyEx(binary.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

    count, _, stats, cent = cv2.connectedComponentsWithStats(binary, 8)
    best: tuple[float, int, int, int, int] | None = None
    for i in range(1, count):
        x, y, w, h, area = (int(stats[i, k]) for k in range(5))
        # 数字又高又窄；高光是小圆点（高 < 12）
        if area < 30 or w < 5 or h < 12:
            continue
        dist = float(np.hypot(cent[i][0] - c, cent[i][1] - c))
        if best is None or dist < best[0]:
            best = (dist, x, y, w, h)
    if best is None:
        return None
    dist, x, y, w, h = best
    if dist > rad * 0.7:      # 离圆心太远 = 不是数字
        return None
    return normalize_glyph(binary[y : y + h, x : x + w])


def read_cost(
    image: np.ndarray, badge: Badge, digits: DigitReader, rad: int = _GLYPH_RAD
) -> int | None:
    """读徽章里的费用。读不出返回 None（不猜）。"""
    glyph = read_glyph(image, badge.center, rad)
    if glyph is None:
        return None
    hit = digits.classify(glyph, rotations=_ROTATIONS)
    return None if hit is None else hit[0]


def recognize(
    image: np.ndarray,
    region: Rect,
    digits: DigitReader,
    threshold: float = BADGE_MIN_SCORE,
) -> list[CardInHand]:
    """识别收起态手牌。费用读不出来的卡 `cost=-1`，策略层会跳过它。"""
    cards: list[CardInHand] = []
    for index, badge in enumerate(find_badges(image, region, threshold=threshold)):
        cx, cy = badge.center
        dx, dy = DRAG_OFFSET
        cost = read_cost(image, badge, digits)
        cards.append(
            CardInHand(
                index=index,
                name="",
                cost=-1 if cost is None else cost,
                # 拖拽起点：徽章右下方的卡身（徽章本身在卡片左上角）
                rect=Rect(cx + dx - 4, cy + dy - 4, 8, 8),
            )
        )
    return cards
