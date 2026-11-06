"""回放设备：用历史截图跑真实主循环。"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from lorwright.config import Settings
from lorwright.device.replay import ReplayDevice
from lorwright.loop.engine import Engine
from lorwright.models import Action, ActionType, Layout, Rect


def _png(path: Path, color: int) -> None:
    img = np.full((1080, 1920, 3), color, np.uint8)
    cv2.imwrite(str(path), img)


def test_replay_emits_frames_in_order(tmp_path: Path) -> None:
    _png(tmp_path / "001.png", 10)
    _png(tmp_path / "002.png", 20)
    dev = ReplayDevice(tmp_path)
    assert int(dev.screencap().image.mean()) == 10
    assert int(dev.screencap().image.mean()) == 20
    # 超出末尾后停在最后一帧，便于单帧回放
    assert int(dev.screencap().image.mean()) == 20
    assert dev.size() == (1920, 1080)


def test_replay_records_actions(tmp_path: Path) -> None:
    _png(tmp_path / "001.png", 0)
    dev = ReplayDevice(tmp_path)
    dev.tap(1, 2)
    dev.drag(1, 2, 3, 4, 300, 800)
    assert dev.taps == [(1, 2)]
    assert dev.drags == [(1, 2, 3, 4, 300, 800)]


def test_replay_rejects_empty_dir(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        ReplayDevice(tmp_path)


class _Router:
    layers: list = []

    def decide(self, state):
        return type(
            "R", (), {"action": Action(type=ActionType.END_TURN), "layer": "test"}
        )()

    def coverage(self):
        return {}


def test_engine_does_not_click_unknown_replay_even_with_unsafe_router(tmp_path: Path) -> None:
    _png(tmp_path / "001.png", 0)
    settings = Settings()
    settings.loop.tick_ms = 0
    settings.layout.end_turn = [10, 10, 20, 20]
    dev = ReplayDevice(tmp_path)
    engine = Engine(
        settings, _Router(), dev, layout=Layout(end_turn=Rect(10, 10, 20, 20))
    )

    engine.run(max_ticks=2)

    assert dev.taps == []
