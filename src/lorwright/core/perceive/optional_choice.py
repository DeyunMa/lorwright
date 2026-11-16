"""实拍可选三选牌界面；不推断卡牌名称或机制。"""

from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from lorwright.core.models import UIState


@lru_cache(maxsize=3)
def _template(name: str) -> np.ndarray:
    image = cv2.imread(str(Path("assets/ui") / f"optional_choice_{name}.png"),
                       cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise FileNotFoundError(f"optional_choice_{name}.png")
    return image


def _visible(gray: np.ndarray, name: str, area: tuple[int, int, int, int],
             threshold: float = 0.90) -> bool:
    x, y, w, h = area
    patch = gray[y:y + h, x:x + w]
    template = _template(name)
    scores = cv2.matchTemplate(patch, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, (dx, dy) = cv2.minMaxLoc(scores)
    matched = patch[dy:dy + template.shape[0], dx:dx + template.shape[1]]
    bright = template > 180
    return score >= threshold and float(matched[bright].mean()) >= 180


def optional_choice_state(image: np.ndarray) -> UIState | None:
    """控件不完整时阻止蓝色按钮兜底；仅覆盖已标定的三列布局。"""
    if image.shape[:2] != (1080, 1920):
        return None
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    skip = _visible(gray, "skip", (1685, 505, 125, 80))
    collapse = _visible(gray, "collapse", (195, 245, 95, 100))
    costs = all(_visible(gray, "cost_edge", (x, 325, 70, 80), 0.85)
                for x in (490, 810, 1130))
    if skip and collapse and costs:
        return UIState.OPTIONAL_CHOICE
    if skip or collapse or costs:
        return UIState.UNKNOWN
    return None
