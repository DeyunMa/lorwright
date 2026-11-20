"""用可控时钟驱动真实循环；不连接模拟器、不真实等待五分钟。"""

from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from test_engine_outcome import engine_for, ready

from lorwright.core.config import Settings
from lorwright.core.device.base import Frame
from lorwright.core.loop import reconnect
from lorwright.core.loop.adventure import AdventureLoop
from lorwright.core.loop.outcome import LoopResult
from lorwright.core.models import Action, ActionType, Rect, UIState
from lorwright.core.perceive.login import LoginScreen
from lorwright.core.runtime.session import RunSession, StopRequested, read_status


@pytest.fixture
def scene(monkeypatch):
    settings = Settings()
    now = [0.0]
    monkeypatch.setattr(reconnect.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(reconnect, "_wait", lambda seconds: now.__setitem__(0, now[0] + seconds))
    detector = Mock()
    detector.detect.side_effect = lambda image: bool(image[0, 0, 0])
    monkeypatch.setattr(reconnect, "ReconnectDetector", lambda: detector)
    image = np.ones((1080, 1920, 3), np.uint8)
    device = Mock()
    device.screencap.return_value = Frame(image)
    snapshots = []
    monkeypatch.setattr(reconnect, "save_snapshot",
                        lambda image, directory, *, tag: snapshots.append(tag) or tag)
    return settings, device, now, image, snapshots


def test_reconnect_waits_full_five_minutes_before_one_restart(scene, monkeypatch):
    settings, device, now, image, snapshots = scene
    starts = []
    resumed = []
    device.restart_app.side_effect = lambda package: starts.append((now[0], package))
    monkeypatch.setattr(reconnect, "_wait_after_restart", lambda *args, **kw: None)

    def run(capture, restarted):
        resumed.append(restarted)
        if not restarted:
            capture()
        return LoopResult("stopped", "iteration_limit")

    assert reconnect.run_with_reconnect_recovery(settings, device, run).reason == "iteration_limit"
    assert starts == [(300, settings.adb.package)]
    assert resumed == [False, True]
    assert snapshots == ["reconnect_timeout"]
    device.tap.assert_not_called()
    device.drag.assert_not_called()


def test_page_clears_before_threshold_and_next_episode_starts_new_timer(scene):
    settings, device, now, image, _ = scene
    def screen():
        # 第一段 0..298 秒；第二段从 298 秒后开始，不能借用前段时间。
        if now[0] == 298 and device.screencap.call_count == 150:
            return Frame(np.zeros_like(image))
        return Frame(image)
    device.screencap.side_effect = screen
    capture = reconnect._ReconnectCapture(settings, device)
    assert not capture().image.any()
    assert now[0] == 298
    with pytest.raises(reconnect.ReconnectTimeout):
        capture()
    assert now[0] == 598
    device.restart_app.assert_not_called()


def test_unknown_and_stale_frames_do_not_count_as_reconnection(scene, monkeypatch):
    settings, device, now, image, _ = scene
    capture = reconnect._ReconnectCapture(settings, device)
    unknown = Frame(np.zeros_like(image))
    device.screencap.return_value = unknown
    assert capture() is unknown and now[0] == 0
    now[0] = 1000
    stale = Frame(image, ts=1)
    device.screencap.return_value = stale
    assert capture() is stale and now[0] == 1000
    device.restart_app.assert_not_called()


def test_stale_frame_ends_continuous_episode(scene, monkeypatch):
    settings, device, now, image, _ = scene
    now[0] = 1000
    stale = Frame(image, ts=1)
    device.screencap.side_effect = [Frame(image), stale]
    capture = reconnect._ReconnectCapture(settings, device)
    assert capture() is stale
    assert now[0] == 1002
    device.restart_app.assert_not_called()


def test_second_persistent_episode_exhausts_without_second_restart(scene, monkeypatch):
    settings, device, now, _, snapshots = scene
    monkeypatch.setattr(reconnect, "_wait_after_restart", lambda *args, **kw: None)
    result = reconnect.run_with_reconnect_recovery(settings, device, lambda capture, _: capture())
    assert result == LoopResult("stopped", "reconnect_recovery_exhausted")
    device.restart_app.assert_called_once_with(settings.adb.package)
    assert now[0] == 600
    assert snapshots == ["reconnect_timeout", "reconnect_timeout"]


def test_restart_failure_is_terminal(scene):
    settings, device, _, _, _ = scene
    device.restart_app.side_effect = RuntimeError("failed")
    result = reconnect.run_with_reconnect_recovery(settings, device, lambda capture, _: capture())
    assert result == LoopResult("stopped", "reconnect_restart_failed")
    device.restart_app.assert_called_once()


def test_wait_has_stable_session_deadline_and_stop_prevents_restart(scene, monkeypatch, tmp_path):
    settings, device, now, _, _ = scene
    monkeypatch.setattr(reconnect.time, "time", lambda: 1000 + now[0])
    waits = []
    with RunSession(tmp_path, mode="adventure", champion="test", device="synthetic",
                    heartbeat_s=1000, stall_timeout_s=3) as session:
        def wait(seconds):
            state = read_status(tmp_path, session.run_id)
            waits.append((state["health"], state["wait_deadline"]))
            now[0] += seconds
            if now[0] >= 10:
                (session.path / "stop.request").write_text("stop", encoding="utf-8")
        monkeypatch.setattr(reconnect, "_wait", wait)
        with pytest.raises(StopRequested):
            reconnect.run_with_reconnect_recovery(settings, device, lambda capture, _: capture())
    assert waits and set(waits) == {("waiting", 1300)}
    device.restart_app.assert_not_called()


@pytest.mark.parametrize("ready_scene", ["home", "map", "battle", "blue_only", "none",
                                        "reconnecting", "stale"])
def test_restart_requires_fresh_known_game_scene(scene, monkeypatch, ready_scene):
    settings, device, now, image, _ = scene
    capture = reconnect._ReconnectCapture(settings, device)
    login = Mock()
    login.detect.return_value = LoginScreen.NONE
    monkeypatch.setattr(reconnect, "LoginDetector", lambda: login)
    ui = Mock()
    ui.detect.return_value = (UIState.MY_TURN_IDLE if ready_scene in {"battle", "blue_only"}
                              else UIState.UNKNOWN)
    ui.action_prompt.return_value = "action_pass" if ready_scene == "battle" else None
    monkeypatch.setattr(reconnect, "UIStateDetector", lambda **kw: ui)
    monkeypatch.setattr(reconnect, "find_home_adventure_entry",
                        lambda image: object() if ready_scene == "home" else None)
    monkeypatch.setattr(reconnect, "is_map", lambda image: ready_scene == "map")
    if ready_scene == "stale":
        now[0] = 1000
    device.screencap.return_value = Frame(
        image if ready_scene == "reconnecting" else np.zeros_like(image),
        ts=1 if ready_scene == "stale" else 0,
    )
    reason = reconnect._wait_after_restart(settings, device, capture, auto_login=False)
    assert reason == (None if ready_scene in {"home", "map", "battle"}
                      else "reconnect_restart_unverified")
    start_now = 1000 if ready_scene == "stale" else 0
    assert now[0] == start_now + (0 if reason is None else 120)
    device.tap.assert_not_called()
    device.text_secret.assert_not_called()


@pytest.mark.parametrize("auto_login", [False, True])
def test_restart_reuses_login_permission_then_verifies_game(scene, monkeypatch, auto_login):
    settings, device, _, image, _ = scene
    device.screencap.return_value = Frame(np.zeros_like(image))
    capture = reconnect._ReconnectCapture(settings, device)
    login = Mock()
    login.detect.side_effect = [LoginScreen.SPLASH, LoginScreen.NONE]
    monkeypatch.setattr(reconnect, "LoginDetector", lambda: login)
    ui = Mock()
    ui.detect.return_value = UIState.UNKNOWN
    monkeypatch.setattr(reconnect, "UIStateDetector", lambda **kw: ui)
    monkeypatch.setattr(reconnect, "find_home_adventure_entry", lambda image: object())
    prepare = Mock(return_value=SimpleNamespace(stop_reason=None if auto_login else "login_required"))
    monkeypatch.setattr(reconnect, "prepare_login", prepare)
    reason = reconnect._wait_after_restart(settings, device, capture, auto_login=auto_login)
    assert reason == (None if auto_login else "login_required")
    prepare.assert_called_once_with(settings, device, auto_login=auto_login, allow_restart=False)


@pytest.mark.parametrize("context", ["battle", "adventure", "reward"])
def test_shared_capture_interrupts_real_loops_before_short_unknown_timeout(scene, monkeypatch, context):
    settings, device, now, _, _ = scene
    engine, engine_device, router, _, _ = engine_for(monkeypatch, [ready()], [])
    capture = reconnect._ReconnectCapture(settings, device)
    engine.capture_frame = capture
    adventure = AdventureLoop(settings, engine, device, pack=SimpleNamespace(), capture_frame=capture)
    monkeypatch.setattr(adventure, "_wait", lambda *args, **kwargs: None)
    monkeypatch.setattr("lorwright.core.loop.adventure.find_continue_button",
                        lambda image: Rect(10, 10, 20, 20))
    with pytest.raises(reconnect.ReconnectTimeout):
        if context == "battle":
            engine.run(max_ticks=1, close_device=False)
        elif context == "adventure":
            adventure.run(max_nodes=1)
        else:
            first = Frame(np.zeros((1080, 1920, 3), np.uint8))
            device.screencap.side_effect = lambda: (
                first if device.screencap.call_count == 1 else device.screencap.return_value
            )
            adventure._handle_task_reward(adventure._frame())
    assert now[0] >= 300
    assert not engine_device.closed
    assert router.calls == 0


def test_pending_action_is_not_verified_or_replayed_across_restart(scene, monkeypatch):
    settings, device, _, _, _ = scene
    before = ready(ui_state=UIState.MULLIGAN)
    engine, _, _, events, _ = engine_for(
        monkeypatch, [before], [Action(ActionType.CONFIRM)],
    )
    capture = reconnect._ReconnectCapture(settings, device)
    original_capture = engine.capture_frame
    calls = [0]
    def next_frame():
        calls[0] += 1
        return original_capture() if calls[0] == 1 else capture()
    engine.capture_frame = next_frame
    with pytest.raises(reconnect.ReconnectTimeout):
        engine.run(max_ticks=2, close_device=False)
    assert engine._pending is not None
    assert not [event for event in events if event.get("status") == "succeeded"]
    assert engine.device.taps == [(20, 20)]
