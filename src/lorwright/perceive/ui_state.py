"""UI 状态机：颜色探针 + 模板匹配。

颜色探针优先：右侧动作按钮（略過/結束回合）是固定位置的大块蓝色，
占比 >45% 就说明轮到我方。比模板匹配稳——按钮文字会变，颜色不会。
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from lorwright.models import Rect, UIState
from lorwright.perceive.locate import exists, load_template

# OpenCV HSV：蓝色 H≈100-125
BLUE_LO = (95, 120, 120)
BLUE_HI = (125, 255, 255)
MIN_BLUE_RATIO = 0.45


def blue_ratio(img: np.ndarray, rect: Rect) -> float:
    """矩形区域内「蓝色像素」占比。"""
    patch = img[rect.y : rect.y + rect.h, rect.x : rect.x + rect.w]
    if patch.size == 0:
        return 0.0
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(BLUE_LO), np.array(BLUE_HI))
    return float(mask.sum()) / 255.0 / (patch.shape[0] * patch.shape[1])


class UIStateDetector:
    """判断当前处于哪个界面。

    优先级：
      1. 动作按钮蓝色占比 → MY_TURN_IDLE
      2. 模板匹配 victory/defeat → BATTLE_END
      3. 模板匹配 enemy_turn → ENEMY_TURN
      4. 都没有 → UNKNOWN

    已知局限：起手换牌界面的「確定」按钮和动作按钮位置重叠，
    会被误判成 MY_TURN_IDLE。等 #2 补上 mulligan 模板再区分。
    """

    def __init__(
        self,
        root: str | Path = "assets/buttons",
        threshold: float = 0.85,
        action_button: Rect | None = None,
    ) -> None:
        self.root = Path(root)
        self.threshold = threshold
        self.action_button = action_button
        self._tpl: dict[str, np.ndarray] = {}

    def load(self) -> None:
        self._tpl.clear()
        if not self.root.exists():
            return
        for png in self.root.glob("*.png"):
            self._tpl[png.stem] = load_template(png)

    def detect(self, frame: np.ndarray) -> UIState:
        # 1. 颜色探针
        if self.action_button and blue_ratio(frame, self.action_button) >= MIN_BLUE_RATIO:
            return UIState.MY_TURN_IDLE

        # 2. 模板
        t = self._tpl
        if "victory" in t and exists(frame, t["victory"], self.threshold):
            return UIState.BATTLE_END
        if "defeat" in t and exists(frame, t["defeat"], self.threshold):
            return UIState.BATTLE_END
        if "enemy_turn" in t and exists(frame, t["enemy_turn"], self.threshold):
            return UIState.ENEMY_TURN

        return UIState.UNKNOWN
