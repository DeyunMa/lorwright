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
from lorwright.perceive.digits import DigitReader, normalize_glyph, rotate_glyph

__all__ = [
    "Badge",
    "find_badges",
    "find_badges_expanded",
    "read_cost",
    "recognize",
    "recognize_expanded",
]

#: 收起态徽章模板（48×48，采自 1920×1080 截图）
BADGE_TEMPLATE = Path("assets/ui/badge.png")
#: 低于这个分数就当地址上没徽章（实测误报上限 0.956）
BADGE_MIN_SCORE = 0.96
#: 非极大值抑制半径：徽章直径约 48px，取 45 够去重
BADGE_MIN_DIST = 45

#: 展开态徽章模板（56×56）。展开后卡片放大，徽章从 48px 变 56px，
#: 收起态模板匹配不上——这正好用来区分两种状态，别试图用缩放凑。
BADGE_EXPANDED_TEMPLATE = Path("assets/ui/badge_expanded.png")
#: 展开态实测：真徽章 ≥0.977，唯一误报 0.937
EXPANDED_MIN_SCORE = 0.96
#: 展开态卡间距 222~242px，抑制半径取 120 不会吃掉邻卡
EXPANDED_MIN_DIST = 120

#: 抠费用字形的半边长。徽章半径 24，数字高约 20px，取 16 够且不碰外环
_GLYPH_RAD = 16
#: 白字判据：三通道都不低于它才算「白」（蓝底 ~(20,60,140)，青环缺 R 通道）
_WHITE_MIN = 170
#: 0 费卡的数字是**绿色**的（R/B 都很低），白字判据抠不出来，单独认一路
_GREEN_MIN = 180
_GREEN_MAX_RB = 120
#: 字形已按主轴扶正，只剩估算误差，小范围搜索就够
_ROTATIONS = tuple(range(-8, 9, 2))
#: 拖拽起点相对徽章中心的偏移：徽章在卡片左上角，卡身朝右下
DRAG_OFFSET = (15, 45)
#: 展开态拖拽起点：卡片平铺、不重叠，徽章右侧就是卡身中部
DRAG_OFFSET_EXPANDED = (64, 10)


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
    # 空白区域分母为零会得到 NaN/Inf；NaN < threshold 为 False，会造出假徽章。
    np.nan_to_num(res, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
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


def _tilt(glyph: np.ndarray) -> float:
    """字形主轴相对竖直方向的倾角（度）。手牌是扇形，每张卡倾斜角度不同。"""
    m = cv2.moments((glyph * 255).astype(np.uint8), binaryImage=False)
    if m["mu20"] + m["mu02"] < 1e-6:
        return 0.0
    ang = 0.5 * np.degrees(np.arctan2(2 * m["mu11"], m["mu20"] - m["mu02"]))
    # 主轴角以 180° 为周期，且数字是竖长的：主轴接近 ±90°，真正要的是
    # 「相对竖直的倾角」。折回 (-45, 45] 就是它——手牌扇形倾斜不会超过 ±45°。
    # 直接返回主轴角（75~90°）会让字形被转躺下，同数字的不同倾斜样本还会
    # 转到不同方向（86° vs 94°），匹配全靠模板碰巧同向，非常脆。
    return (ang + 45.0) % 90.0 - 45.0


def read_glyph(image: np.ndarray, center: tuple[int, int], rad: int = _GLYPH_RAD):
    """从徽章圆心抠出费用字形，返回归一化并扶正的 0..1 图（认不出返回 None）。

    判白字用 `min(R,G,B)` 而不是灰度或 max：徽章底是蓝色、外环是青色，
    两者都「某个通道很亮」，只有数字是三个通道都亮。用灰度/最大值会在
    1080p 把青色环一起框进来，和数字粘成一块（字形直接读废）。
    """
    cx, cy = center
    patch = image[cy - rad : cy + rad, cx - rad : cx + rad]
    if patch.shape[:2] != (rad * 2, rad * 2):
        return None

    blue, green, red = patch[:, :, 0], patch[:, :, 1], patch[:, :, 2]
    lit = (patch.min(axis=2) >= _WHITE_MIN) | (
        (green >= _GREEN_MIN) & (red <= _GREEN_MAX_RB) & (blue <= _GREEN_MAX_RB)
    )
    white = lit.astype(np.uint8) * 255
    yy, xx = np.mgrid[0 : rad * 2, 0 : rad * 2]
    c = rad - 0.5
    white[np.hypot(xx - c, yy - c) > rad - 2] = 0   # 只留圆盘内部，排除外环

    count, _, stats, _ = cv2.connectedComponentsWithStats(white, 8)
    boxes = [
        (int(stats[i, 4]), int(stats[i, 0]), int(stats[i, 1]), int(stats[i, 2]), int(stats[i, 3]))
        for i in range(1, count)
        if stats[i, 4] >= 20
    ]
    if not boxes:
        return None
    _, x, y, w, h = max(boxes)          # 数字是盘内最大的一块白
    if h < 10 or w > h * 1.4:           # 太扁 = 高光碎片，不是数字
        return None

    glyph = normalize_glyph(white[y : y + h, x : x + w])
    return rotate_glyph(glyph, _tilt(glyph))


def read_cost(
    image: np.ndarray, badge: Badge, digits: DigitReader, rad: int = _GLYPH_RAD
) -> int | None:
    """读徽章里的费用。读不出返回 None（不猜）。"""
    glyph = read_glyph(image, badge.center, rad)
    if glyph is None:
        return None
    hit = digits.classify(glyph, rotations=_ROTATIONS)
    return None if hit is None else hit[0]


def find_badges_expanded(
    image: np.ndarray,
    region: Rect,
    template: str | Path = BADGE_EXPANDED_TEMPLATE,
    threshold: float = EXPANDED_MIN_SCORE,
) -> list[Badge]:
    """在展开态手牌区域里找徽章，按从左到右排序。

    展开态必须单独一套模板：卡片放大后徽章 56px，收起态的 48px 模板完全
    匹配不上（实测最高 0.90，全是误报）。
    """
    tpl = cv2.imread(str(template), cv2.IMREAD_GRAYSCALE)
    if tpl is None:
        return []

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    sub = gray[region.y : region.y + region.h, region.x : region.x + region.w]
    h, w = tpl.shape
    if sub.shape[0] < h or sub.shape[1] < w:
        return []

    res = cv2.matchTemplate(sub, tpl, cv2.TM_CCORR_NORMED, mask=_ring_mask(h))
    np.nan_to_num(res, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
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
        cv2.circle(res, loc, EXPANDED_MIN_DIST, 0, -1)

    return sorted(found, key=lambda b: b.center[0])


def recognize_expanded(
    image: np.ndarray,
    region: Rect,
    digits: DigitReader,
    threshold: float = EXPANDED_MIN_SCORE,
) -> list[CardInHand]:
    """识别展开态手牌（卡片平铺在屏幕下方）。"""
    cards: list[CardInHand] = []
    for index, badge in enumerate(find_badges_expanded(image, region, threshold=threshold)):
        cx, cy = badge.center
        dx, dy = DRAG_OFFSET_EXPANDED
        cost = read_cost(image, badge, digits)
        cards.append(
            CardInHand(
                index=index,
                name="",
                cost=-1 if cost is None else cost,
                rect=Rect(cx + dx - 4, cy + dy - 4, 8, 8),
            )
        )
    return cards


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
