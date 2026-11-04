"""回放设备：用历史截图跑真实主循环，不碰 adb、不碰游戏。

调试感知/决策时最费时的不是改代码，是「开游戏 → 走到那个画面 → 复现」。
这个设备把一段截图当成设备，`screencap()` 按顺序吐帧，`tap()`/`drag()`
只记录不执行，于是同一套 `Engine` 可以离线跑，动作序列还能断言。

用法：
    lorwright run --replay tests/fixtures/replay/xxx --max-ticks 5
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2

from lorwright.device.base import Frame

__all__ = ["ReplayDevice"]


class ReplayDevice:
    name = "replay"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.frames = sorted(self.root.glob("*.png")) + sorted(self.root.glob("*.jpg"))
        if not self.frames:
            raise FileNotFoundError(f"回放目录里没有截图：{self.root}")
        self.actions: list[tuple] = []
        self._i = 0
        first = cv2.imread(str(self.frames[0]), cv2.IMREAD_COLOR)
        if first is None:
            raise RuntimeError(f"截图读不出来：{self.frames[0]}")
        self._size = (first.shape[1], first.shape[0])

    def screencap(self) -> Frame:
        path = self.frames[min(self._i, len(self.frames) - 1)]
        self._i += 1
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError(f"截图读不出来：{path}")
        return Frame(image=img, ts=time.time())

    def tap(self, x: int, y: int) -> None:
        self.actions.append(("tap", int(x), int(y)))

    def drag(self, x1: int, y1: int, x2: int, y2: int, hold_ms: int, drag_ms: int) -> None:
        self.actions.append(("drag", int(x1), int(y1), int(x2), int(y2), hold_ms, drag_ms))

    def text(self, value: str) -> None:
        self.actions.append(("text", value))

    def size(self) -> tuple[int, int]:
        return self._size

    def launch(self, package: str) -> None:
        self.actions.append(("launch", package))

    def restart_app(self, package: str) -> None:
        self.actions.append(("restart", package))

    def close(self) -> None:
        pass

    # 便于测试断言
    @property
    def taps(self) -> list[tuple[int, int]]:
        return [(a[1], a[2]) for a in self.actions if a[0] == "tap"]

    @property
    def drags(self) -> list[tuple[int, ...]]:
        return [a[1:] for a in self.actions if a[0] == "drag"]
