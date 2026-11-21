"""设备抽象：用假设备验证 Engine 不依赖真实 adb。"""

from __future__ import annotations

import numpy as np

from lorwright.core.device.base import Frame
from lorwright.core.loop.engine import Engine


class FakeDevice:
    name = "fake"

    def __init__(self, size=(1920, 1080), ts: float = 0.0) -> None:
        self._size = size
        self.taps: list[tuple[int, int]] = []
        self._frame = Frame(image=np.zeros((size[1], size[0], 3), np.uint8), ts=ts)

    def screencap(self) -> Frame:
        return self._frame

    def tap(self, x: int, y: int) -> None:
        self.taps.append((x, y))

    def drag(self, x1, y1, x2, y2, hold_ms, drag_ms) -> None:
        pass

    def size(self) -> tuple[int, int]:
        return self._size

    def close(self) -> None:
        pass


class _Router:
    layers: list = []
    calls = 0

    def decide(self, state):
        from lorwright.core.decide.router import RouteResult
        from lorwright.core.models import Action, ActionType

        type(self).calls += 1
        return RouteResult(Action(type=ActionType.CONFIRM), "test")

    def coverage(self):
        return {}


def test_engine_uses_device(monkeypatch, tmp_path) -> None:
    from lorwright.core.config import Settings
    from lorwright.core.models import GameState, Layout, Rect, UIState

    settings = Settings()
    settings.layout.end_turn = [10, 10, 20, 20]
    settings.layout.play_area = [0, 0, 10, 10]
    settings.loop.tick_ms = 0

    dev = FakeDevice()
    layout = Layout(end_turn=Rect(10, 10, 20, 20), play_area=Rect(0, 0, 10, 10))

    engine = Engine(settings, _Router(), dev, layout=layout)
    monkeypatch.setattr(engine.parser, "parse", lambda image: GameState(
        ui_state=UIState.MULLIGAN, mulligan_selected=(False, False, False, False),
    ))
    engine.run(max_ticks=3)

    # 两帧稳定后只发一次；第三帧仍未看到结果，不能重复点击。
    assert dev.taps == [(20, 20)]


def test_engine_scales_coordinates_to_device_resolution(monkeypatch) -> None:
    """非设计尺寸时，动作坐标要按比例换成设备像素（分辨率解耦）。"""
    from lorwright.core.config import Settings
    from lorwright.core.models import GameState, Layout, Rect, UIState

    settings = Settings()
    settings.layout.end_turn = [10, 10, 20, 20]
    settings.loop.tick_ms = 0

    dev = FakeDevice(size=(960, 540))
    layout = Layout(end_turn=Rect(10, 10, 20, 20))
    engine = Engine(settings, _Router(), dev, layout=layout)
    monkeypatch.setattr(engine.parser, "parse", lambda image: GameState(
        ui_state=UIState.MULLIGAN, mulligan_selected=(False, False, False, False),
    ))
    engine.run(max_ticks=2)

    # 设计坐标 (20,20) → 设备像素 (10,10)
    assert dev.taps == [(10, 10)]


def test_stale_frame_is_not_acted_on(monkeypatch) -> None:
    """帧太旧就不动：截图+决策耗时过长时，点会落在已经变了的画面上。"""
    from lorwright.core.config import Settings
    from lorwright.core.models import GameState, Layout, Rect, UIState

    settings = Settings()
    settings.loop.tick_ms = 0
    settings.loop.max_frame_age_s = 1.0

    monkeypatch.setattr("lorwright.core.loop.engine.time.monotonic", lambda: 100.0)
    dev = FakeDevice(ts=90.0)
    engine = Engine(
        settings, _Router(), dev, layout=Layout(end_turn=Rect(10, 10, 20, 20))
    )
    monkeypatch.setattr(engine.parser, "parse", lambda image: GameState(
        ui_state=UIState.MULLIGAN, mulligan_selected=(False, False, False, False),
    ))
    engine.run(max_ticks=3)

    assert dev.taps == []
    assert engine._skipped_stale == 3


def test_fake_device_size() -> None:
    dev = FakeDevice(size=(1156, 2510))
    assert dev.size() == (1156, 2510)
    assert dev.screencap().width == 1156


def test_adb_ensure_marks_connected_only_on_success(monkeypatch) -> None:
    import subprocess

    from lorwright.core.device.adb import AdbRunner

    responses = iter([
        subprocess.CompletedProcess(["adb"], 0, stdout=b"unable to connect to 127.0.0.1:5555\n", stderr=b""),
        subprocess.CompletedProcess(["adb"], 0, stdout=b"already connected to 127.0.0.1:5555\n", stderr=b""),
    ])
    calls: list[list[str]] = []

    def _fake_run(cmd, **kwargs):
        calls.append(cmd)
        return next(responses)

    monkeypatch.setattr(subprocess, "run", _fake_run)
    runner = AdbRunner(adb="adb", serial="127.0.0.1:5555")
    runner.ensure()
    assert runner._connected is False
    runner.ensure()
    assert runner._connected is True
    runner.ensure()
    assert len(calls) == 2


def test_adb_timeout_is_wrapped_without_leaking_stdin(monkeypatch) -> None:
    import subprocess

    import pytest

    from lorwright.core.device.adb import AdbRunner, AdbTimeout

    def _timeout(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout", 15))

    monkeypatch.setattr(subprocess, "run", _timeout)
    runner = AdbRunner(adb="adb", serial="127.0.0.1:5555", timeout=5.0)
    with pytest.raises(AdbTimeout, match="connect 127.0.0.1:5555"):
        runner.ensure()
    assert runner._connected is False

    runner._connected = True
    with pytest.raises(AdbTimeout) as exc:
        runner.run("shell", "sh", stdin=b"input text super-secret-password\n")
    assert "super-secret-password" not in str(exc.value)
    assert "shell sh" in str(exc.value)


def test_adb_list_devices_handles_connect_timeout(monkeypatch) -> None:
    import subprocess

    from lorwright.core.device.adb import AdbDevice

    def _fake_run(cmd, **kwargs):
        if "devices" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="List of devices attached\n\n", stderr="")
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=15)

    monkeypatch.setattr(subprocess, "run", _fake_run)
    assert AdbDevice.list_devices(adb="adb", connect="127.0.0.1:5555") == []
