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

__all__ = ["Badge", "find_badges", "read_cost", "recognize"]

#: 收起态徽章模板（48×48，采自 1920×1080 截图）
BADGE_TEMPLATE = Path("assets/ui/badge.png")
#: 低于这个分数就当地址上没徽章（实测误报上限 0.956）
BADGE_MIN_SCORE = 0.96
#: 非极大值抑制半径：徽章直径约 48px，取 45 够去重
BADGE_MIN_DIST = 45

#: 抠费用字形的半边长。徽章半径 24，数字高约 20px，取 16 够且不碰外环
_GLYPH_RAD = 16
#: 白字判据：三通道都不低于它才算「白」（蓝底 ~(20,60,140)，青环缺 R 通道）
_WHITE_MIN = 170
#: 字形已按主轴扶正，只剩估算误差，小范围搜索就够
_ROTATIONS = tuple(range(-8, 9, 2))
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


def _tilt(glyph: np.ndarray) -> float:
    """字形主轴相对竖直方向的倾角（度）。手牌是扇形，每张卡倾斜角度不同。"""
    m = cv2.moments((glyph * 255).astype(np.uint8), binaryImage=False)
    if m["mu20"] + m["mu02"] < 1e-6:
        return 0.0
    ang = 0.5 * np.degrees(np.arctan2(2 * m["mu11"], m["mu20"] - m["mu02"]))
    # 数字是竖长的：主轴偏向 x 轴时说明差了 90°，转回来
    return ang if m["mu20"] < m["mu02"] else ang - 90.0


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

    white = (patch.min(axis=2) >= _WHITE_MIN).astype(np.uint8) * 255
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
