"""设备抽象：截图 + 输入。

MAA/ALAS 的经验：把「控制器」抽象出来，上层逻辑不关心是手机还是桌面。
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
    def swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int = 300) -> None: ...
    def size(self) -> tuple[int, int]: ...
    def restart_app(self, package: str) -> None: ...
    def close(self) -> None: ...
