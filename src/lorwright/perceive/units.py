"""场上单位识别：攻击力徽章 → 单位位置。

我方单位卡面左上角、敌方单位卡面下缘各有一个攻击力徽章，形状固定。徽章
中间是攻击力数字，数字随单位变化会显著拉低无掩膜模板匹配分（同一模板
1.00 vs 0.76），所以用「只匹配外框、挖空数字区」的掩膜。

我方和敌方徽章的明暗与描边不同（敌方卡面被屏幕上方裁切、我方带手牌阴影），
实测跨区互匹全部落在 0.975 以下，区内真单位 ≥0.986，所以两个模板各管一边，
阈值 0.98 能干净分开。

攻击力/生命值数字暂不读：位置够攻击和格挡用了，读数留给战斗求解器。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from lorwright.models import Rect, Unit

__all__ = [
    "ENEMY_UNIT_TEMPLATE",
    "MY_UNIT_TEMPLATE",
    "UNIT_MIN_DIST",
    "UNIT_MIN_SCORE",
    "UnitBadge",
    "find_unit_badges",
    "to_units",
]

#: 我方徽章模板（63×44，采自 1920×1080 截图）
MY_UNIT_TEMPLATE = Path("assets/ui/unit_attack_my.png")
#: 敌方徽章模板（62×44）
ENEMY_UNIT_TEMPLATE = Path("assets/ui/unit_attack.png")

#: 实测：真徽章 ≥0.986，跨区/邻位误报 ≤0.975
UNIT_MIN_SCORE = 0.98
#: 相邻单位间距 174px，抑制半径取 100 不会吃掉邻居
UNIT_MIN_DIST = 100

#: 掩膜挖空区 = 攻击力数字（y0, y1, x0, x1）
_GLYPH_HOLE = (12, 36, 16, 48)

#: 我方徽章在卡面左上角，拖拽点要落到卡身中部才抓得住
MY_DRAG_OFFSET = (40, 55)
#: 敌方徽章就在卡面下缘，直接当拖拽目标
ENEMY_DRAG_OFFSET = (0, 0)


@dataclass(frozen=True)
class UnitBadge:
    """一个被检出的攻击力徽章。"""

    center: tuple[int, int]
    score: float


def _mask(h: int, w: int) -> np.ndarray:
    mask = np.full((h, w), 255, np.uint8)
    y0, y1, x0, x1 = _GLYPH_HOLE
    mask[y0:y1, x0:x1] = 0
    return mask


def find_unit_badges(
    image: np.ndarray,
    region: Rect,
    *,
    enemy: bool = False,
    min_score: float = UNIT_MIN_SCORE,
    min_dist: int = UNIT_MIN_DIST,
) -> list[UnitBadge]:
    """在 `region` 里找攻击力徽章，按 x 从左到右返回。"""
    template_path = ENEMY_UNIT_TEMPLATE if enemy else MY_UNIT_TEMPLATE
    template = cv2.imread(str(template_path))
    if template is None:
        raise FileNotFoundError(f"单位徽章模板缺失: {template_path}")
    h, w = template.shape[:2]
    sub = image[region.y : region.y + region.h, region.x : region.x + region.w]
    if sub.shape[0] < h or sub.shape[1] < w:
        return []

    result = cv2.matchTemplate(
        cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY),
        cv2.cvtColor(template, cv2.COLOR_BGR2GRAY),
        cv2.TM_CCORR_NORMED,
        mask=_mask(h, w),
    )

    badges: list[UnitBadge] = []
    while True:
        _, score, _, loc = cv2.minMaxLoc(result)
        # 全黑/全白图上 TM_CCORR_NORMED 会返回 NaN（除以零），而 nan < 阈值
        # 恒为 False —— 不挡就会在空屏上凭空造出单位
        if not np.isfinite(score) or score < min_score:
            break
        cx = region.x + loc[0] + w // 2
        cy = region.y + loc[1] + h // 2
        badges.append(UnitBadge((cx, cy), float(score)))
        cv2.circle(result, loc, min_dist, 0.0, -1)

    badges.sort(key=lambda b: b.center[0])
    return badges


def to_units(badges: list[UnitBadge], *, enemy: bool = False) -> list[Unit]:
    """徽章 → `Unit`。数值未识别时留 -1，策略层据此判断「不知道」。"""
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
