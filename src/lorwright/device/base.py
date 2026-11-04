"""设备抽象：截图 + 输入。

MAA/ALAS 的经验：把「控制器」抽象出来，上层逻辑不关心是手机还是桌面。

输入用 `drag(hold_ms, drag_ms)` 而不是 `swipe(ms)`：LoR 出牌要「按住 → 停顿 →
拖 → 松手」，只给总时长的 swipe 表达不了停顿（见 device/touch.py）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass
class Frame:
    """一帧画面（BGR）。"""

    image: np.ndarray

    @property
    def width(self) -> int:
        return int(self.image.shape[1])

    @property
    def height(self) -> int:
        return int(self.image.shape[0])


class Device(Protocol):
    name: str

    def screencap(self) -> Frame: ...
    def tap(self, x: int, y: int) -> None: ...
    def drag(
        self, x1: int, y1: int, x2: int, y2: int, hold_ms: int, drag_ms: int
    ) -> None: ...
    def size(self) -> tuple[int, int]: ...
    def restart_app(self, package: str) -> None: ...
    def close(self) -> None: ...
