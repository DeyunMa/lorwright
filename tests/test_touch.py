"""触摸输入：设备发现、坐标缩放、手势脚本。

不开游戏、不碰 adb —— 只验证拼出来的事件流。
"""

from __future__ import annotations

from lorwright.device.touch import (
    EvdevSurface,
    TouchDevice,
    parse_getevent,
)

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
    surface = EvdevSurface(dev, (1920, 1080))
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


def test_every_move_report_selects_slot() -> None:
    """协议 B 要求每次上报前重新选中 slot（0），漏了移动事件会被忽略。"""
    lines = _script(steps=3)
    xs = [i for i, ln in enumerate(lines) if " 3 53 " in ln]
    # 第一个是按下时的初始坐标，后面每个都是移动
    for i in xs[1:]:
        assert lines[i - 1].endswith(" 3 47 0"), f"移动前缺 ABS_MT_SLOT：{lines[i - 1]}"
