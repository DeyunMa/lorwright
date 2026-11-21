"""「選擇1個單位或地標進行替換」提示：满场打出单位后的替换选目标。

与「選擇目標」按钮文字无法区分普通的选目标流程；提示条是额外证据，
只在 TARGETING 状态下由调用方读取。
"""

from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np


@lru_cache(maxsize=1)
def _template() -> np.ndarray:
    image = cv2.imread(str(Path("assets/ui") / "replace_unit_prompt.png"),
                       cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise FileNotFoundError("replace_unit_prompt.png")
    return image


def replace_unit_prompt(image: np.ndarray) -> bool:
    """左侧中部提示条读作替换选目标；其余 1080p 帧实测最高约 0.17。"""
    if image.shape[:2] != (1080, 1920):
        return False
    patch = cv2.cvtColor(image[505:590, 100:860], cv2.COLOR_BGR2GRAY)
    score = float(cv2.matchTemplate(patch, _template(), cv2.TM_CCOEFF_NORMED).max())
    return score >= 0.90
