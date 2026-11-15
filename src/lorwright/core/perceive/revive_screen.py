"""保守识别已采样的冒险复活页。"""

from __future__ import annotations

import cv2
import numpy as np

from lorwright.core.models import Rect
from lorwright.core.perceive.adventure_scene import _template


def _matches_visible(image: np.ndarray, name: str, bounds: tuple[int, int, int, int],
                     segments: int) -> bool:
    template = _template(name)
    x1, y1, x2, y2 = bounds
    if template is None or template.shape != (y2 - y1, x2 - x1):
        return False
    region = cv2.cvtColor(image[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    # 分段比较绝对亮度与细节，防止整体变暗、局部遮挡和模糊仍通过相关性匹配。
    for actual, expected in zip(np.array_split(region, segments, axis=1),
                                np.array_split(template, segments, axis=1), strict=True):
        if float(np.mean(cv2.absdiff(actual, expected))) > 8:
            return False
    return True


def find_revive_button(image: np.ndarray) -> Rect | None:
    """同时确认复活说明和完整按钮；无法确认时不授权点击。"""
    if image.shape != (1080, 1920, 3):
        return None
    if not _matches_visible(image, "revive_message", (460, 600, 1460, 660), 8):
        return None
    if not _matches_visible(image, "revive_button", (804, 858, 1116, 967), 4):
        return None
    return Rect(804, 858, 312, 109)
