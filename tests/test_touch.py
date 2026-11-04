"""触摸输入：设备发现、坐标缩放、手势脚本。

不开游戏、不碰 adb —— 只验证拼出来的事件流。
"""

from __future__ import annotations

from lorwright.device.touch import (
    EvdevSurface,
    TouchDevice,
    parse_getevent,
)


class _Runner:
    """假的 adb 入口：记录脚本，不真跑。"""

    def __init__(self) -> None:
        self.scripts: list[str] = []

    def run(self, *args, stdin=None, binary=False):
        if stdin:
            self.scripts.append(stdin.decode())
        return ""

#: 真机上 `adb shell getevent -pl` 的片段（BlueStacks Pie64）。
GETEVENT = """\
add device 1: /dev/input/event6
  name:     "Android Power Button"
  events:
    KEY (0001): KEY_POWER             KEY_WAKEUP
add device 4: /dev/input/event4
  name:     "BlueStacks Virtual Touch"
  events:
    KEY (0001): BTN_MOUSE             BTN_RIGHT             BTN_MIDDLE            BTN_TOUCH
    ABS (0003): ABS_MT_SLOT           : value 0, min 0, max 15, fuzz 0, flat 0, resolution 0
                ABS_MT_POSITION_X     : value 0, min 0, max 32767, fuzz 0, flat 0, resolution 0
                ABS_MT_POSITION_Y     : value 0, min 0, max 32767, fuzz 0, flat 0, resolution 0
                ABS_MT_TRACKING_ID    : value 0, min 0, max 65535, fuzz 0, flat 0, resolution 0
add device 5: /dev/input/event2
  name:     "AT Translated Set 2 keyboard"
  events:
    KEY (0001): KEY_ESC               KEY_1
"""


def test_parse_getevent_picks_touch_device() -> None:
    devices = parse_getevent(GETEVENT)
    assert len(devices) == 1
    dev = devices[0]
    assert dev.node == "/dev/input/event4"
    assert dev.name == "BlueStacks Virtual Touch"
    assert (dev.max_x, dev.max_y) == (32767, 32767)


def test_parse_getevent_ignores_devices_without_mt_axes() -> None:
    assert parse_getevent('add device 1: /dev/input/event6\n  name: "Power"\n') == []


def test_to_raw_scales_and_clamps() -> None:
    dev = TouchDevice("/dev/input/event4", "touch", 32767, 32767)
    assert dev.to_raw(0, 0, 1920, 1080) == (0, 0)
    assert dev.to_raw(1920, 1080, 1920, 1080) == (32767, 32767)
    # 越界要夹住，否则 sendevent 会发非法值
    assert dev.to_raw(-10, 5000, 1920, 1080) == (0, 32767)


def _script(**kw) -> list[str]:
    dev = TouchDevice("/dev/input/event4", "touch", 32767, 32767)
    surface = EvdevSurface(dev, (1920, 1080), _Runner())
    script = surface.build_script(
        kw.get("x1", 1482), kw.get("y1", 1015),
        kw.get("x2", 960), kw.get("y2", 900),
        kw.get("hold_ms", 300), kw.get("drag_ms", 800),
        kw.get("steps", 4),
    )
    return script.strip().splitlines()


def test_script_holds_before_moving() -> None:
    """停顿必须在第一次 MOVE 之前 —— 这就是 `input swipe` 做不到的那件事。"""
    lines = _script(hold_ms=300)
    down = next(i for i, ln in enumerate(lines) if " 1 330 1" in ln)      # BTN_TOUCH 按下
    hold = next(i for i, ln in enumerate(lines) if ln.startswith("sleep 0.300"))
    first_move = next(i for i, ln in enumerate(lines) if " 3 53 " in ln and i > hold)
    assert down < hold < first_move


def test_script_releases_tracking_id() -> None:
    lines = _script()
    assert any(ln.endswith(" 3 57 -1") for ln in lines), "抬手必须发 TRACKING_ID=-1"
    assert any(ln.endswith(" 1 330 0") for ln in lines), "抬手必须发 BTN_TOUCH=0"


def test_script_moves_in_steps_and_ends_on_target() -> None:
    lines = _script(x1=1482, y1=1015, x2=960, y2=900, steps=4)
    moves = [ln for ln in lines if " 3 53 " in ln]
    # 4 步移动 + 1 次按下时的初始坐标
    assert len(moves) == 5
    last_x = int(moves[-1].split()[-1])
    expected = round(960 / 1920 * 32767)
    assert abs(last_x - expected) <= 2


def test_gesture_stays_short_enough() -> None:
    """整段手势要 < 2s：每个 sendevent 是一次进程启动（~40ms）。

    事件数一多手势就拖到 3s 以上，LoR 会当成「长按预览」——卡片放大但不
    跟手，松手回手牌。这条盯的是事件数，不是逻辑。
    """
    from lorwright.device.touch import _DRAG_STEPS

    lines = _script(steps=_DRAG_STEPS)
    events = [ln for ln in lines if ln.startswith("sendevent")]
    # 按下 6 + 每步 3 + 抬手 3；按 40ms/次估算总时长
    assert len(events) <= 30, f"事件太多：{len(events)}"
    assert len(events) * 0.040 + 0.120 + 0.600 < 2.0


def test_slot_selected_once_at_down() -> None:
    """整个手势只用 slot 0，按下时选一次即可（协议 B）。"""
    lines = _script(steps=3)
    slots = [ln for ln in lines if ln.endswith(" 3 47 0")]
    assert len(slots) == 1, f"ABS_MT_SLOT 只该发一次，实际 {len(slots)}"


def test_tap_goes_through_runner() -> None:
    """输入必须走统一的 adb 入口：绕过它就会丢掉重连和返回码检查。"""
    runner = _Runner()
    dev = TouchDevice(node="/dev/input/event4", name="t", max_x=32767, max_y=32767)
    surface = EvdevSurface(dev, (1920, 1080), runner)

    surface.tap(100, 200)

    assert len(runner.scripts) == 1
    script = runner.scripts[0]
    assert "sendevent /dev/input/event4 3 53 1707" in script
    assert "sendevent /dev/input/event4 3 54 6068" in script


def test_adb_runner_raises_on_failure(monkeypatch) -> None:
    """adb 返回非 0 必须抛错。以前输入后端把返回码丢掉，点失败也报成功。"""
    import subprocess

    from lorwright.device.adb import AdbRunner

    class _P:
        returncode = 1
        stdout = b""
        stderr = b"error: no devices/emulators found"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _P())
    runner = AdbRunner(serial=None)

    try:
        runner.run("shell", "input", "tap", "1", "2")
    except RuntimeError as e:
        assert "no devices" in str(e)
    else:
        raise AssertionError("应当抛 RuntimeError")
