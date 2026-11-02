"""执行层：鼠标点击 / 拖拽 / 按键。

LoR 在「点击出牌」模式下只需要点击；保留 drag 以备切换回拖拽模式。
"""

from __future__ import annotations

import time

from lorwright.util.logger import logger


class Mouse:
    def __init__(self, move_duration: float = 0.15) -> None:
        from pynput.mouse import Controller

        self._m = Controller()
        self.move_duration = move_duration

    def move_to(self, x: int, y: int, steps: int = 15) -> None:
        """分步移动，模拟人手。"""
        sx, sy = self._m.position
        for i in range(1, steps + 1):
            t = i / steps
            self._m.position = (int(sx + (x - sx) * t), int(sy + (y - sy) * t))
            time.sleep(self.move_duration / steps)

    def click(self, x: int, y: int, button: str = "left") -> None:
        from pynput.mouse import Button

        btn = Button.left if button == "left" else Button.right
        self.move_to(x, y)
        time.sleep(0.03)
        self._m.press(btn)
        time.sleep(0.05)
        self._m.release(btn)
        logger.debug("click ({}, {})", x, y)

    def drag(self, x1: int, y1: int, x2: int, y2: int, steps: int = 20) -> None:
        """按住 → 分步移动 → 松开（备用：拖拽出牌模式）。"""
        from pynput.mouse import Button

        self.move_to(x1, y1)
        self._m.press(Button.left)
        time.sleep(0.08)
        self.move_to(x2, y2, steps=steps)
        time.sleep(0.08)
        self._m.release(Button.left)
        logger.debug("drag ({},{}) -> ({},{})", x1, y1, x2, y2)

    def position(self) -> tuple[int, int]:
        return self._m.position
