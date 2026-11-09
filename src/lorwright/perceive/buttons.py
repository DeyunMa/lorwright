"""通用按钮识别：返回当前截图中的可点击位置，不决定何时点击。"""

from __future__ import annotations

from functools import cache
from pathlib import Path

import cv2
import numpy as np

from lorwright.models import Rect


@cache
def _continue_templates() -> tuple[np.ndarray, ...]:
    root = Path("assets/common")
    templates = (cv2.imread(str(root / name), cv2.IMREAD_GRAYSCALE) for name in (
        "continue_gold.png", "continue_bronze.png",
    ))
    return tuple(template for template in templates if template is not None)


def find_continue_button(image: np.ndarray) -> Rect | None:
    """定位繁中「繼續」文字所在的可点击区域；缺失或有多个候选时弃权。

    返回坐标属于输入图像。现有模板来自 960×540 历史截图，只验证了
    两种按钮样式；流程仍须先确认界面，不能把按钮外观当成界面类型。
    """
    if image.ndim != 3 or image.shape[2] != 3:
        return None
    height, width = image.shape[:2]
    if not height or abs(width / height - 16 / 9) > 0.02:
        return None
    reference = cv2.resize(image, (960, 540), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    candidates: list[tuple[float, Rect]] = []
    for template in _continue_templates():
        scores = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
        regions, labels, _, _ = cv2.connectedComponentsWithStats(
            (scores >= 0.90).astype(np.uint8)
        )
        for label in range(1, regions):
            masked = np.where(labels == label, scores, -1.0)
            _, score, _, (x, y) = cv2.minMaxLoc(masked)
            h, w = template.shape
            patch = reference[y:y + h, x:x + w]
            hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
            gold = cv2.inRange(hsv, (10, 60, 70), (40, 255, 255))
            if np.count_nonzero(gold) / gold.size >= 0.5:
                candidates.append((score, Rect(x, y, w, h)))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    best = candidates[0][1]
    bx, by = best.center
    if any(abs(rect.center[0] - bx) > 20 or abs(rect.center[1] - by) > 20
           for _, rect in candidates[1:]):
        return None
    return Rect(round(best.x * width / 960), round(best.y * height / 540),
                round(best.w * width / 960), round(best.h * height / 540))
