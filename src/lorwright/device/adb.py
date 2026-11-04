"""ADB 设备：手机 / 模拟器。

截图走 `adb exec-out screencap -p`，输入走 `adb shell input`。
"""

from __future__ import annotations

import subprocess
import time

import cv2
import numpy as np

from lorwright.device.base import Frame


class AdbDevice:
    name = "adb"

    def __init__(self, serial: str | None = None, adb: str = "adb", timeout: float = 15.0) -> None:
        self.serial = serial
        self.adb = adb
        self.timeout = timeout
        self._size: tuple[int, int] | None = None
        self._connected = False

    # ---- 进程调用 ----

    def _base(self) -> list[str]:
        return [self.adb] + (["-s", self.serial] if self.serial else [])

    def _ensure_connected(self) -> None:
        """serial 形如 host:port 时先 `adb connect`。

        adb daemon 会随发起它的会话一起消失，模拟器实例因此掉线；
        每个进程自己重连一次，`lorwright probe` 之类才不用前置命令。
        """
        if self._connected or not self.serial or ":" not in self.serial:
            return
        self._connected = True
        subprocess.run(
            [self.adb, "connect", self.serial],
            capture_output=True, timeout=self.timeout, check=False,
        )

    def _run(self, *args: str, binary: bool = False):
        self._ensure_connected()
        cmd = self._base() + list(args)
        try:
            p = subprocess.run(
                cmd, capture_output=True, timeout=self.timeout, check=False
            )
        except FileNotFoundError as e:
            raise RuntimeError(f"找不到 adb：{self.adb}") from e
        if p.returncode != 0:
            err = p.stderr.decode("utf-8", "ignore").strip()
            raise RuntimeError(f"adb 失败（{p.returncode}）：{' '.join(args)} → {err}")
        return p.stdout if binary else p.stdout.decode("utf-8", "ignore")

    # ---- 设备发现 ----

    @staticmethod
    def list_devices(adb: str = "adb") -> list[str]:
        try:
            out = subprocess.run(
                [adb, "devices"], capture_output=True, text=True, timeout=10, check=False
            ).stdout
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return []
        serials = []
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                serials.append(parts[0])
        return serials

    # ---- Device 接口 ----

    def screencap(self) -> Frame:
        raw = self._run("exec-out", "screencap", "-p", binary=True)
        arr = np.frombuffer(raw, np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError("截图解码失败（可能是 adb 输出被污染）")
        return Frame(image=img)

    def tap(self, x: int, y: int) -> None:
        self._run("shell", "input", "tap", str(int(x)), str(int(y)))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int = 300) -> None:
        self._run(
            "shell", "input", "swipe",
            str(int(x1)), str(int(y1)), str(int(x2)), str(int(y2)), str(int(ms)),
        )

    def size(self) -> tuple[int, int]:
        """当前方向下的截图尺寸（不是 wm size 的物理尺寸）。

        横屏游戏截图是 2510x1156，而 wm size 永远报竖屏 1156x2510，
        用后者会把所有坐标算错。
        """
        if self._size:
            return self._size
        frame = self.screencap()
        self._size = (frame.width, frame.height)
        return self._size

    def close(self) -> None:
        pass

    # ---- 便捷方法 ----

    def keyevent(self, code: int) -> None:
        self._run("shell", "input", "keyevent", str(code))

    def back(self) -> None:
        self.keyevent(4)

    def home(self) -> None:
        self.keyevent(3)

    def launch(self, package: str) -> None:
        self._run(
            "shell", "monkey", "-p", package,
            "-c", "android.intent.category.LAUNCHER", "1",
        )
        time.sleep(0.5)

    def restart_app(self, package: str) -> None:
        """强制结束再拉起：游戏进程无响应时用（docs/handoff.md §4.1）。

        注意：LoR 重启后会回到 Riot 登入页（登录态被清）。
        """
        self._run("shell", "am", "force-stop", package)
        time.sleep(1.0)
        self.launch(package)

    def current_focus(self) -> str:
        out = self._run("shell", "dumpsys", "window")
        for line in out.splitlines():
            if "mCurrentFocus" in line:
                return line.strip()
        return ""

    def info(self) -> dict:
        return {
            "serial": self.serial,
            "size": self.size(),
            "focus": self.current_focus(),
        }
