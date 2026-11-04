"""桌面设备：mss 截屏 + pynput 输入（开发/调试用）。"""

from __future__ import annotations

import time

from lorwright.device.base import Frame


class DesktopDevice:
    name = "desktop"

    def __init__(self, width: int = 1920, height: int = 1080, move_duration: float = 0.15) -> None:
        import mss

        self._sct = mss.mss()
        self._monitor = {"left": 0, "top": 0, "width": width, "height": height}
        self.move_duration = move_duration
        self._size = (width, height)

    def screencap(self) -> Frame:
        import numpy as np

        shot = self._sct.grab(self._monitor)
        return Frame(image=np.asarray(shot)[:, :, :3])

    def tap(self, x: int, y: int) -> None:
        from pynput.mouse import Button, Controller

        m = Controller()
        m.position = (x, y)
        time.sleep(0.03)
        m.press(Button.left)
        time.sleep(0.05)
        m.release(Button.left)

    def drag(
        self, x1: int, y1: int, x2: int, y2: int, hold_ms: int, drag_ms: int
    ) -> None:
        """鼠标按下 → 停顿 → 移动 → 松开。桌面模式能直接表达停顿。"""
        from pynput.mouse import Button, Controller

        m = Controller()
        steps = 20
        m.position = (x1, y1)
        m.press(Button.left)
        time.sleep(hold_ms / 1000)
        for i in range(1, steps + 1):
            t = i / steps
            m.position = (int(x1 + (x2 - x1) * t), int(y1 + (y2 - y1) * t))
            time.sleep(drag_ms / 1000 / steps)
        m.release(Button.left)

    def size(self) -> tuple[int, int]:
        return self._size

    def text(self, value: str) -> None:
        from pynput.keyboard import Controller

        Controller().type(value)

    def launch(self, package: str) -> None:
        # 桌面模式没有应用句柄，启动只能人工做
        from lorwright.util.logger import logger

        logger.warning("desktop: 不支持启动应用（{}），请手动打开", package)

    def restart_app(self, package: str) -> None:
        # 桌面模式没有应用句柄，重启只能人工做
        from lorwright.util.logger import logger

        logger.warning("desktop 模式不支持重启客户端（{}），跳过", package)

    def close(self) -> None:
        try:
            self._sct.close()
        except Exception:
            pass
