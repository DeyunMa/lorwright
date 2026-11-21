"""通过真实 CLI 和离线设备核验 Agent 输出；不连接游戏。"""

import json
import os
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest
from typer.testing import CliRunner

from lorwright.cli.app import app
from lorwright.core.runtime.session import RunSession, read_status


def replay_dir(tmp_path):
    folder = tmp_path / "frames"
    folder.mkdir()
    assert cv2.imwrite(str(folder / "001.png"), np.zeros((1080, 1920, 3), np.uint8))
    return folder


def test_foreground_jsonl_has_clean_stdout_and_queryable_terminal(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    monkeypatch.setenv("LORWRIGHT_RUNS_DIR", str(root))
    frames = replay_dir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["run", "--replay", str(frames), "--max-ticks", "1",
                                 "--champion", "jinx", "--jsonl"])
    assert result.exit_code == 0, result.output
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert events and all(event["schema_version"] == 1 for event in events)
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    assert events[-1]["type"] == "session_finished"
    assert events[-1]["payload"]["reason"] == "tick_limit"
    run_id = events[0]["run_id"]
    query = runner.invoke(app, ["sessions", "status", run_id, "--json"])
    saved = json.loads(query.stdout)
    assert query.exit_code == 0
    assert saved["status"] == "stopped" and saved["reason"] == "tick_limit"
    assert "last_progress_age_s" in saved and "heartbeat_age_s" in saved
    tail = runner.invoke(app, ["sessions", "events", run_id, "--after", "1", "--jsonl"])
    assert tail.exit_code == 0
    assert [json.loads(line)["seq"] for line in tail.stdout.splitlines()] == [
        event["seq"] for event in events if event["seq"] > 1
    ]


def test_configuration_failure_is_a_terminal_event(tmp_path, monkeypatch):
    monkeypatch.setenv("LORWRIGHT_RUNS_DIR", str(tmp_path))

    def broken_settings():
        raise ValueError("invalid local configuration")

    monkeypatch.setattr("lorwright.cli.app.load_settings", broken_settings)
    result = CliRunner().invoke(app, ["run", "--jsonl"])
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert result.exit_code == 1
    assert events[-1]["type"] == "session_finished"
    assert events[-1]["payload"]["status"] == "failed"
    saved = read_status(tmp_path, events[0]["run_id"])
    assert saved["reason"] == "execution_error"
    assert saved["details"]["error_type"] == "ValueError"


def test_bootstrap_login_stops_without_entering_adventure(tmp_path, monkeypatch):
    monkeypatch.setenv("LORWRIGHT_RUNS_DIR", str(tmp_path))
    device = Mock()
    monkeypatch.setattr("lorwright.cli.app._make_device", lambda _: device)
    monkeypatch.setattr("lorwright.core.loop.bootstrap.prepare_f1",
                        lambda settings, dev, **kwargs: SimpleNamespace(stop_reason="login_required"))
    result = CliRunner().invoke(app, ["adventure", "--bootstrap-f1", "--jsonl"])
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert result.exit_code == 3
    saved = read_status(tmp_path, events[0]["run_id"])
    assert (saved["status"], saved["reason"]) == ("stopped", "login_required")
    device.close.assert_called_once()


