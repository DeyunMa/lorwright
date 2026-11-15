"""真实循环接入运行会话；合成帧不连接设备。"""

from dataclasses import replace

import pytest
from test_engine_outcome import engine_for, ready

from lorwright.core.loop.outcome import LoopResult
from lorwright.core.loop.recovery import RecoveryPolicy
from lorwright.core.models import (
    Action,
    ActionType,
    CardInHand,
    ClickPlan,
    GameState,
    Reading,
    Rect,
    UIState,
)
from lorwright.core.runtime.session import RunSession, StopRequested, read_status


@pytest.mark.parametrize(("states", "expected"), [
    ([GameState()], LoopResult("stopped", "tick_limit")),
    ([ready(ui_state=UIState.BATTLE_END)], LoopResult("completed", "battle_end")),
])
def test_engine_returns_exit_fact(monkeypatch, states, expected):
    engine, _, _, _, _ = engine_for(monkeypatch, states, [])
    assert engine.run(max_ticks=1) == expected


@pytest.mark.parametrize(("state", "reason"), [
    (GameState(), "unknown_ui"),
    (ready(readings={}), "unreadable"),
])
def test_unknown_wait_does_not_refresh_progress_or_deadline(monkeypatch, tmp_path, state, reason):
    now = [1000.0]
    monkeypatch.setattr("time.time", lambda: now[0])
    engine, device, router, _, _ = engine_for(monkeypatch, [state] * 4, [], timeout=2)
    observed = []
    with RunSession(tmp_path, mode="run", champion="test", device="synthetic",
                    heartbeat_s=1000, stall_timeout_s=3) as session:
        def observe(_):
            observed.append(read_status(tmp_path, session.run_id))
            now[0] += 2
        monkeypatch.setattr(engine, "_wait", observe)
        engine.run(max_ticks=4)
    assert router.calls == 0 and device.taps == []
    assert observed[0]["health"] == "waiting"
    assert observed[-1]["health"] == "stalled"
    assert {status["last_progress_at"] for status in observed} == {1000.0}
    assert {status["details"]["wait_until"] for status in observed} == {1002.0}
    assert observed[-1]["details"]["tick"] == 4
    assert observed[-1]["reason"] == reason


def test_verified_action_updates_session_progress(monkeypatch, tmp_path):
    now = [1000.0]
    monkeypatch.setattr("time.time", lambda: now[0])
    card = CardInHand(0, "card", 1, Rect(300, 800, 50, 50))
    before = ready(hand=[card], hand_expanded=True)
    after = replace(before, hand=[], mana=2,
                    readings={**before.readings, "mana": Reading(2, 0)})
    engine, _, _, _, _ = engine_for(
        monkeypatch, [before, before, after],
        [Action(ActionType.PLAY_CARD, 0), Action(ActionType.NO_OP)],
    )
    observed = []
    with RunSession(tmp_path, mode="run", champion="test", device="synthetic",
                    heartbeat_s=1000) as session:
        def observe(_):
            observed.append(read_status(tmp_path, session.run_id))
            now[0] += 1
        monkeypatch.setattr(engine, "_wait", observe)
        engine.run(max_ticks=3)
    assert observed[1]["last_progress_at"] == observed[0]["last_progress_at"]
    assert observed[-1]["last_progress_at"] > observed[0]["last_progress_at"]


def test_stop_request_prevents_remaining_inputs(monkeypatch, tmp_path):
    engine, device, _, _, _ = engine_for(monkeypatch, [], [])
    with RunSession(tmp_path, mode="run", champion="test", device="synthetic") as session:
        tap = device.tap
        def stop_after_tap(*point):
            tap(*point)
            (session.path / "stop.request").write_text("stop", encoding="utf-8")
        monkeypatch.setattr(device, "tap", stop_after_tap)
        with pytest.raises(StopRequested):
            engine._execute(ClickPlan(points=[(10, 10), (20, 20)], wait_ms=0))
    assert device.taps == [(10, 10)]


def test_stop_during_decision_prevents_first_input_and_closes_device(monkeypatch, tmp_path):
    engine, device, router, _, _ = engine_for(
        monkeypatch, [ready()], [Action(ActionType.END_TURN)],
    )
    with RunSession(tmp_path, mode="run", champion="test", device="synthetic") as session:
        decide = router.decide
        def stop_in_decision(state):
            (session.path / "stop.request").write_text("stop", encoding="utf-8")
            return decide(state)
        monkeypatch.setattr(router, "decide", stop_in_decision)
        with pytest.raises(StopRequested):
            engine.run(max_ticks=1)
    assert device.taps == [] and device.closed
    assert read_status(tmp_path, session.run_id)["phase"] == "stopping"


def test_shared_device_stays_open_after_battle(monkeypatch):
    engine, device, _, _, _ = engine_for(monkeypatch, [ready(ui_state=UIState.BATTLE_END)], [])
    assert engine.run(max_ticks=1, close_device=False).reason == "battle_end"
    assert not device.closed
    assert device.screencap().image is not None


@pytest.mark.parametrize(("recovery", "reason"), [
    (RecoveryPolicy(retry_limit=0, battle_limit=1), "recovery_disabled"),
    (RecoveryPolicy(retry_limit=0, battle_limit=0, client_limit=0), "recovery_exhausted"),
])
def test_recovery_stop_reasons_are_distinct(monkeypatch, recovery, reason):
    engine, _, _, _, _ = engine_for(monkeypatch, [], [])
    engine.recovery = recovery
    assert not engine._recover(ready())
    assert engine.result == LoopResult("stopped", reason)


def test_action_timeout_returns_specific_reason(monkeypatch):
    state = ready(ui_state=UIState.MULLIGAN)
    engine, _, _, _, _ = engine_for(
        monkeypatch, [state, state], [Action(ActionType.CONFIRM)], timeout=0,
    )
    assert engine.run(max_ticks=10) == LoopResult("stopped", "action_timeout")
