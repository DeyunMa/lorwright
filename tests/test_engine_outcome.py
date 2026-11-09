"""合成状态序列驱动真实 Engine，验证输入等待与安全停机。不是实机操作录像。"""

import time
from dataclasses import replace

import numpy as np

from lorwright.config import Settings
from lorwright.decide.router import RouteResult
from lorwright.device.base import Frame
from lorwright.loop.engine import Engine
from lorwright.models import (
    Action,
    ActionType,
    CardInHand,
    GameState,
    Layout,
    Reading,
    Rect,
    UIState,
)


class Device:
    name = "synthetic"

    def __init__(self):
        self.taps = []
        self.drags = []
        self.closed = False
        self.frames = 0

    def size(self):
        return (1920, 1080)

    def screencap(self):
        self.frames += 1
        return Frame(image=np.zeros((1080, 1920, 3), np.uint8))

    def tap(self, *point):
        self.taps.append(point)

    def drag(self, *args):
        self.drags.append(args)

    def close(self):
        self.closed = True


class Router:
    layers = []

    def __init__(self, actions):
        self.actions = iter(actions)
        self.calls = 0

    def decide(self, state):
        self.calls += 1
        return RouteResult(next(self.actions), "synthetic")

    def coverage(self):
        return {}


def ready(**kwargs):
    values = dict(
        ui_state=UIState.MY_TURN_IDLE, mana=3,
        readings={"mana": Reading(3, 0), "nexus_hp": Reading(20, 0),
                  "enemy_nexus_hp": Reading(20, 0)},
    )
    values.update(kwargs)
    return GameState(**values)


def engine_for(monkeypatch, states, actions, timeout=8):
    settings = Settings()
    settings.loop.tick_ms = 0
    settings.loop.action_timeout_s = timeout
    settings.act.tap_wait_ms = settings.act.expand_wait_ms = settings.act.drag_wait_ms = 0
    device = Device()
    router = Router(actions)
    layout = Layout(end_turn=Rect(10, 10, 20, 20), hand_region=Rect(100, 800, 300, 200),
                    play_area=Rect(500, 500, 100, 100))
    engine = Engine(settings, router, device, layout=layout)
    sequence = iter(states)
    monkeypatch.setattr(engine.parser, "load", lambda: None)
    monkeypatch.setattr(engine, "_build_state", lambda image: next(sequence))
    events, snapshots = [], []
    monkeypatch.setattr("lorwright.loop.engine.emit", lambda **event: events.append(event))
    monkeypatch.setattr("lorwright.loop.engine.save_snapshot", lambda *args, **kw: snapshots.append(kw))
    return engine, device, router, events, snapshots


def test_expand_then_drag_waits_for_result_without_repeating_input(monkeypatch):
    card = CardInHand(0, "", 1, Rect(300, 800, 50, 50))
    collapsed = ready(hand=[card])
    expanded = replace(collapsed, hand_expanded=True)
    paid = replace(expanded, hand=[], mana=2, readings={**expanded.readings, "mana": Reading(2, 0)})
    engine, device, router, events, _ = engine_for(
        monkeypatch, [collapsed, expanded, expanded, paid],
        [Action(ActionType.PLAY_CARD, 0), Action(ActionType.PLAY_CARD, 0), Action(ActionType.NO_OP)],
    )
    engine.run(max_ticks=4)
    assert len(device.taps) == 1
    assert len(device.drags) == 1
    assert router.calls == 3
    assert [e["status"] for e in events if e.get("event") == "action_outcome"] == [
        "succeeded", "waiting", "succeeded",
    ]
    assert device.closed


def test_successful_outcome_is_delivered_to_policy_once(monkeypatch):
    card = CardInHand(0, "牌", 1, Rect(300, 800, 50, 50))
    before = ready(hand=[card], hand_expanded=True)
    after = replace(before, hand=[], mana=2, readings={**before.readings, "mana": Reading(2, 0)})
    action = Action(ActionType.PLAY_CARD, 0)
    engine, _, router, _, _ = engine_for(
        monkeypatch, [before, before, after], [action, Action(ActionType.NO_OP)],
    )

    class Observer:
        def __init__(self):
            self.outcomes = []

        def on_action_outcome(self, action, before, after):
            self.outcomes.append((action, before, after))

    observer = Observer()
    router.layers = [observer]
    engine.run(max_ticks=3)
    assert observer.outcomes == [(action, before, after)]


