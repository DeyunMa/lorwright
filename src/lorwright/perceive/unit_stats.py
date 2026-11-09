"""场上单位的攻击/生命数字。

单位卡左上角有两个方块：橙色攻击、红色生命。数字不是普通 UI 白字：
攻击数字可能是白色或绿色（被 buff 时），生命数字是红底白字。
两者都按颜色掩膜切字形，再用 `Beaufort for LOL` 渲染的模板分类。

模板来源：游戏资源 `BeaufortforLOL-Bold`（85KB TTF），预渲染到
`assets/digits_unit/`，避免运行时依赖 Pillow/字体文件。
读不出、或置信度不够时返回 None，由调用方保留 -1（不猜）。
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from lorwright.models import Rect
from lorwright.perceive.digits import DigitReader, normalize_glyph

_DEFAULT_ROOT = "assets/digits_unit"
_MIN_SCORE = 0.80
_MIN_GLYPH_AREA = 12
_MAX_DIGITS = 3


class UnitStatsReader:
    def __init__(self, root: str | Path = _DEFAULT_ROOT, min_score: float = _MIN_SCORE) -> None:
        self.digits = DigitReader(root=root, min_score=min_score)
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.digits.load()
            self._loaded = True

    def read(self, image: np.ndarray, badge: Rect) -> tuple[int | None, int | None]:
        """返回 (攻击, 生命)，读不出的字段为 None。"""
        self._ensure_loaded()
        return self._read_attack(image, badge), self._read_health(image, badge)

    def _read_attack(self, image: np.ndarray, badge: Rect) -> int | None:
        patch = _inner(image, badge, 5)
        if patch.size == 0:
            return None
        blue, green, red = patch[:, :, 0], patch[:, :, 1], patch[:, :, 2]
        white = patch.min(axis=2) >= 170
        buffed = (green >= 180) & (red <= 120) & (blue <= 120)
        return self._read_mask((white | buffed).astype(np.uint8) * 255)

    def _read_health(self, image: np.ndarray, badge: Rect) -> int | None:
        health = _find_health_badge(image, badge)
        if health is None:
            return None
        patch = _inner(image, health, 5)
        if patch.size == 0:
            return None
        return self._read_mask((patch.min(axis=2) >= 170).astype(np.uint8) * 255)

    def _read_mask(self, mask: np.ndarray) -> int | None:
        count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        boxes = [
            (int(stats[i, 0]), int(stats[i, 1]), int(stats[i, 2]), int(stats[i, 3]))
            for i in range(1, count)
            if stats[i, 4] >= _MIN_GLYPH_AREA and stats[i, 2] <= stats[i, 3] * 1.6
        ]
        if not boxes:
            return None
        tallest = max(h for _, _, _, h in boxes)
        boxes = [b for b in boxes if b[3] >= tallest * 0.6]
        boxes.sort(key=lambda b: b[0])
        if not boxes or len(boxes) > _MAX_DIGITS:
            return None

        out = ""
        for x, y, w, h in boxes:
            hit = self.digits.classify(normalize_glyph(mask[y : y + h, x : x + w]))
            if hit is None:
                return None
            out += str(hit[0])
        return int(out)


def _inner(image: np.ndarray, rect: Rect, margin: int) -> np.ndarray:
    x0 = max(0, rect.x + margin)
    y0 = max(0, rect.y + margin)
    x1 = min(image.shape[1], rect.x + rect.w - margin)
    y1 = min(image.shape[0], rect.y + rect.h - margin)
    return image[y0:y1, x0:x1]


def _find_health_badge(image: np.ndarray, attack: Rect) -> Rect | None:
    """攻击方块右侧、同一行的红色生命方块。"""
    x0 = max(0, attack.x + attack.w - 5)
    x1 = min(image.shape[1], x0 + 120)
    y0 = max(0, attack.y - 10)
    y1 = min(image.shape[0], attack.y + attack.h + 10)
    sub = image[y0:y1, x0:x1]
    if sub.size == 0:
        return None
    hsv = cv2.cvtColor(sub, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([0, 120, 100]), np.array([10, 255, 255]))
    mask |= cv2.inRange(hsv, np.array([170, 120, 100]), np.array([180, 255, 255]))
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    attack_cy = attack.y + attack.h / 2
    candidates = []
    for i in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[i])
        if area < 800 or not (40 <= w <= 100 and 30 <= h <= 70):
            continue
        cy = y0 + y + h / 2
        candidates.append((abs(cy - attack_cy), x0 + x, y0 + y, w, h))
    if not candidates:
        return None
    _, x, y, w, h = min(candidates)
    return Rect(x, y, w, h)


__all__ = ["UnitStatsReader"]