def test_status_does_not_read_game_configuration(tmp_path, monkeypatch):
    with RunSession(tmp_path, mode="battle", champion="test", device="replay") as session:
        session.finish("stopped", "tick_limit")

    def forbidden():
        raise AssertionError("status must not load game configuration")

    monkeypatch.setattr("lorwright.cli.app.load_settings", forbidden)
    result = CliRunner().invoke(app, ["sessions", "status", session.run_id,
                                     "--root", str(tmp_path), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["reason"] == "tick_limit"


def test_device_lock_failure_has_one_terminal_json_record(tmp_path, monkeypatch):
    monkeypatch.setenv("LORWRIGHT_RUNS_DIR", str(tmp_path))
    with RunSession(tmp_path, mode="battle", champion="test", device="adb"):
        result = CliRunner().invoke(app, ["run", "--jsonl"])
    records = [json.loads(line) for line in result.stdout.splitlines()]
    assert result.exit_code == 1
    assert len(records) == 1
    assert records[0]["seq"] == 1
    assert records[0]["type"] == "session_finished"
    assert records[0]["payload"]["reason"] == "device_lock_unavailable"


@pytest.fixture
def hand_runtime(tmp_path, monkeypatch):
    from lorwright.cli import app as cli
    from lorwright.core.config import Settings
    from lorwright.core.loop.outcome import LoopResult

    settings = Settings()
    settings.logging.dir = str(tmp_path / "logs")
    root = tmp_path / "runs"
    monkeypatch.setenv("LORWRIGHT_RUNS_DIR", str(root))
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    device = Mock()
    monkeypatch.setattr(cli, "_make_device", Mock(return_value=device))
    replay_device = Mock(return_value=device)
    monkeypatch.setattr("lorwright.core.device.replay.ReplayDevice", replay_device)
    pack = SimpleNamespace(name="elise", display_name="Elise", recognize_hand=Mock())
    load_pack = Mock(return_value=pack)
    monkeypatch.setattr("lorwright.core.champions.load", load_pack)
    engine_type = Mock()
    engine = engine_type.return_value
    engine.observe_hand.return_value = LoopResult("completed", "hand_view_verified")
    engine.run.side_effect = AssertionError("hand must not run battle")
    monkeypatch.setattr("lorwright.core.loop.engine.Engine", engine_type)
    monkeypatch.setattr(cli, "_battle_layers", Mock(side_effect=AssertionError("no battle layers")))
    monkeypatch.setattr("lorwright.core.loop.reconnect.run_with_reconnect_recovery",
                        Mock(side_effect=AssertionError("no client restart for hand")))
    return SimpleNamespace(root=root, engine=engine, engine_type=engine_type,
                           device=device, replay_device=replay_device, pack=pack, load_pack=load_pack)


@pytest.mark.parametrize("view,expanded", [("expanded", True), ("collapsed", False)])
@pytest.mark.parametrize("device", ["adb", "desktop", "replay"])
def test_hand_view_cli_dispatches_once_with_its_own_session(hand_runtime, tmp_path, view, expanded, device):
    runtime = hand_runtime
    args = ["--replay", str(replay_dir(tmp_path))] if device == "replay" else ["--device", device]
    result = CliRunner().invoke(app, ["hand", "--view", view, "--champion", "elise", "--jsonl", *args])
    assert result.exit_code == 0, result.output
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    assert events[-1]["type"] == "session_finished"
    saved = read_status(runtime.root, events[0]["run_id"])
    assert (saved["mode"], saved["status"], saved["reason"]) == ("hand", "completed", "hand_view_verified")
    runtime.engine.observe_hand.assert_called_once_with(expanded=expanded, close_device=False)
    runtime.engine.run.assert_not_called()
    runtime.device.close.assert_called_once()
    runtime.load_pack.assert_called_once_with("elise")
    assert runtime.engine_type.call_args.args[1].layers == []
    assert runtime.engine_type.call_args.kwargs["card_recognizer"] is runtime.pack.recognize_hand
    if device == "replay":
        runtime.replay_device.assert_called_once_with(str(tmp_path / "frames"))


@pytest.mark.parametrize("outcome,reason,exit_code", [
    ("stopped", "hand_view_unverified", 3),
    ("cancelled", "stop_requested", 130),
    ("failed", "execution_error", 1),
])
def test_hand_view_cli_preserves_terminal_reason_and_closes_device(hand_runtime, outcome, reason, exit_code):
    from lorwright.core.loop.outcome import LoopResult
    from lorwright.core.runtime.session import StopRequested

    runtime = hand_runtime
    if outcome == "cancelled":
        runtime.engine.observe_hand.side_effect = StopRequested()
    elif outcome == "failed":
        runtime.engine.observe_hand.side_effect = RuntimeError("synthetic observation error")
    else:
        runtime.engine.observe_hand.return_value = LoopResult(outcome, reason)
    result = CliRunner().invoke(app, ["hand", "--view", "collapsed", "--jsonl"])
    assert result.exit_code == exit_code, result.output
    events = [json.loads(line) for line in result.stdout.splitlines()]
    terminals = [event for event in events if event["type"] == "session_finished"]
    assert len(terminals) == 1
    assert (terminals[0]["payload"]["status"], terminals[0]["payload"]["reason"]) == (outcome, reason)
    saved = read_status(runtime.root, events[0]["run_id"])
    assert (saved["status"], saved["reason"]) == (outcome, reason)
    runtime.device.close.assert_called_once()


@pytest.mark.parametrize("args", [
    [], ["--view", "unknown"],
    ["--view", "expanded", "--bootstrap-f1"],
    ["--view", "expanded", "--open-riot-login"],
    ["--view", "expanded", "--auto-login"],
    ["--view", "expanded", "--jinx-summoned"],
    ["--view", "expanded", "--spell-already-played"],
    ["--view", "expanded", "--rockets-already-played", "1"],
    ["--view", "expanded", "--confirm-empty-hand-once"],
    ["--view", "expanded", "--max-ticks", "1"],
])
def test_hand_view_cli_rejects_unsupported_parameters_before_loading_config(monkeypatch, args):
    load = Mock(side_effect=AssertionError("invalid CLI must not load configuration"))
    monkeypatch.setattr("lorwright.cli.app.load_settings", load)
    result = CliRunner().invoke(app, ["hand", *args])
    assert result.exit_code == 2, result.output
    load.assert_not_called()


def test_hand_view_configuration_failure_uses_session_jsonl(tmp_path, monkeypatch):
    monkeypatch.setenv("LORWRIGHT_RUNS_DIR", str(tmp_path))
    monkeypatch.setattr("lorwright.cli.app.load_settings", Mock(side_effect=ValueError("bad config")))
    result = CliRunner().invoke(app, ["hand", "--view", "expanded", "--jsonl"])
    assert result.exit_code == 1
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert events[-1]["type"] == "session_finished"
    assert events[-1]["payload"]["reason"] == "execution_error"


def test_adb_timeout_reports_device_timeout_terminal_reason(hand_runtime):
    from lorwright.core.device.adb import AdbTimeout

    hand_runtime.engine.observe_hand.side_effect = AdbTimeout("adb 超时（15.0s）：exec-out screencap -p")
    result = CliRunner().invoke(app, ["hand", "--view", "collapsed", "--jsonl"])
    assert result.exit_code == 1, result.output
    events = [json.loads(line) for line in result.stdout.splitlines()]
    terminals = [event for event in events if event["type"] == "session_finished"]
    assert len(terminals) == 1
    assert terminals[0]["payload"]["status"] == "failed"
    assert terminals[0]["payload"]["reason"] == "device_timeout"


def test_hand_view_cli_uses_shared_device_lock(tmp_path, monkeypatch):
    monkeypatch.setenv("LORWRIGHT_RUNS_DIR", str(tmp_path))
    with RunSession(tmp_path, mode="battle", champion="test", device="adb"):
        result = CliRunner().invoke(app, ["hand", "--view", "expanded", "--jsonl"])
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert result.exit_code == 1
    assert len(events) == 1
    assert events[0]["payload"]["reason"] == "device_lock_unavailable"


def test_real_background_cli_can_be_observed_and_stopped(tmp_path):
    root = tmp_path / "runs"
    frames = replay_dir(tmp_path)
    env = dict(os.environ, LORWRIGHT_RUNS_DIR=str(root), PYTHONIOENCODING="utf-8")
    command = [sys.executable, "-m", "lorwright.cli.app"]
    started = subprocess.run(
        [*command, "sessions", "start", "--replay", str(frames), "--champion", "jinx", "--json"],
        capture_output=True, text=True, encoding="utf-8", env=env, timeout=10,
    )
    assert started.returncode == 0, started.stderr + started.stdout
    run_id = json.loads(started.stdout)["run_id"]
    # stop.request also works before the background interpreter reaches its first checkpoint.
    stopped = subprocess.run([*command, "sessions", "stop", run_id, "--json"],
                             capture_output=True, text=True, encoding="utf-8", env=env, timeout=10)
    assert stopped.returncode == 0, stopped.stderr + stopped.stdout
    assert json.loads(stopped.stdout)["requested"]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        saved = read_status(root, run_id)
        if saved["status"] in {"cancelled", "failed", "stopped", "completed"}:
            break
        time.sleep(0.05)
    assert saved["status"] == "cancelled", saved
    assert saved["reason"] == "stop_requested"
    assert (root / run_id / "events.jsonl").is_file()
