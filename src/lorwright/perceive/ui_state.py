"""UI 状态机：靠模板判断当前处于哪个界面。"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from lorwright.models import UIState
from lorwright.perceive.locate import exists, load_template


class UIStateDetector:
    """用按钮模板判断状态。

    需要的模板（放 assets/buttons/）：
      - end_turn.png      → MY_TURN_IDLE
      - enemy_turn.png    → ENEMY_TURN
      - victory.png       → BATTLE_END
      - defeat.png        → BATTLE_END
      - targeting.png     → TARGETING（可选，也可用"卡牌已高亮"判断）
    """

    def __init__(self, root: str | Path = "assets/buttons", threshold: float = 0.85) -> None:
        self.root = Path(root)
        self.threshold = threshold
        self._tpl: dict[str, np.ndarray] = {}

    def load(self) -> None:
        self._tpl.clear()
        if not self.root.exists():
            return
        for png in self.root.glob("*.png"):
            self._tpl[png.stem] = load_template(png)

    def detect(self, frame: np.ndarray) -> UIState:
        t = self._tpl
        if "victory" in t and exists(frame, t["victory"], self.threshold):
            return UIState.BATTLE_END
        if "defeat" in t and exists(frame, t["defeat"], self.threshold):
            return UIState.BATTLE_END
        if "end_turn" in t and exists(frame, t["end_turn"], self.threshold):
            return UIState.MY_TURN_IDLE
        if "enemy_turn" in t and exists(frame, t["enemy_turn"], self.threshold):
            return UIState.ENEMY_TURN
        return UIState.UNKNOWN
