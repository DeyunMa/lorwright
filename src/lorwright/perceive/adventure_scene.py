"""对局外画面的保守识别；无法证明画面类型时不授权点击。"""

from __future__ import annotations

from functools import cache
from pathlib import Path

import cv2
import numpy as np

from lorwright.models import Rect

_ASSETS = Path("assets/adventure")


@cache
def _template(name: str) -> np.ndarray | None:
    return cv2.imread(str(_ASSETS / f"{name}.png"), cv2.IMREAD_GRAYSCALE)


def _matches(image: np.ndarray, name: str, rect: tuple[int, int, int, int],
             threshold: float = 0.85) -> bool:
    tpl = _template(name)
    if tpl is None or image.shape[:2] != (1080, 1920):
        return False
    x1, y1, x2, y2 = rect
    region = cv2.cvtColor(image[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    if region.shape[0] < tpl.shape[0] or region.shape[1] < tpl.shape[1]:
        return False
    return float(cv2.matchTemplate(region, tpl, cv2.TM_CCOEFF_NORMED).max()) >= threshold


def is_map(image: np.ndarray) -> bool:
    """同时识别地图返回键与缩放控件，不能仅凭蓝色像素认地图。"""
    return (_matches(image, "map_back", (80, 65, 118, 105), 0.9)
            and _matches(image, "map_zoom", (1780, 240, 1864, 430)))


def is_battle_detail(image: np.ndarray) -> bool:
    return (_matches(image, "map_back", (80, 65, 118, 105), 0.9)
            and _matches(image, "battle_detail", (1572, 133, 1703, 166), 0.9))


def is_completed_panel(image: np.ndarray) -> bool:
    return is_map(image) and _matches(image, "completed", (400, 300, 1100, 650), 0.9)


def button_is(image: np.ndarray, button: Rect, name: str) -> bool:
    """金色外观不足以区分按钮：还需匹配按钮上的文字。"""
    return _matches(image, name, (button.x, button.y, button.x + button.w, button.y + button.h))
