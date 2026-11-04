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
    """一帧画面（BGR）+ 采集完成时刻。

    `ts` 用于「动作前帧时效校验」：截图要几百毫秒，如果拿着旧帧去点，
    点击会落在已经变了的画面上——这正是「状态不明还点」的典型来源。
    """

    image: np.ndarray
    ts: float = 0.0
    capture_ms: int = 0

    @property
    def width(self) -> int:
        return int(self.image.shape[1])

    @property
    def height(self) -> int:
        return int(self.image.shape[0])

    def age_s(self, now: float | None = None) -> float:
        """帧龄（秒）。`ts == 0` 表示设备没打时间戳，按「不过期」处理。"""
        if not self.ts:
            return 0.0
        import time as _time

        return max(0.0, (_time.time() if now is None else now) - self.ts)


class Device(Protocol):
    name: str

    def screencap(self) -> Frame: ...
    def tap(self, x: int, y: int) -> None: ...
    def drag(
        self, x1: int, y1: int, x2: int, y2: int, hold_ms: int, drag_ms: int
    ) -> None: ...
    def size(self) -> tuple[int, int]: ...
    def launch(self, package: str) -> None: ...
    def text(self, value: str) -> None: ...
    def restart_app(self, package: str) -> None: ...
    def close(self) -> None: ...
