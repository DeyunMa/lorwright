"""触摸输入：原语 + 能力声明。

设计思想取自 MAA 的输入层（只借结构，不搬代码）：

1. **后端不提供「原子手势」**。`MaaControllerFeature_UseMouseDownAndUpInsteadOfClick`
   这个能力标志的含义是：这个后端做不了「点一下」这种原子动作，上层请用
   down / move / up 自己组合。minitouch 后端连 `swipe()` 都直接返回失败，
   并提示调用方改用 `touch_down / touch_move / touch_up`。
2. **能力要显式声明**，不能假装能做到。做不到就报错，让上层改走别的路径，
   而不是发一个会被游戏吞掉的手势。
3. **坐标缩放集中在后端**，设备坐标上限从设备读，不写死。

LoR 出牌需要的正是「按住 → 停顿 → 拖 → 松手」：
`adb shell input swipe` 是原子手势，从第 0 ms 就开始插值移动，表达不了这个停顿，
所以必须走事件级后端（直接写 `/dev/input/eventN`）。
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Protocol

__all__ = [
    "AdbRunnerLike",
    "TouchDevice",
    "TouchSurface",
    "AdbInputSurface",
    "EvdevSurface",
    "parse_getevent",
    "discover_touch_device",
]


class AdbRunnerLike(Protocol):
    """`device.adb.AdbRunner` 的接口（避免 touch → adb 的反向依赖）。"""

    def run(self, *args: str, stdin: bytes | None = None, binary: bool = False): ...


@dataclass(frozen=True)
class TouchDevice:
    """一个可写的触摸输入设备。"""

    node: str          # /dev/input/event4
    name: str
    max_x: int         # ABS_MT_POSITION_X 的 max，通常 32767
    max_y: int

    def to_raw(self, x: int, y: int, width: int, height: int) -> tuple[int, int]:
        """屏幕像素 → 设备坐标。缩放只在这一处发生。"""
        rx = round(x / width * self.max_x)
        ry = round(y / height * self.max_y)
        return max(0, min(self.max_x, rx)), max(0, min(self.max_y, ry))


class TouchSurface(Protocol):
    """输入后端。`can_hold` 为 False 时 `drag()` 的停顿语义无法表达。"""

    can_hold: bool

    def tap(self, x: int, y: int) -> None: ...
    def drag(self, x1: int, y1: int, x2: int, y2: int, hold_ms: int, drag_ms: int) -> None: ...


#: 拖拽插值步数。每步 3 个 sendevent（x/y/syn），一次进程启动 ~40ms，
#: 步数多了整段手势就超过 2s，游戏会当成「长按预览」而不是拖拽。
_DRAG_STEPS = 6

_ABS_LINE = re.compile(r"(ABS_MT_POSITION_[XY])\s*:.*?max\s+(-?\d+)")
_DEV_LINE = re.compile(r"^add device \d+: (/dev/input/event\d+)")
_NAME_LINE = re.compile(r'^\s*name:\s+"(.+)"')


def parse_getevent(text: str) -> list[TouchDevice]:
    """从 `getevent -pl` 输出里挑出触摸设备（有 ABS_MT_POSITION_X/Y 的那些）。"""
    found: list[TouchDevice] = []
    node = name = None
    maxes: dict[str, int] = {}

    def flush() -> None:
        if node and "ABS_MT_POSITION_X" in maxes and "ABS_MT_POSITION_Y" in maxes:
            found.append(
                TouchDevice(
                    node=node,
                    name=name or "",
                    max_x=maxes["ABS_MT_POSITION_X"],
                    max_y=maxes["ABS_MT_POSITION_Y"],
                )
            )

    for line in text.splitlines():
        dev = _DEV_LINE.match(line.strip())
        if dev:
            flush()
            node, name, maxes = dev.group(1), None, {}
            continue
        nm = _NAME_LINE.match(line)
        if nm:
            name = nm.group(1)
            continue
        abs_m = _ABS_LINE.search(line)
        if abs_m:
            maxes[abs_m.group(1)] = int(abs_m.group(2))
    flush()
    return found


class AdbInputSurface:
    """`adb shell input` 后端：只有原子手势，**不能停顿**。

    能用就用它（简单、无副作用），但表达不了「按住再拖」。
    """

    can_hold = False

    def __init__(self, runner: AdbRunnerLike) -> None:
        self.runner = runner

    def tap(self, x: int, y: int) -> None:
        self.runner.run("shell", "input", "tap", str(x), str(y))

    def drag(self, x1: int, y1: int, x2: int, y2: int, hold_ms: int, drag_ms: int) -> None:
        # 停顿无法表达：只能把总时长给 swipe。需要停顿请换 EvdevSurface。
        self.runner.run(
            "shell", "input", "swipe",
            str(x1), str(y1), str(x2), str(y2), str(max(1, drag_ms)),
        )


class EvdevSurface:
    """事件级后端：一次 adb 调用把整个手势写成设备端脚本。

    为什么不逐事件调用 adb：每次 `adb shell` 都是新进程，进程退出时手势就断了。
    所以整个 down → 停顿 → move×N → up 必须作为一段设备端脚本一次执行。

    事件序列按 Linux 多点触控协议 B（与 minitouch 同类）：
        ABS_MT_SLOT, ABS_MT_TRACKING_ID, BTN_TOUCH(1),
        [ABS_MT_TOUCH_MAJOR / WIDTH_MAJOR / PRESSURE —— 设备支持才发],
        ABS_MT_POSITION_X/Y, SYN_REPORT
    抬手时 TRACKING_ID = -1。
    """

    can_hold = True

    def __init__(
        self,
        device: TouchDevice,
        screen: tuple[int, int],
        runner: AdbRunnerLike,
    ) -> None:
        self.device = device
        self.screen = screen
        self.runner = runner
        self._tracking_id = 100

    # --- 事件流 ---------------------------------------------------------

    def _ev(self, etype: int, code: int, value: int) -> str:
        return f"sendevent {self.device.node} {etype} {code} {value}"

    def _seq_down(self, x: int, y: int) -> list[str]:
        w, h = self.screen
        rx, ry = self.device.to_raw(x, y, w, h)
        self._tracking_id = self._tracking_id % 60000 + 1
        return [
            self._ev(3, 47, 0),                    # ABS_MT_SLOT 0
            self._ev(3, 57, self._tracking_id),    # ABS_MT_TRACKING_ID
            self._ev(1, 330, 1),                   # BTN_TOUCH
            self._ev(3, 53, rx),                   # ABS_MT_POSITION_X
            self._ev(3, 54, ry),                   # ABS_MT_POSITION_Y
            self._ev(0, 0, 0),                     # SYN_REPORT
        ]

    def _seq_move(self, x: int, y: int) -> list[str]:
        # 不再每次重发 ABS_MT_SLOT：整个手势只用 slot 0，协议 B 下选中一次就够。
        # 每个 sendevent 是一次进程启动（~40ms），事件数直接决定手势时长。
        w, h = self.screen
        rx, ry = self.device.to_raw(x, y, w, h)
        return [
            self._ev(3, 53, rx),
            self._ev(3, 54, ry),
            self._ev(0, 0, 0),
        ]

    def _seq_up(self) -> list[str]:
        return [
            self._ev(3, 57, -1),                   # TRACKING_ID = -1 → 抬手
            self._ev(1, 330, 0),                   # BTN_TOUCH
            self._ev(0, 0, 0),
        ]

    def build_script(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        hold_ms: int,
        drag_ms: int,
        steps: int = _DRAG_STEPS,
    ) -> str:
        """把一次「按住 → 停顿 → 拖 → 松手」拼成设备端 shell 脚本。

        时长上限是硬约束：整段手势要落在 2s 以内，否则游戏把它当长按预览
        （卡片放大但不跟着手指走），松手后卡片回手牌。
        """
        steps = max(1, steps)
        step_sleep = max(0.004, drag_ms / 1000 / steps)
        lines = ["#!/system/bin/sh", *self._seq_down(x1, y1), f"sleep {hold_ms / 1000:.3f}"]
        for i in range(1, steps + 1):
            x = x1 + (x2 - x1) * i // steps
            y = y1 + (y2 - y1) * i // steps
            lines += [*self._seq_move(x, y), f"sleep {step_sleep:.3f}"]
        lines += ["sleep 0.10", *self._seq_up()]
        return "\n".join(lines) + "\n"

    def _shell(self, script: str) -> None:
        # 脚本经 stdin 送进去，避免命令行转义（Windows 上尤其容易出错）。
        # 返回码由 runner 检查：写不进 /dev/input 必须报错，不能静默失败。
        self.runner.run("shell", "sh", stdin=script.encode())

    # --- TouchSurface ---------------------------------------------------

    def tap(self, x: int, y: int) -> None:
        script = "\n".join(
            ["#!/system/bin/sh", *self._seq_down(x, y), "sleep 0.08", *self._seq_up()]
        )
        self._shell(script + "\n")

    def drag(self, x1: int, y1: int, x2: int, y2: int, hold_ms: int, drag_ms: int) -> None:
        self._shell(self.build_script(x1, y1, x2, y2, hold_ms, drag_ms))


def discover_touch_device(runner: AdbRunnerLike) -> TouchDevice | None:
    """找可写的触摸设备。

    `/dev/input/eventN` 写不写得了取决于设备（shell 在 input 组里才行）。
    找不到就返回 None，调用方退回 `AdbInputSurface`。
    """
    try:
        text = runner.run("shell", "getevent", "-pl")
    except (OSError, subprocess.SubprocessError, RuntimeError):
        return None
    devices = parse_getevent(text)
    if not devices:
        return None
    # 优先带 touch 字样的设备（BlueStacks 是 "BlueStacks Virtual Touch"）
    devices.sort(key=lambda d: ("touch" not in d.name.lower(), d.name))
    return devices[0]
