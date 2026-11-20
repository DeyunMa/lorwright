"""ADB 设备：手机 / 模拟器。

截图走 `adb exec-out screencap -p`，输入走 `adb shell input`。
"""

from __future__ import annotations

import shlex
import subprocess
import time

import cv2
import numpy as np

from lorwright.core.device.base import Frame
from lorwright.core.device.touch import (
    AdbInputSurface,
    EvdevSurface,
    TouchSurface,
    discover_touch_device,
)
from lorwright.core.util.logger import logger


def secret_text_supported(value: str) -> bool:
    """Android input text accepts printable ASCII; percent has special escape semantics."""
    return bool(value) and all(32 <= ord(char) <= 126 and char != "%" for char in value)


class AdbTimeout(RuntimeError):
    """adb 子进程超过超时上限时抛出，便于与代码异常区分。"""


class AdbRunner:
    """adb 调用入口：统一重连与错误检查。

    输入后端和截图必须走同一个入口。之前输入后端自己起 `adb`，绕过了重连，
    还把返回码丢掉了——新会话里 adb daemon 刚起、设备还没连上，
    `input tap` 报 "no devices" 却被当成成功，表现是「点了没反应」。
    """

    def __init__(self, adb: str = "adb", serial: str | None = None, timeout: float = 15.0) -> None:
        self.adb = adb
        self.serial = serial
        self.timeout = timeout
        self._connected = False

    def base(self) -> list[str]:
        return [self.adb] + (["-s", self.serial] if self.serial else [])

    def ensure(self) -> None:
        """serial 形如 host:port 时先 `adb connect`。

        adb daemon 会随发起它的会话一起消失，模拟器实例因此掉线；
        每个进程自己重连一次，`lorwright probe` 之类才不用前置命令。
        """
        if self._connected or not self.serial or ":" not in self.serial:
            return
        try:
            p = subprocess.run(
                [self.adb, "connect", self.serial],
                capture_output=True, timeout=self.timeout, check=False,
            )
        except FileNotFoundError as e:
            raise RuntimeError(f"找不到 adb：{self.adb}") from e
        except subprocess.TimeoutExpired as e:
            raise AdbTimeout(f"adb 超时（{self.timeout}s）：connect {self.serial}") from e
        out = (p.stdout + p.stderr).decode("utf-8", "ignore").lower()
        if p.returncode == 0 and "connected to" in out:
            self._connected = True

    def run(self, *args: str, stdin: bytes | None = None, binary: bool = False):
        self.ensure()
        cmd = self.base() + list(args)
        try:
            p = subprocess.run(
                cmd, input=stdin, capture_output=True, timeout=self.timeout, check=False
            )
        except FileNotFoundError as e:
            raise RuntimeError(f"找不到 adb：{self.adb}") from e
        except subprocess.TimeoutExpired as e:
            # 仅记录 args，不记录 stdin，避免 text_secret 凭据泄漏。
            raise AdbTimeout(f"adb 超时（{self.timeout}s）：{' '.join(args)}") from e
        if p.returncode != 0:
            err = p.stderr.decode("utf-8", "ignore").strip()
            raise RuntimeError(f"adb 失败（{p.returncode}）：{' '.join(args)} → {err}")
        return p.stdout if binary else p.stdout.decode("utf-8", "ignore")


class AdbDevice:
    name = "adb"

    def __init__(
        self, serial: str | None = None, adb: str = "adb", timeout: float = 15.0,
        launch_mode: str = "standard", wait=None,
    ) -> None:
        self.serial = serial
        self.adb = adb
        self.timeout = timeout
        self.launch_mode = launch_mode
        self._wait = wait
        self._size: tuple[int, int] | None = None
        self._adb = AdbRunner(adb=adb, serial=serial, timeout=timeout)
        self._surface: TouchSurface | None = None

    # ---- 进程调用 ----

    def _run(self, *args: str, binary: bool = False):
        return self._adb.run(*args, binary=binary)

    # ---- 设备发现 ----

    @staticmethod
    def list_devices(adb: str = "adb", connect: str | None = None) -> list[str]:
        """列出已连接设备。

        `connect` 用于网络设备（模拟器）：adb daemon 会随发起它的会话消失，
        重连一次再列，否则调用方会误判成「没有设备」。
        """

        def _scan() -> list[str]:
            try:
                out = subprocess.run(
                    [adb, "devices"], capture_output=True, text=True, timeout=10, check=False
                ).stdout
            except (FileNotFoundError, subprocess.TimeoutExpired):
                return []
            found = []
            for line in out.splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "device":
                    found.append(parts[0])
            return found

        serials = _scan()
        if not serials and connect and ":" in connect:
            try:
                subprocess.run(
                    [adb, "connect", connect], capture_output=True, timeout=15, check=False
                )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                return []
            serials = _scan()
        return serials

    # ---- Device 接口 ----

    def screencap(self) -> Frame:
        t0 = time.monotonic()
        raw = self._run("exec-out", "screencap", "-p", binary=True)
        arr = np.frombuffer(raw, np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError("截图解码失败（可能是 adb 输出被污染）")
        now = time.monotonic()
        ms = int((now - t0) * 1000)
        # 截图耗时是循环节奏的真正上限，先量再谈优化（docs/maa/04-screencap.md）
        logger.debug("screencap: {}x{} {}ms", img.shape[1], img.shape[0], ms)
        return Frame(image=img, ts=now, capture_ms=ms)

    # ---- 输入 ----

    def surface(self) -> TouchSurface:
        """输入后端。优先事件级（能表达「按住再拖」），不行退回 `input`。

        事件级要能写 `/dev/input/eventN`（shell 在 input 组里才行）。
        """
        if self._surface is not None:
            return self._surface
        dev = discover_touch_device(self._adb)
        if dev is not None:
            self._surface = EvdevSurface(dev, self.size(), self._adb)
        else:
            logger.warning("没找到可写的触摸设备，退回 input 后端（无法「按住再拖」）")
            self._surface = AdbInputSurface(self._adb)
        return self._surface

    def tap(self, x: int, y: int) -> None:
        self.surface().tap(int(x), int(y))

    def drag(
        self, x1: int, y1: int, x2: int, y2: int, hold_ms: int, drag_ms: int
    ) -> None:
        self.surface().drag(
            int(x1), int(y1), int(x2), int(y2), int(hold_ms), int(drag_ms)
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

    def text(self, value: str) -> None:
        """往当前焦点输入框打字（`input text`，只支持 ASCII，空格要用 %s）。"""
        self._run("shell", "input", "text", value.replace(" ", "%s"))

    def clear_text(self, max_chars: int = 64) -> None:
        """清空当前焦点输入框：移到末尾后一次性发送多个退格，不读取或回显原内容。"""
        self._run("shell", "input", "keyevent", "123", *["67"] * max_chars)

    def text_secret(self, value: str) -> None:
        """通过标准输入向 Android shell 传递有限字符，避免宿主机命令参数含凭据。"""
        if not secret_text_supported(value):
            raise ValueError("凭据包含当前输入后端不支持的字符")
        encoded = shlex.quote(value.replace(" ", "%s"))
        self._adb.run("shell", "sh", stdin=f"input text {encoded}\n".encode("ascii"))

    def launch(self, package: str) -> None:
        if self.launch_mode == "pie64_trace":
            from lorwright.core.device.startup import launch_pie64

            launch_pie64(self._adb, package, wait=self._wait)
            return
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
