"""设备抽象：用假设备验证 Engine 不依赖真实 adb。"""

from __future__ import annotations

import numpy as np

from lorwright.device.base import Frame
from lorwright.loop.engine import Engine


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
        from lorwright.models import Action, ActionType

        type(self).calls += 1
        return type("R", (), {"action": Action(type=ActionType.END_TURN), "layer": "test"})()

    def coverage(self):
        return {}


def test_engine_uses_device(monkeypatch, tmp_path) -> None:
    from lorwright.config import Settings
    from lorwright.models import Layout, Rect

    settings = Settings()
    settings.layout.end_turn = [10, 10, 20, 20]
    settings.layout.play_area = [0, 0, 10, 10]
    settings.loop.tick_ms = 0

    dev = FakeDevice()
    layout = Layout(end_turn=Rect(10, 10, 20, 20), play_area=Rect(0, 0, 10, 10))

    engine = Engine(settings, _Router(), dev, layout=layout)
    engine.run(max_ticks=2)

    # 结束回合按钮中心 = (20, 20)，跑 2 轮应点 2 次
    assert dev.taps == [(20, 20), (20, 20)]


def test_engine_scales_coordinates_to_device_resolution() -> None:
    """非设计尺寸时，动作坐标要按比例换成设备像素（分辨率解耦）。"""
    from lorwright.config import Settings
    from lorwright.models import Layout, Rect

    settings = Settings()
    settings.layout.end_turn = [10, 10, 20, 20]
    settings.loop.tick_ms = 0

    dev = FakeDevice(size=(960, 540))
    layout = Layout(end_turn=Rect(10, 10, 20, 20))
    Engine(settings, _Router(), dev, layout=layout).run(max_ticks=1)

    # 设计坐标 (20,20) → 设备像素 (10,10)
    assert dev.taps == [(10, 10)]


def test_stale_frame_is_not_acted_on() -> None:
    """帧太旧就不动：截图+决策耗时过长时，点会落在已经变了的画面上。"""
    import time

    from lorwright.config import Settings
    from lorwright.models import Layout, Rect

    settings = Settings()
    settings.loop.tick_ms = 0
    settings.loop.max_frame_age_s = 1.0

    dev = FakeDevice(ts=time.time() - 10)
    engine = Engine(
        settings, _Router(), dev, layout=Layout(end_turn=Rect(10, 10, 20, 20))
    )
    engine.run(max_ticks=3)

    assert dev.taps == []
    assert engine._skipped_stale == 3


def test_fake_device_size() -> None:
    dev = FakeDevice(size=(1156, 2510))
    assert dev.size() == (1156, 2510)
    assert dev.screencap().width == 1156
