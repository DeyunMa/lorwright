"""识别起手换牌按钮当前显示「替換」还是「取消」。"""

from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

_ASSETS = Path("assets/mulligan")
MULLIGAN_REPLACE_POINTS = ((438, 820), (756, 820), (1068, 817), (1386, 817))
_BUTTON_CENTERS = (486, 802, 1118, 1434)


@lru_cache(maxsize=1)
def _templates() -> tuple[np.ndarray | None, np.ndarray | None]:
    return tuple(
        cv2.imread(str(_ASSETS / f"{name}.png"), cv2.IMREAD_GRAYSCALE)
        for name in ("replace", "cancel")
    )


def recognize_mulligan_selection(image: np.ndarray) -> tuple[bool | None, ...]:
    """设计尺寸下逐槽判定选中；文字不清、遮暗或按钮缺失时返回 None。"""
    unknown = (None,) * 4
    if image.shape != (1080, 1920, 3):
        return unknown
    templates = _templates()
    if any(template is None for template in templates):
        return unknown
    states: list[bool | None] = []
    for center in _BUTTON_CENTERS:
        area = cv2.cvtColor(image[795:880, center - 85:center + 85], cv2.COLOR_BGR2GRAY)
        matches = []
        for template in templates:
            scores = cv2.matchTemplate(area, template, cv2.TM_CCOEFF_NORMED)
            _, score, _, (x, y) = cv2.minMaxLoc(scores)
            patch = area[y:y + template.shape[0], x:x + template.shape[1]]
            matches.append((float(score), x, y, float(np.percentile(patch, 95))))
        selected = int(matches[1][0] > matches[0][0])
        best, other = matches[selected], matches[1 - selected]
        if (best[0] < 0.93 or best[0] - other[0] < 0.2 or best[3] < 175
                or not 24 <= best[1] <= 37 or not 9 <= best[2] <= 21):
            states.append(None)
        else:
            states.append(bool(selected))
    return tuple(states)
