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


def _engine(
    device: FakeDevice,
    action: Action,
    recovery: RecoveryPolicy,
    allow_client_restart: bool = False,
) -> Engine:
    settings = Settings()
    settings.loop.tick_ms = 0
    settings.loop.stuck_threshold = 1
    settings.loop.action_timeout_s = 0.0
    settings.recovery.allow_client_restart = allow_client_restart
    layout = Layout(end_turn=Rect(1200, 600, 60, 60))
    return Engine(
        settings,
        Router([FixedLayer(action)]),
        device,
        layout=layout,
        ui_detector=UIStateDetector(root="__missing__", action_button=layout.end_turn),
        recovery=recovery,
    )


def test_stuck_retries_then_stops_instead_of_restarting_client() -> None:
    """重启客户端会掉登录态，默认配置下不能拿它当恢复手段。"""
    dev = FakeDevice()
    engine = _engine(
        dev,
        Action(type=ActionType.END_TURN),
        RecoveryPolicy(retry_limit=1, battle_limit=1, client_limit=1),
    )

    engine.run(max_ticks=20)

    # 重试重放了一次点击，然后走到 restart_battle → 拒绝重启 → 停
    assert len(dev.taps) >= 2
    assert dev.restarts == []
    assert dev.closed


def test_client_restart_only_when_explicitly_allowed() -> None:
    dev = FakeDevice()
    engine = _engine(
        dev,
        Action(type=ActionType.END_TURN),
        RecoveryPolicy(retry_limit=1, battle_limit=1, client_limit=1),
        allow_client_restart=True,
    )

    engine.run(max_ticks=20)

    # restart_battle 退化为重启客户端，第二次又重启，最后耗尽停下
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
