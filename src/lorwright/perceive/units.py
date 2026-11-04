"""场上单位识别：攻击力方块 → 单位位置。

**为什么不用模板匹配。** 最早用「挖空数字的攻击力徽章模板」，因为卡面上的
buff 光效、装备图标、选中高亮都会改变像素，同一张截图里两个单位的匹配分
能差 0.05（实测 1.000 vs 0.944），阈值 0.98 只能认出一半。更糟的是单位卡
在「可攻击」和「待命」两种状态下样式完全不同（后者带蓝色发光描边），
一个模板管不了两种状态，`my_units` 会在回合中途突然变 0，策略就以为没兵
可打，整局不攻击。

**改成认颜色。** 攻击力方块的橙色是固定的（H 8-30、S≥150、V≥140），
生命值方块的红色也是固定的，两者都不随 buff/描边/选中状态变化。
按连通域找方块，形状约束（长宽比 0.7-2.2、面积≥400）滤掉卡面上的装饰。

**方向差异。** 我方单位卡在己方半场，攻击力方块在**卡面顶部**，拖拽要往
下落到卡身才抓得住（`MY_DRAG_OFFSET`）；敌方单位卡被屏幕下缘裁切，
攻击力方块就在**卡面底部**，方块中心本身就是落点（`ENEMY_DRAG_OFFSET`）。

攻击力/生命值数字暂不读：位置够攻击和格挡用了，读数留给战斗求解器
（`perceive/digits.py` 的字形库已经支持白/绿两套）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

from lorwright.models import Rect, Unit

__all__ = [
    "ATTACK_BLOCK_MIN_AREA",
    "ATTACK_ORANGE",
    "ENEMY_DRAG_OFFSET",
    "MY_DRAG_OFFSET",
    "UnitBadge",
    "find_unit_badges",
    "to_units",
]

#: 攻击力方块的橙色（OpenCV HSV：H 0-180）。实测我方/敌方中位 H 都是 13-15。
#:
#: 试过把下限放到 H=5 去捞「攻击行橙→红渐变」的方块（7|9 那只的 H 分位
#: 是 7/18/177），结果相邻的橙色元素全部连通：敌方从 3 个掉到 2 个、
#: 我方从 5 个掉到 3 个。色域不能再放宽，攻击行的个别单位宁可漏检。
ATTACK_ORANGE = ((8, 150, 140), (30, 255, 255))
#: 真方块实测 62×44、面积 1700-2200。下限 1400 能滤掉卡面上的 buff 图标
#: （面积 250-1150）和装备标记，又不至于因为数字变化把真方块排除。
ATTACK_BLOCK_MIN_AREA = 1400
#: 尺寸窗口 (w_min, w_max, h_min, h_max)。
#:
#: 待命单位的方块实测 60-62 × 43-44。但**攻击行**的单位方块外面多一层
#: 描边，实测 68 × 59；只按 43-44 卡高度会把正在攻击的单位全部漏掉，
#: 格挡阶段就找不到该拖到哪儿。上限放到 90×70 覆盖这层描边，
#: 下限 35 仍然能滤掉卡面装饰（误检实测 19-39 高）。
#:
#: 另有一种情况这个窗口管不了：单位整圈套着「攻击中」橙色高亮时，
#: 高亮和攻击力方块连通成一个 150×250 的大块（实测 7|9 那只）。
#: 那需要单独按「高亮框」处理，见 `_find_highlighted`。
ATTACK_BLOCK_SIZE = (50, 90, 35, 70)
#: 同一单位卡上会出现第二个橙色元素（buff 图标），实测间距 68-95px；
#: 正常单位间距 163px。100 能在两者之间干净切开。
#:
#: 注意是**欧氏距离**不是 x 距离。待命位和攻击行是上下两排，同一列的
#: 两个单位 x 只差 60-80（实测 4|6 在 x=926、它正下方的 4|3 在 x=1004），
#: 只比 x 会把下面那个当成上面那个卡面上的图标丢掉。
UNIT_MIN_DIST = 100

#: 我方方块在卡面顶部，拖拽点要落到卡身中部才抓得住
MY_DRAG_OFFSET = (40, 55)
#: 敌方方块就在卡面下缘，方块中心即落点
ENEMY_DRAG_OFFSET = (0, 0)


@dataclass(frozen=True)
class UnitBadge:
    """一个被检出的攻击力方块。`center` 是方块中心，不是拖拽点。"""

    center: tuple[int, int]
    score: float
    rect: Rect | None = None


def _orange_mask(hsv: np.ndarray) -> np.ndarray:
    lo, hi = ATTACK_ORANGE
    mask = cv2.inRange(hsv, np.array(lo), np.array(hi))
    # 方块内部的数字和描边会把连通域切碎，先闭运算补回来
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))


def find_unit_badges(
    image: np.ndarray,
    region: Rect,
    *,
    enemy: bool = False,
    min_area: int = ATTACK_BLOCK_MIN_AREA,
) -> list[UnitBadge]:
    """在 `region` 里找攻击力方块，按 x 从左到右返回。

    `enemy` 只影响调用方怎么用（拖拽偏移不同），检出的形状判据两边一样。
    """
    sub = image[region.y : region.y + region.h, region.x : region.x + region.w]
    if sub.size == 0:
        return []
    hsv = cv2.cvtColor(sub, cv2.COLOR_BGR2HSV)
    mask = _orange_mask(hsv)
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask)

    w_min, w_max, h_min, h_max = ATTACK_BLOCK_SIZE
    candidates: list[UnitBadge] = []
    for i in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[i])
        if area < min_area or not (w_min <= w <= w_max and h_min <= h <= h_max):
            continue
        candidates.append(
            UnitBadge(
                center=(region.x + x + w // 2, region.y + y + h // 2),
                # 颜色判据没有「匹配分」，用面积占方块典型面积的比例当置信度，
                # 只用于日志和测试断言，不做阈值过滤。
                score=min(1.0, area / 2000.0),
                rect=Rect(region.x + x, region.y + y, w, h),
            )
        )

    # 间距抑制：同卡上的 buff 图标紧挨着真方块，留面积大的那个
    candidates.sort(key=lambda b: -b.score)
    kept: list[UnitBadge] = []
    for badge in candidates:
        if all(
            math.dist(badge.center, k.center) >= UNIT_MIN_DIST for k in kept
        ):
            kept.append(badge)
    kept.sort(key=lambda b: b.center[0])
    return kept


def to_units(badges: list[UnitBadge], *, enemy: bool = False) -> list[Unit]:
    """方块 → `Unit`。数值未识别时留 -1，策略层据此判断「不知道」。"""
    dx, dy = ENEMY_DRAG_OFFSET if enemy else MY_DRAG_OFFSET
    return [
        Unit(
            name="",
            attack=-1,
            health=-1,
            # rect 是 8×8 的拖拽点，中心即落指坐标（和手牌同一个约定）
            rect=Rect(badge.center[0] + dx - 4, badge.center[1] + dy - 4, 8, 8),
        )
        for badge in badges
    ]
