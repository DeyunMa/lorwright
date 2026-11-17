"""受控手牌观测通过真实 Engine 验证；状态序列为合成，不代表实机录像。"""

from dataclasses import replace

import numpy as np
import pytest

from lorwright.core.config import Settings
from lorwright.core.device.base import Frame
from lorwright.core.loop.engine import Engine
from lorwright.core.models import CardInHand, GameState, Layout, Rect, UIState


class Device:
    name = "synthetic"

    def __init__(self):
        self.frames = 0
        self.taps = []
        self.closed = False

    def screencap(self):
        self.frames += 1
        return Frame(np.zeros((1080, 1920, 3), np.uint8))

    def tap(self, *point):
        self.taps.append(point)

    def drag(self, *args):
        pytest.fail("手牌视图任务不能拖牌")

    def close(self):
        self.closed = True


class Router:
    layers = []

    def decide(self, state):
        pytest.fail("手牌视图任务不能调用战斗策略")


def view(expanded=False, ui=UIState.MY_TURN_IDLE):
    return GameState(ui_state=ui, hand_expanded=expanded,
                     hand=[CardInHand(0, "", -1, Rect(300, 800, 50, 50))])


def setup(monkeypatch, states, *, expired_at=None, stale_at=()):
    settings = Settings()
    settings.loop.tick_ms = 0
    settings.loop.action_timeout_s = 8
    settings.act.expand_wait_ms = 0
    device = Device()
    layout = Layout(hand_region=Rect(100, 800, 300, 200),
                    collapse_hand_point=Rect(900, 700, 20, 20))
    engine = Engine(settings, Router(), device, layout=layout)
    sequence = iter(states)
    monkeypatch.setattr(engine.parser, "load", lambda: None)
    monkeypatch.setattr(engine, "_build_state", lambda image: next(sequence))
    monkeypatch.setattr("lorwright.core.loop.engine.time.monotonic",
                        lambda: 8.0 if expired_at and device.frames >= expired_at else 0.0)
    monkeypatch.setattr(Frame, "age_s", lambda self: 10.0 if device.frames in stale_at else 0.0)
    events, reports, snapshots = [], [], []
    monkeypatch.setattr("lorwright.core.loop.engine.emit", lambda **event: events.append(event))
    monkeypatch.setattr("lorwright.core.loop.engine.report",
                        lambda *args, **kw: reports.append((args, kw)))
    monkeypatch.setattr("lorwright.core.loop.engine.save_snapshot",
                        lambda *args, **kw: snapshots.append(kw))
    return engine, device, events, reports, snapshots


@pytest.mark.parametrize("expanded", [False, True])
@pytest.mark.parametrize("already", [False, True])
def test_hand_view_verifies_two_frames_and_sends_at_most_once(monkeypatch, expanded, already):
    target = view(expanded)
    states = [target, target] if already else [view(not expanded)] * 2 + [target, target]
    engine, device, events, reports, snapshots = setup(monkeypatch, states)
    result = engine.observe_hand(expanded=expanded)
    assert (result.status, result.reason) == ("completed", "hand_view_verified")
    expected = engine.layout.hand_region if expanded else engine.layout.collapse_hand_point
    assert device.taps == ([] if already else [expected.center])
    assert device.frames == len(states)
    assert device.closed
    assert snapshots == [{"tag": "hand_view_verified"}]
    assert reports[-1][1]["inputs"] == (0 if already else 1)
    outcomes = [event for event in events if event.get("event") == "action_outcome"]
    assert [event["status"] for event in outcomes] == ([] if already else ["succeeded"])


@pytest.mark.parametrize("stale", [False, True])
def test_unknown_or_stale_target_frame_resets_confirmation(monkeypatch, stale):
    target = view(True)
    middle = target if stale else view(True, UIState.UNKNOWN)
    engine, device, _, _, _ = setup(monkeypatch, [target, middle, target, target],
                                     stale_at=(2,) if stale else ())
    assert engine.observe_hand(expanded=True, close_device=False).status == "completed"
    assert device.frames == 4
    assert not device.taps and not device.closed


@pytest.mark.parametrize("ui", [UIState.ENEMY_TURN, UIState.COMBAT_RESOLVING, UIState.BATTLE_END])
def test_hand_view_stops_without_input_outside_idle(monkeypatch, ui):
    engine, device, _, _, snapshots = setup(monkeypatch, [view(ui=ui)])
    assert engine.observe_hand(expanded=True).reason == "hand_view_unavailable"
    assert not device.taps
    assert snapshots == [{"tag": "hand_view_unavailable"}]


def test_hand_view_unknown_does_not_extend_deadline_or_repeat_input(monkeypatch):
    unknown = view(True, UIState.UNKNOWN)
    engine, device, events, _, snapshots = setup(
        monkeypatch, [view(), view(), unknown, unknown, view(True)], expired_at=5,
    )
    result = engine.observe_hand(expanded=True)
    assert result.reason == "hand_view_unverified"
    assert device.taps == [engine.layout.hand_region.center]
    assert snapshots == [{"tag": "hand_view_unverified"}]
    assert [event["status"] for event in events if event.get("event") == "action_outcome"] == ["timed_out"]


def test_hand_view_rejects_empty_expansion(monkeypatch):
    engine, device, _, _, _ = setup(monkeypatch, [replace(view(), hand=[])])
    assert engine.observe_hand(expanded=True).reason == "hand_view_unavailable"
    assert not device.taps


def test_hand_view_stale_source_cannot_supply_second_input_frame(monkeypatch):
    engine, device, _, _, _ = setup(
        monkeypatch, [view(), view(), view(), view(), view(True), view(True)], stale_at=(2,),
    )
    assert engine.observe_hand(expanded=True).status == "completed"
    assert device.frames == 6
    assert device.taps == [engine.layout.hand_region.center]
