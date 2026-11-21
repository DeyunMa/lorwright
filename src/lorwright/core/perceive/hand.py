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
    # 边缘残片若有一两个像素落入核心半径就会留在 core_labels 里逃过排除；
    # 与上方残笔判据一致按核心像素数 <8 认定，绿色减费数字的碎笔画同样剔除。
    boxes = [
        (int(stats[i, 4]), int(stats[i, 0]), int(stats[i, 1]), int(stats[i, 2]), int(stats[i, 3]))
        for i in range(1, count)
        if stats[i, 4] >= 20 and not (
            ignore_perimeter_highlights
            and np.count_nonzero(core == i) < 8
            and max(stats[i, 2:4]) <= rad / 2
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


#: 展开卡面左下力量角标、右下血量角标相对徽章中心的估计位置。
#: 卡面左缘约 cx-32、宽约 196px，角标贴在卡面下缘两角。
_STAT_CHIP_OFFSETS = ((-12, 175), (136, 185))
#: 角标外接半径：六边形约 36px，取样半径 20px。
_STAT_CHIP_RADIUS = 20
#: 邻牌覆盖模型：卡牌沿扇形倾斜，左缘自徽章处 (bx-32, by-55) 向下
#: 每行左移约 0.31px，右缘同斜率、顶部约在徽章 +164px。角标中心
#: 越过该边界才算属于本卡可见区域。
_EDGE_SLOPE = 0.31
_LEFT_EDGE_TOP = (-32, -55)
_RIGHT_EDGE_TOP = 164


def _left_edge_x(badge: Badge, y: int) -> float:
    bx, by = badge.center
    return bx + _LEFT_EDGE_TOP[0] - _EDGE_SLOPE * (y - (by + _LEFT_EDGE_TOP[1]))


def _right_edge_x(badge: Badge, y: int) -> float:
    bx, by = badge.center
    return bx + _RIGHT_EDGE_TOP - _EDGE_SLOPE * (y - (by + _LEFT_EDGE_TOP[1]))


#: 法术星形标记模板：费用徽章下方灰牌上的青色星火簇。两张分别
#: 取自窄扇法术「砰砰」与伊莉丝 0 费法术实帧，布局/倾角不同。
SPELL_MARKER_TEMPLATES = (
    Path("assets/ui/spell_marker.png"),
    Path("assets/ui/spell_marker_b.png"),
    Path("assets/ui/spell_marker_c.png"),
    Path("assets/ui/spell_marker_d.png"),
)
SPELL_MARKER_MIN_SCORE = 0.72
#: 单位顶栏肩角模板：种族横幅左肩（深色横幅底+金色上缘），不含文字
#: 以便跨种族复用；三张取自同一窄扇实帧的不同倾角卡。
UNIT_TAB_TEMPLATES = (
    Path("assets/ui/unit_tab_shoulder_a.png"),
    Path("assets/ui/unit_tab_shoulder_b.png"),
    Path("assets/ui/unit_tab_shoulder_c.png"),
)
UNIT_TAB_MIN_SCORE = 0.70
#: 法术拱形卡框顶部为银灰色尖拱：顶中区域低饱和亮像素占比实测
#: 法术 0.32~0.41、单位 ≤0.11。
_ARCH_SILVER_MIN = 0.18


@lru_cache(maxsize=8)
def _gray_template(path: str) -> np.ndarray | None:
    image = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    return None if image is None else image


def _spell_marker(image: np.ndarray, badge: Badge) -> bool:
    """费用徽章下方的星形法术标记：有标记即非单位。"""
    bx, by = badge.center
    x0, y0 = max(bx - 62, 0), max(by + 25, 0)
    x1, y1 = min(bx + 70, image.shape[1]), min(by + 160, image.shape[0])
    window = cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    for path in SPELL_MARKER_TEMPLATES:
        tpl = _gray_template(str(path))
        if tpl is None:
            continue
        h, w = tpl.shape
        if window.shape[0] < h or window.shape[1] < w:
            continue
        if cv2.matchTemplate(window, tpl, cv2.TM_CCOEFF_NORMED).max() \
                >= SPELL_MARKER_MIN_SCORE:
            return True
    return False


def _arched_frame(image: np.ndarray, badge: Badge) -> bool:
    """卡顶中部的银灰尖拱：法术/装备拱形框的负向证据。"""
    bx, by = badge.center
    zone = image[max(by - 50, 0):max(by - 15, 0), bx + 50:bx + 130]
    if zone.size == 0:
        return False
    hsv = cv2.cvtColor(zone, cv2.COLOR_BGR2HSV)
    silver = (hsv[:, :, 1] < 75) & (hsv[:, :, 2] > 150)
    return float(silver.mean()) >= _ARCH_SILVER_MIN


def _unit_tab(image: np.ndarray, badge: Badge, badges: list[Badge]) -> bool:
    """卡顶中部的种族横幅肩角：方形单位框的正向证据。"""
    bx, by = badge.center
    y0, y1 = max(by - 40, 0), min(by + 30, image.shape[0])
    x0, x1 = bx + 15, min(bx + 185, image.shape[1])
    # 右邻卡左缘若压进横幅取样窗，窗口右截到其左缘，不混入邻卡。
    for other in badges:
        if other.center[0] > bx:
            x1 = min(x1, int(_left_edge_x(other, (y0 + y1) // 2)))
            break
    window = cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    # 近全黑的窗口是退化匹配源（相关在平坦区虚高），直接弃权。
    if float((window > 40).mean()) < 0.30:
        return False
    for path in UNIT_TAB_TEMPLATES:
        tpl = _gray_template(str(path))
        if tpl is None:
            continue
        h, w = tpl.shape
        if window.shape[0] < h or window.shape[1] < w:
            continue
        if cv2.matchTemplate(window, tpl, cv2.TM_CCOEFF_NORMED).max() \
                >= UNIT_TAB_MIN_SCORE:
            return True
    return False


def _stat_chip_present(image: np.ndarray, cx: int, cy: int) -> bool:
    """角标区域：深色六边形底加内部亮色字素。任一角标无法独立验证即弃权。"""
    r = _STAT_CHIP_RADIUS
    x0, y0 = max(cx - r, 0), max(cy - r, 0)
    x1, y1 = min(cx + r, image.shape[1]), min(cy + r, image.shape[0])
    if x1 - x0 < r or y1 - y0 < r:
        return False
    patch = image[y0:y1, x0:x1]
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    # 六边形底为深色块（V<110）；内部数字为亮字素（V>200）或暖色
    # （力量橙底 / 血量红底）。字素必须被深底包围，排除卡面插画里
    # 孤立的亮点或边缘高光。
    dark = (gray < 110)
    if dark.mean() < 0.45:
        return False
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    ink = ((gray > 200) | ((hsv[:, :, 0] < 30) & (hsv[:, :, 1] > 100)
           & (hsv[:, :, 2] > 140))).astype(np.uint8)
    count, _, stats, cents = cv2.connectedComponentsWithStats(ink)
    cy0, cx0 = patch.shape[0] / 2, patch.shape[1] / 2
    for label in range(1, count):
        area = stats[label, cv2.CC_STAT_AREA]
        if not 8 <= area <= 110:
            continue
        lx, ly = cents[label]
        if abs(lx - cx0) >= r * 0.6 or abs(ly - cy0) >= r * 0.6:
            continue
        gx, gy, gw, gh = stats[label, :4]
        m = 4
        ring = dark[max(gy - m, 0):gy + gh + m, max(gx - m, 0):gx + gw + m].copy()
        ring[m:m + gh, m:m + gw] = True
        if ring.size and ring.mean() >= 0.7:
            return True
    return False


def _visible_playable_unit(image: np.ndarray, badge: Badge, badges: list[Badge]) -> bool:
    """单位类型的正向证据：数值角标对，或无负向证据时的方形框种族横幅。

    力量/血量角标在窄扇里常被邻牌或屏幕裁切，故另认方形卡框顶部的
    种族横幅肩角；法术的星形标记或拱形框命中即非单位；仍证据不足
    （横幅被遮、类型未证实）一律弃权。不识别牌名或出牌效果。
    """
    if image.shape[:2] != (1080, 1920):
        return False
    if _spell_marker(image, badge) or _arched_frame(image, badge):
        return False
    if _unit_tab(image, badge, badges):
        return True
    cx, cy = badge.center
    for dx, dy in _STAT_CHIP_OFFSETS:
        x = cx + dx
        if not (_STAT_CHIP_RADIUS <= x < 1920 - _STAT_CHIP_RADIUS):
            return False
        # 卡牌倾斜使角标上下浮动约 ±20px，在锚点附近小范围搜索；
        # 每个候选位置都要求越过邻牌覆盖边界并独立检出角标。
        found = False
        for y in (cy + dy - 20, cy + dy, cy + dy + 20):
            if dx < 0 and any(other.center[0] < cx and _right_edge_x(other, y) > x
                              for other in badges):
                continue
            if dx > 0 and any(other.center[0] > cx and _left_edge_x(other, y) < x
                              for other in badges):
                continue
            if _stat_chip_present(image, x, y):
                found = True
                break
        if not found:
            return False
    return True


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