def test_timeout_saves_evidence_and_stops_without_retry_or_restart(monkeypatch):
    state = ready(ui_state=UIState.MULLIGAN)
    engine, device, router, events, snapshots = engine_for(
        monkeypatch, [state, state], [Action(ActionType.CONFIRM)], timeout=0,
    )
    engine.run(max_ticks=10)
    assert router.calls == 1
    assert device.taps == [(20, 20)]
    assert snapshots == [{"tag": "action_timeout"}]
    assert any(e.get("status") == "timed_out" for e in events)
    assert device.closed and device.frames == 2


def test_old_readings_block_decision_then_resume_when_fresh(monkeypatch):
    current = ready()
    stale = replace(current, readings={**current.readings, "mana": Reading(3, 1)})
    engine, device, router, events, _ = engine_for(
        monkeypatch, [stale, current], [Action(ActionType.END_TURN)],
    )
    engine.run(max_ticks=2)
    assert router.calls == 1
    assert len(device.taps) == 1
    assert events[0]["layer"] == "unreadable"
    assert events[0]["readings"]["mana"] == {"value": 3, "age_frames": 1}


def test_zero_mana_unreadable_still_allows_ending_turn(monkeypatch):
    # 同一段优先权中先确认 0 费，再连续 5 帧读不出时允许结束回合。
    state = ready(
        mana=0,
        readings={"mana": Reading(None, None), "nexus_hp": Reading(20, 0),
                  "enemy_nexus_hp": Reading(20, 0)},
    )
    confirmed = replace(state, readings={**state.readings, "mana": Reading(0, 0)})
    engine, device, router, _, _ = engine_for(
        monkeypatch, [confirmed, *([state] * 5)],
        [Action(ActionType.NO_OP), Action(ActionType.END_TURN)], timeout=0,
    )
    engine.run(max_ticks=6)
    assert router.calls == 2
    assert len(device.taps) == 1


def test_unreadable_mana_is_not_assumed_zero_without_confirmation(monkeypatch):
    state = ready(readings={"mana": Reading(None, None), "nexus_hp": Reading(20, 0)})
    engine, device, router, _, _ = engine_for(
        monkeypatch, [state] * 5, [Action(ActionType.END_TURN)],
    )
    engine.run(max_ticks=5)
    assert router.calls == 0
    assert device.taps == []


def test_zero_mana_confirmation_does_not_cross_priority_change(monkeypatch):
    confirmed = ready(mana=0, readings={"mana": Reading(0, 0), "nexus_hp": Reading(20, 0)})
    enemy = ready(ui_state=UIState.ENEMY_TURN)
    unreadable = ready(readings={"mana": Reading(None, None), "nexus_hp": Reading(20, 0)})
    engine, device, router, _, _ = engine_for(
        monkeypatch, [confirmed, enemy, *([unreadable] * 5)],
        [Action(ActionType.NO_OP), Action(ActionType.NO_OP), Action(ActionType.END_TURN)],
    )
    engine.run(max_ticks=7)
    assert router.calls == 2
    assert device.taps == []


def test_unknown_state_never_reaches_a_strategy(monkeypatch):
    engine, device, router, _, _ = engine_for(monkeypatch, [GameState()], [])
    engine.run(max_ticks=1)
    assert router.calls == 0
    assert device.taps == []


def test_frame_that_expires_during_decision_is_not_executed(monkeypatch):
    engine, device, router, events, _ = engine_for(
        monkeypatch, [ready()], [Action(ActionType.END_TURN)],
    )
    frame = device.screencap()
    frame.ts = time.time()
    monkeypatch.setattr(device, "screencap", lambda: frame)
    decide = router.decide

    def slow_decide(state):
        # 模拟决策时已经经过100秒，不真实等待。
        frame.ts -= 100
        return decide(state)

    monkeypatch.setattr(router, "decide", slow_decide)
    engine.run(max_ticks=1)
    assert device.taps == []
    assert engine._pending is None
    assert engine._skipped_stale == 1
    assert events[-1]["reason"] == "frame_expired_during_decision"


def test_pending_action_times_out_even_if_every_followup_frame_is_stale(monkeypatch):
    state = ready(ui_state=UIState.MULLIGAN)
    engine, device, router, events, snapshots = engine_for(
        monkeypatch, [state, state], [Action(ActionType.CONFIRM)], timeout=0,
    )
    capture = device.screencap

    def frames():
        frame = capture()
        if device.frames > 1:
            frame.ts = time.time() - 100
        return frame

    monkeypatch.setattr(device, "screencap", frames)
    engine.run(max_ticks=10)
    assert router.calls == 1
    assert device.frames == 2
    assert len(device.taps) == 1
    assert snapshots == [{"tag": "action_timeout"}]
    assert events[-1]["reason"] == "no_fresh_frame_before_deadline"
