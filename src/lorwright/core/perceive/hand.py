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
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from lorwright.core.models import CardInHand, Rect
from lorwright.core.perceive.digits import DigitReader, normalize_glyph, rotate_glyph

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
#: 展开态主体徽章阈值；边缘卡另结合相邻卡间距及可读费用检查。
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
#: 弃牌页高亮下绿色数字混入徽章蓝光（B≈125），按绿明显高于蓝放宽蓝通道。
_GREEN_MAX_B = 175
_GREEN_OVER_B = 50
#: 费用增加时数字会变红，背景蓝色徽章不能混入笔画。
_RED_MIN = 160
_RED_MAX_GB = 110
#: 字形已按主轴扶正，只剩估算误差，小范围搜索就够
_ROTATIONS = tuple(range(-8, 9, 2))
#: 拖拽起点相对徽章中心的偏移：徽章在卡片左上角，卡身朝右下
DRAG_OFFSET = (15, 45)
#: 展开态卡面识别锚点，保留供英雄卡面识别使用。
DRAG_OFFSET_EXPANDED = (64, 10)
#: 展开态出牌实验点：徽章下方的可见卡身，尚待实机验证。
_EXPANDED_DRAG_BODY_OFFSET = (64, 105)

# 已确认空手的卡玛棋盘两帧；左侧包含场上单位的动态效果。
EMPTY_HAND_TEMPLATES = (Path("assets/ui/empty_hand_karma.png"),
                        Path("assets/ui/empty_hand_karma_2.png"))
EMPTY_HAND_REGION = Rect(1420, 855, 500, 225)


@lru_cache(maxsize=4)
def _load_empty_hand_templates(paths: tuple[str, ...]) -> tuple[np.ndarray | None, ...]:
    return tuple(cv2.imread(path) for path in paths)


@lru_cache(maxsize=8)
def _load_gray_template(path: str) -> np.ndarray | None:
    return cv2.imread(path, cv2.IMREAD_GRAYSCALE)


def is_confirmed_empty(image: np.ndarray, region: Rect) -> bool:
    """匹配已知空手背景；未知棋盘或明显遮挡均保守返回 False。"""
    if image.shape[:2] != (1080, 1920) or region != EMPTY_HAND_REGION:
        return False
    templates = _load_empty_hand_templates(tuple(str(path) for path in EMPTY_HAND_TEMPLATES))
    sample = image[region.y:region.y + region.h, region.x:region.x + region.w]
    if any(template is None or template.shape != sample.shape for template in templates):
        return False
    # 两帧间的单位动画只在最左侧；每像素取最近参考，允许中间帧。
    diff = np.minimum(*(np.max(cv2.absdiff(sample, template), axis=2)
                        for template in templates))
    for row in np.array_split(diff, 5, axis=0):
        for index, block in enumerate(np.array_split(row, 10, axis=1)):
            limit = 45 if index == 0 else 25
            if block.mean() > (8 if index == 0 else 5) or np.max(block) > limit:
                return False
    return True


@dataclass(frozen=True)
class Badge:
    """手牌里的一个费用徽章。"""

    center: tuple[int, int]
    score: float


@lru_cache(maxsize=8)
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
    tpl = _load_gray_template(str(template))
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


