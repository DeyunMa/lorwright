"""對局外節點面板：金色主按鈕（旅行／戰鬥）檢測。

節點詳情面板只有一顆實心金色圓角按鈕，文字可能是「旅行」或「戰鬥」。
2026-11-07 f1 1080p 實測：

- 旅行按鈕 bbox 698,460,238,50，HSV 約 H=20-22 / S=146-163 / V=242-255；
- 戰鬥按鈕 bbox 1426,976,311,68，HSV 約 H=16 / S=180 / V=205；
- 地圖草地也是黃綠色，但 V 只有 140 左右，用 V>=190 排除；
- 節點的金色菱形是 60×60 左右，aspect≈1，用 w/h>=1.8 排除。

這裡不讀文字，只找按鈕本體。文字 OCR 留給獎勵選擇（需要名稱時）再做。
"""

from __future__ import annotations

import cv2
import numpy as np

from lorwright.models import Rect

__all__ = ["action_button"]


def action_button(image: np.ndarray) -> Rect | None:
    """回傳面板上最大的實心金色按鈕；沒有就回 None。

    輸入為 BGR、1920×1080 設計尺寸。
    """
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (12, 110, 190), (32, 255, 255))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best: Rect | None = None
    best_area = 0.0
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w < 150 or not 35 <= h <= 120 or not 1.8 <= w / h <= 8:
            continue
        area = cv2.contourArea(contour)
        if area < 4000 or area / (w * h) < 0.65:
            continue
        if area > best_area:
            best_area = area
            best = Rect(x, y, w, h)
    return best
