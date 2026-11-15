"""通过真实 CLI 和离线设备核验 Agent 输出；不连接游戏。"""

import json
import os
import subprocess
import sys
import time

import cv2
import numpy as np
from typer.testing import CliRunner

from lorwright.main import app
from lorwright.runtime.session import RunSession, read_status


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

    monkeypatch.setattr("lorwright.main.load_settings", broken_settings)
    result = CliRunner().invoke(app, ["run", "--jsonl"])
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert result.exit_code == 1
    assert events[-1]["type"] == "session_finished"
    assert events[-1]["payload"]["status"] == "failed"
    saved = read_status(tmp_path, events[0]["run_id"])
    assert saved["reason"] == "execution_error"
    assert saved["details"]["error_type"] == "ValueError"


def test_status_does_not_read_game_configuration(tmp_path, monkeypatch):
    with RunSession(tmp_path, mode="battle", champion="test", device="replay") as session:
        session.finish("stopped", "tick_limit")

    def forbidden():
        raise AssertionError("status must not load game configuration")

    monkeypatch.setattr("lorwright.main.load_settings", forbidden)
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


def test_real_background_cli_can_be_observed_and_stopped(tmp_path):
    root = tmp_path / "runs"
    frames = replay_dir(tmp_path)
    env = dict(os.environ, LORWRIGHT_RUNS_DIR=str(root), PYTHONIOENCODING="utf-8")
    command = [sys.executable, "-m", "lorwright.main"]
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
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        saved = read_status(root, run_id)
        if saved["status"] in {"cancelled", "failed", "stopped", "completed"}:
            break
        time.sleep(0.05)
    assert saved["status"] == "cancelled", saved
    assert saved["reason"] == "stop_requested"
    assert (root / run_id / "events.jsonl").is_file()