def read_cost_glyphs(
    image: np.ndarray, center: tuple[int, int], rad: int = _GLYPH_RAD,
    *, ignore_perimeter_highlights: bool = False,
) -> list[np.ndarray] | None:
    """从徽章抠出完整费用序列，逐字归一化并扶正；异常组件不能丢成个位。

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
        (green >= _GREEN_MIN) & (red <= _GREEN_MAX_RB)
        & ((blue <= _GREEN_MAX_RB)
           | ((blue <= _GREEN_MAX_B) & (green.astype(np.int16) - blue >= _GREEN_OVER_B)))
    ) | (
        (red >= _RED_MIN) & (green <= _RED_MAX_GB) & (blue <= _RED_MAX_GB)
    )
    white = lit.astype(np.uint8) * 255
    yy, xx = np.mgrid[0 : rad * 2, 0 : rad * 2]
    c = rad - 0.5
    white[np.hypot(xx - c, yy - c) > rad - 2] = 0   # 只留圆盘内部，排除外环

    count, labels, stats, _ = cv2.connectedComponentsWithStats(white, 8)
    # 核心残笔虽不足以提取完整字形，也不能丢掉后报成个位；边缘描边另排除。
    core = labels[np.hypot(xx - c, yy - c) <= rad * 0.7]
    if any(12 <= stats[i, cv2.CC_STAT_AREA] < 20 and np.count_nonzero(core == i) >= 8
           for i in range(1, count)):
        return None
    core_labels = set(core) if ignore_perimeter_highlights else None
    boxes = [
        (int(stats[i, 4]), int(stats[i, 0]), int(stats[i, 1]), int(stats[i, 2]), int(stats[i, 3]))
        for i in range(1, count)
        if stats[i, 4] >= 20 and not (
            core_labels is not None and i not in core_labels and max(stats[i, 2:4]) <= rad / 2
        )
    ]
    if not 1 <= len(boxes) <= 2:
        return None
    boxes.sort(key=lambda box: box[1])
    if any(h < 10 or w > h for _, x, y, w, h in boxes):
        return None
    if len(boxes) == 2:
        _, x1, y1, w1, h1 = boxes[0]
        _, x2, y2, _, h2 = boxes[1]
        if (min(h1, h2) < max(h1, h2) * 0.7 or not 0 < x2 - x1 - w1 <= max(h1, h2)
                or abs(y1 + h1 / 2 - y2 - h2 / 2) > max(h1, h2) * 0.5):
            return None
    result = []
    for _, x, y, w, h in boxes:
        glyph = normalize_glyph(white[y:y + h, x:x + w])
        result.append(rotate_glyph(glyph, _tilt(glyph)))
    return result


def read_cost(
    image: np.ndarray, badge: Badge, digits: DigitReader, rad: int = _GLYPH_RAD
) -> int | None:
    """读徽章里的费用。读不出返回 None（不猜）。"""
    glyphs = read_cost_glyphs(image, badge.center, rad)
    if glyphs is None:
        return None
    hit = digits.classify_sequence(glyphs, rotations=_ROTATIONS)
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
    tpl = _load_gray_template(str(template))
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


def _visible_playable_unit(image: np.ndarray, badge: Badge, badges: list[Badge]) -> bool:
    """宽间距展开牌：蓝色直线顶部提供单位轮廓及可用发光的联合证据。

    扇形密集时相邻牌的直边会覆盖法术，故拒绝窄间距和边缘裁切。
    该判据不识别牌名或出牌效果。
    """
    x, y = badge.center
    if (image.shape[:2] != (1080, 1920) or y < 75 or x < 0 or x + 220 > 1920
            or any(0 < abs(x - other.center[0]) < 210 for other in badges)):
        return False
    crop = image[y - 75:min(y + 45, image.shape[0]), x + 20:x + 220]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    blue = cv2.inRange(hsv, (90, 100, 120), (125, 255, 255))
    lines = cv2.HoughLinesP(blue[:80], 1, np.pi / 180, threshold=85,
                            minLineLength=175, maxLineGap=5)
    if lines is None:
        return False
    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        if x1 > x2:
            x1, y1, x2, y2 = x2, y2, x1, y1
        if x1 <= 20 and x2 >= 180 and abs(y2 - y1) <= 0.3 * (x2 - x1):
            # 蓝光下方还要有连续明亮的低饱和卡框，不能只认背景蓝线。
            xs = np.arange(25, 175)
            base = np.rint(y1 + (xs - x1) * (y2 - y1) / (x2 - x1)).astype(int)
            if np.max(base) + 24 >= crop.shape[0]:
                continue
            frame = crop[base[:, None] + np.array([16, 24]), xs[:, None]]
            neutral = (frame.max(axis=2) >= 140) & (
                frame.max(axis=2).astype(int) - frame.min(axis=2).astype(int) < 85
            )
            if np.all(neutral.mean(axis=0) >= 0.65):
                return True
    return False


def _expanded_drag_point(
    image: np.ndarray, badge: Badge, badges: list[Badge]
) -> tuple[int, int] | None:
    """估算卡身内部点；空间不足时拒绝拖拽，避免落在邻牌或屏幕外。"""
    x, y = badge.center
    px = x + _EXPANDED_DRAG_BODY_OFFSET[0]
    py = y + _EXPANDED_DRAG_BODY_OFFSET[1]
    height, width = image.shape[:2]
    if not (10 <= px < width - 10 and 10 <= py < height - 10):
        return None
    # 密集扇形下卡牌倾斜、互相遮挡；多牌展开（>=6 张）时游戏压缩间距至约 120px，
    # 此时卡身落点仍在邻牌左缘内侧，少牌仍维持 180px 防止异常重检或粘连。
    min_gap = EXPANDED_MIN_DIST if len(badges) >= 6 else 180
    if any(0 < other.center[0] - x < min_gap
           for other in badges):
        return None
    return px, py


def recognize_expanded(
    image: np.ndarray,
    region: Rect,
    digits: DigitReader,
    threshold: float = EXPANDED_MIN_SCORE,
) -> list[CardInHand]:
    """识别展开态手牌（卡片平铺在屏幕下方）。"""
    badges = find_badges_expanded(image, region, threshold=threshold)
    # 边缘卡倾斜可能使最左徽章得分略低；只有在两张以上可靠徽章
    # 确立间距、候选位于其左侧且费用可读时才补回，不单靠低阈值。
    if threshold == EXPANDED_MIN_SCORE and len(badges) >= 2:
        candidates = find_badges_expanded(image, region, threshold=0.95)
        if candidates and candidates[0].center[0] < badges[0].center[0]:
            candidate = candidates[0]
            gap = badges[1].center[0] - badges[0].center[0]
            left_gap = badges[0].center[0] - candidate.center[0]
            if 0.7 * gap <= left_gap <= 1.3 * gap and read_cost(image, candidate, digits) is not None:
                badges.insert(0, candidate)
    cards: list[CardInHand] = []
    for index, badge in enumerate(badges):
        cx, cy = badge.center
        dx, dy = DRAG_OFFSET_EXPANDED
        cost = read_cost(image, badge, digits)
        drag_point = _expanded_drag_point(image, badge, badges)
        cards.append(
            CardInHand(
                index=index,
                name="",
                cost=-1 if cost is None else cost,
                rect=Rect(cx + dx - 4, cy + dy - 4, 8, 8),
                visible_playable_unit=_visible_playable_unit(image, badge, badges),
                drag_point=drag_point,
                drag_point_valid=drag_point is not None,
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
