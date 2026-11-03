"""主循环接上恢复策略：卡住 → 重试 → 重启客户端 → 停。

用假设备跑真实 Engine，不碰游戏、不碰 adb。
"""

from __future__ import annotations

import numpy as np

from lorwright.config import Settings
from lorwright.decide.router import Router
from lorwright.device.base import Frame
from lorwright.loop.engine import Engine
from lorwright.loop.recovery import RecoveryPolicy
from lorwright.models import Action, ActionType, Layout, Rect, UIState
from lorwright.perceive.cards import CardLibrary
from lorwright.perceive.ui_state import UIStateDetector


class FakeDevice:
    name = "fake"

    def __init__(self) -> None:
        self.taps: list[tuple[int, int]] = []
        self.swipes: list[tuple[int, int, int, int]] = []
        self.restarts: list[str] = []
        self.closed = False
        self._img = np.zeros((720, 1280, 3), dtype=np.uint8)

    def screencap(self) -> Frame:
        return Frame(image=self._img.copy())

    def tap(self, x: int, y: int) -> None:
        self.taps.append((x, y))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int = 300) -> None:
        self.swipes.append((x1, y1, x2, y2))

    def size(self) -> tuple[int, int]:
        return (1280, 720)

    def restart_app(self, package: str) -> None:
        self.restarts.append(package)

    def close(self) -> None:
        self.closed = True


class FixedLayer:
    """永远返回同一个动作，用来制造「画面不变」。"""

    def __init__(self, action: Action) -> None:
        self.action = action
        self.name = "fixed"

    def decide(self, state) -> Action:
        return self.action


def _engine(device: FakeDevice, action: Action, recovery: RecoveryPolicy) -> Engine:
    settings = Settings()
    settings.loop.tick_ms = 0
    settings.loop.stuck_threshold = 1
    settings.loop.action_timeout_s = 0.0
    layout = Layout(end_turn=Rect(1200, 600, 60, 60))
    return Engine(
        settings,
        Router([FixedLayer(action)]),
        device,
        layout=layout,
        ui_detector=UIStateDetector(root="__missing__", action_button=layout.end_turn),
        cards=CardLibrary(root="__missing__"),
        recovery=recovery,
    )


def test_stuck_escalates_and_stops() -> None:
    dev = FakeDevice()
    engine = _engine(
        dev,
        Action(type=ActionType.END_TURN),
        RecoveryPolicy(retry_limit=1, battle_limit=1, client_limit=1),
    )

    engine.run(max_ticks=20)

    # 重试重放了一次点击，然后两级重启各一次，最后停下
    assert len(dev.taps) >= 2
    assert dev.restarts == ["com.riotgames.legendsofruneterra"] * 2
    assert engine.recovery.exhausted
    assert dev.closed


def test_no_op_never_triggers_recovery() -> None:
    """对手回合一直 NO_OP：跑满 tick 也不能触发恢复。"""
    dev = FakeDevice()
    engine = _engine(
        dev,
        Action(type=ActionType.NO_OP),
        RecoveryPolicy(retry_limit=1, battle_limit=1, client_limit=1),
    )

    engine.run(max_ticks=12)

    assert dev.taps == []
    assert dev.restarts == []
    assert not engine.recovery.exhausted
    assert dev.closed


def test_stable_state_under_no_op_is_unknown_not_stuck() -> None:
    dev = FakeDevice()
    engine = _engine(dev, Action(type=ActionType.NO_OP), RecoveryPolicy())
    state = engine._build_state(dev.screencap().image)
    assert state.ui_state is UIState.UNKNOWN
