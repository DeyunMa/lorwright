"""治疗师页面：只识别已选中的免费治疗及其按钮。"""

from __future__ import annotations

import cv2
import numpy as np

from lorwright.core.models import Rect
from lorwright.core.perceive.adventure_scene import _template


def _visible(
    image: np.ndarray, name: str, bounds: tuple[int, int, int, int]
) -> Rect | None:
    template = _template(name)
    if template is None or image.shape != (1080, 1920, 3):
        return None
    x1, y1, x2, y2 = bounds
    region = cv2.cvtColor(image[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    height, width = template.shape
    if region.shape[0] < height or region.shape[1] < width:
        return None
    scores = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, (x, y) = cv2.minMaxLoc(scores)
    patch = region[y:y + height, x:x + width]
    bright = template >= max(90, float(np.percentile(template, 75)))
    if (score < 0.90 or not bright.any()
            or float(patch[bright].mean()) < float(template[bright].mean()) * 0.8):
        return None
    return Rect(x1 + x, y1 + y, width, height)


def is_healer_screen(image: np.ndarray) -> bool:
    """识别治疗师页面；选项不清楚时仍由调用方保存快照停下。"""
    return (any(_visible(image, name, (540, 335, 760, 435)) is not None
                for name in ("healer_title", "healer_title_bright"))
            or _visible(image, "field_cook_title", (550, 345, 805, 430)) is not None)


def healer_heal_button(image: np.ndarray) -> Rect | None:
    """已选免费治疗且页面可辨认时返回治疗按钮；不选购或删除卡牌。"""
    if not is_healer_screen(image):
        return None
    if _visible(image, "healer_selected", (918, 740, 994, 830)) is None:
        return None
    if _visible(image, "healer_heal_description", (1190, 20, 1510, 95)) is None:
        return None
    return _visible(image, "healer_heal_button", (1380, 965, 1510, 1045))
