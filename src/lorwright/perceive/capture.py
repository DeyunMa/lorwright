"""截屏：mss 为主，Windows 下可用 pywin32 定位窗口。"""

from __future__ import annotations

import sys
from dataclasses import dataclass

import numpy as np


@dataclass
class CaptureResult:
    frame: np.ndarray   # BGR
    offset_x: int = 0   # 窗口在屏幕上的偏移（全屏时为 0）
    offset_y: int = 0


class ScreenCapture:
    """固定区域截屏。

    当前实现：截取主显示器全屏。
    后续可扩展为「按窗口标题定位 + 只截窗口区域」。
    """

    def __init__(self, width: int = 1920, height: int = 1080) -> None:
        import mss

        self._sct = mss.mss()
        self.width = width
        self.height = height
        self._monitor = {"left": 0, "top": 0, "width": width, "height": height}

    def grab(self) -> CaptureResult:
        shot = self._sct.grab(self._monitor)
        frame = np.asarray(shot)[:, :, :3]  # BGRA -> BGR
        return CaptureResult(frame=frame)

    def close(self) -> None:
        try:
            self._sct.close()
        except Exception:
            pass


def is_windows() -> bool:
    return sys.platform == "win32"
