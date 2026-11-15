"""通过多个页面特征识别战斗后的任务与宝库结算页。"""

from __future__ import annotations

import cv2
import numpy as np

from lorwright.core.perceive.adventure_scene import _template


def _visible(image: np.ndarray, name: str, bounds: tuple[int, int, int, int]) -> bool:
    template = _template(name)
    if template is None:
        return False
    x1, y1, x2, y2 = bounds
    region = cv2.cvtColor(image[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    if region.shape[0] < template.shape[0] or region.shape[1] < template.shape[1]:
        return False
    scores = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, (x, y) = cv2.minMaxLoc(scores)
    h, w = template.shape
    patch = region[y:y + h, x:x + w]
    bright = template >= 160
    return bool(score >= 0.83 and bright.any()
                and float(patch[bright].mean()) >= float(template[bright].mean()) * 0.8)


def result_screen(image: np.ndarray) -> str | None:
    """识别已采样的结算页；输入应为 1920×1080 设计帧。"""
    if image.shape != (1080, 1920, 3):
        return None
    if (_visible(image, "result_missions_title", (528, 187, 779, 274))
            and _visible(image, "result_missions_xp", (1496, 46, 1683, 126))):
        return "missions"
    if (_visible(image, "result_vault_title", (1158, 20, 1387, 153))
            and _visible(image, "result_vault_xp", (214, 349, 390, 427))):
        return "vault"
    return None
