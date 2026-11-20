"""会话的磁盘/CLI 合约；无需游戏、ADB 或图像解析。"""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from lorwright.cli import sessions as cli
from lorwright.core.runtime import session
from lorwright.core.runtime.session import (
    RunSession,
    StopRequested,
    checkpoint,
    current_session,
    read_status,
    record_event,
    report,
)

runner = CliRunner()


def saved_events(run):
    return [json.loads(line) for line in
            (run.path / "events.jsonl").read_text(encoding="utf-8").splitlines()]


def test_decision_input_and_verification_have_distinct_cli_messages(tmp_path):
    with RunSession(tmp_path, mode="battle", champion="jinx", device="fake") as run:
        report("decided", action="attack", strategy="attack_when_token",
               decision_reason="有攻击令牌，未知手牌不影响攻击", unknown_cards=[0, 2])
        result = runner.invoke(cli.app, ["status", run.run_id, "--root", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert "未知牌槽位：[0, 2]" in result.stdout
        assert "未知手牌不影响攻击" in result.stdout
        report("input_sent", action="attack", inputs=1)
        sent = read_status(tmp_path, run.run_id)
        assert "尚未确认游戏结果" in sent["message"]
        assert sent["last_decision"]["action"] == "attack"
        report("verified", "selected_units_moved_to_combat_row", progress=True)
        assert "已验证" in read_status(tmp_path, run.run_id)["message"]
        report("stopped", "unknown_target", snapshot="snapshots/unknown_target.png")
        run.finish("stopped", "unknown_target")
    result = runner.invoke(cli.app, ["status", run.run_id, "--root", str(tmp_path)])
    assert "unknown_target" in result.stdout
    assert "snapshots/unknown_target.png" in result.stdout
    events = saved_events(run)
    phases = [e["payload"] for e in events if e["type"] == "phase"]
    assert [p["phase"] for p in phases] == ["decided", "input_sent", "verified", "stopped"]
    assert all(p["message"] for p in phases)


def test_human_events_hide_repeated_polling_but_jsonl_keeps_every_event(tmp_path):
    with RunSession(tmp_path, mode="battle", champion="", device="fake") as run:
        for _ in range(2):
            report("capture")
            report("recognized", ui="my_turn_idle", summary="same")
            report("waiting", "enemy_turn", wait_s=60)
        run.finish("stopped", "tick_limit")
    human = runner.invoke(cli.app, ["events", run.run_id, "--root", str(tmp_path)])
    assert human.exit_code == 0, human.output
    assert human.stdout.count("识别到 my_turn_idle") == 1
    assert human.stdout.count("等待对手") == 1
    detailed = runner.invoke(cli.app, ["events", run.run_id, "--root", str(tmp_path), "--verbose"])
    assert '"phase": "capture"' in detailed.stdout
    machine = runner.invoke(cli.app, ["events", run.run_id, "--root", str(tmp_path), "--jsonl"])
    assert [json.loads(line) for line in machine.stdout.splitlines()] == saved_events(run)


def test_human_events_preserve_each_input_and_verified_result(tmp_path):
    with RunSession(tmp_path, mode="battle", champion="", device="fake") as run:
        for _ in range(2):
            report("decided", action="play_card", decision_reason="选择可出单位")
            report("input_sent", action="play_card")
            report("verified", "hand_reduced_and_mana_or_board_changed", progress=True)
    result = runner.invoke(cli.app, ["events", run.run_id, "--root", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert result.stdout.count("选择可出单位") == 2
    assert result.stdout.count("尚未确认游戏结果") == 2
    assert result.stdout.count("已验证可见结果") == 2


def test_jsonl_sequence_unique_terminal_and_scope(tmp_path, capsys):
    assert current_session() is None
    report("outside")
    record_event("outside")
    checkpoint()
    with RunSession(tmp_path, mode="battle", champion="arbitrary", device="fake", jsonl=True) as run:
        assert current_session() is run
        report("battle", "awaiting_result", wait_s=5, action="play", champion="configured")
        record_event("decision", action="no_op")
        run.finish("stopped", "max_ticks")
        run.finish("completed", "ignored")
        run.event("ignored")
    assert current_session() is None
    events = saved_events(run)
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert [e["type"] for e in events].count("session_finished") == 1
    assert [json.loads(line) for line in capsys.readouterr().out.splitlines()] == events
    assert read_status(tmp_path, run.run_id)["reason"] == "max_ticks"
    assert read_status(tmp_path, run.run_id)["champion"] == "configured"
    assert set(events[0]) == {"schema_version", "run_id", "seq", "ts_utc", "type", "payload"}


@pytest.mark.parametrize(("error", "status", "reason"), [
    (None, "stopped", "run_returned"),
    (ValueError("bad"), "failed", "exception"),
    (KeyboardInterrupt(), "cancelled", "keyboard_interrupt"),
    (StopRequested(), "cancelled", "stop_requested"),
])
def test_exit_semantics(tmp_path, error, status, reason):
    run = RunSession(tmp_path, mode="battle", champion="", device="fake")
    if error:
        with pytest.raises(type(error)), run:
            raise error
    else:
        with run:
            pass
    result = read_status(tmp_path, run.run_id)
    assert (result["status"], result["reason"]) == (status, reason)


def test_stop_ack_only_and_checkpoint(tmp_path):
    with pytest.raises(StopRequested):
        with RunSession(tmp_path, mode="battle", champion="", device="fake") as run:
            result = runner.invoke(cli.app, ["stop", run.run_id, "--root", str(tmp_path), "--json"])
            assert result.exit_code == 0, result.output
            assert json.loads(result.stdout)["requested"]
            assert read_status(tmp_path, run.run_id)["status"] == "running"
            checkpoint()
    assert read_status(tmp_path, run.run_id)["status"] == "cancelled"


def test_heartbeat_not_progress_waiting_stall_unresponsive(tmp_path, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(session.time, "time", lambda: clock[0])
    with RunSession(tmp_path, mode="battle", champion="", device="fake", heartbeat_s=100) as run:
        report("result", wait_s=10)
        assert read_status(tmp_path, run.run_id)["health"] == "waiting"
        clock[0] = 141
        run._status["heartbeat_at"] = clock[0]
        run._persist()
        result = read_status(tmp_path, run.run_id)
        assert result["health"] == "stalled"
        assert result["last_progress_age_s"] == 41
        report("map", progress=True)
        assert read_status(tmp_path, run.run_id)["health"] == "running"
        clock[0] += 301
        assert read_status(tmp_path, run.run_id)["health"] == "unresponsive"


def test_background_heartbeat_runs_without_ticks(tmp_path):
    with RunSession(tmp_path, mode="battle", champion="", device="fake", heartbeat_s=0.01) as run:
        updated = threading.Event()
        original = run._persist

        def observe():
            original()
            updated.set()

        run._persist = observe
        before = run._status["last_progress_at"]
        assert updated.wait(2)
        assert read_status(tmp_path, run.run_id)["last_progress_at"] == before


def test_device_lock_released_and_distinct_devices(tmp_path):
    with RunSession(tmp_path, mode="battle", champion="", device="fake"):
        with pytest.raises(RuntimeError, match="设备已由另一会话控制"):
            with RunSession(tmp_path, mode="battle", champion="", device="fake"):
                pass
        with RunSession(tmp_path, mode="battle", champion="", device="other"):
            pass
    with RunSession(tmp_path, mode="battle", champion="", device="fake"):
        pass


def test_adb_and_desktop_share_the_interactive_device_lock(tmp_path):
    with RunSession(tmp_path / "adb", mode="battle", champion="", device="adb"):
        with pytest.raises(RuntimeError, match="设备已由另一会话控制"):
            with RunSession(tmp_path / "desktop", mode="battle", champion="", device="desktop"):
                pass


def test_device_lock_is_shared_across_run_directories(tmp_path):
    device = f"test:{tmp_path}"
    with RunSession(tmp_path / "a", mode="battle", champion="", device=device):
        with pytest.raises(RuntimeError, match="设备已由另一会话控制"):
            with RunSession(tmp_path / "b", mode="battle", champion="", device=device):
                pass


def test_enter_failure_releases_device_and_context(tmp_path, monkeypatch):
    device = f"test:{tmp_path}"
    run = RunSession(tmp_path / "a", mode="battle", champion="", device=device)

    def failed_event(*args, **kwargs):
        raise OSError("event store unavailable")

    monkeypatch.setattr(run, "event", failed_event)
    try:
        with pytest.raises(OSError, match="event store unavailable"):
            run.__enter__()
        assert current_session() is None
        with RunSession(tmp_path / "b", mode="battle", champion="", device=device):
            pass
    finally:
        # Keep a deliberately failing old implementation from leaking into later tests.
        if current_session() is run:
            session._active.reset(run._token)
            run._token = None
        run._lock.release()


@pytest.mark.parametrize("run_id", ["../bad", ".", "x/y", "x\\y", "", "a" * 101])
def test_invalid_run_id(tmp_path, run_id):
    with pytest.raises(ValueError):
        session.run_path(tmp_path, run_id)


def test_status_latest_and_event_cursor(tmp_path):
    with RunSession(tmp_path, mode="battle", champion="", device="fake") as run:
        run.event("choice", value=1)
    result = runner.invoke(cli.app, ["status", "--root", str(tmp_path), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["run_id"] == run.run_id
    result = runner.invoke(cli.app, ["events", run.run_id, "--root", str(tmp_path),
                                     "--jsonl", "--follow", "--after", "1"])
    assert result.exit_code == 0, result.output
    assert [json.loads(line)["seq"] for line in result.stdout.splitlines()] == [2, 3]


def test_events_ignores_partial_line(tmp_path):
    with RunSession(tmp_path, mode="battle", champion="", device="fake") as run:
        pass
    with (run.path / "events.jsonl").open("a") as stream:
        stream.write('{"seq":3')
    result = runner.invoke(cli.app, ["events", run.run_id, "--root", str(tmp_path), "--jsonl"])
    assert result.exit_code == 0, result.output
    assert len(result.stdout.splitlines()) == 2


def test_start_early_failure_keeps_console_log(tmp_path, monkeypatch):
    calls = []

    def spawn(command, **kwargs):
        calls.append((command, kwargs))
        assert kwargs["stderr"] == subprocess.STDOUT
        kwargs["stdout"].write(b"startup error\n")
        return SimpleNamespace(pid=99999999, wait=lambda timeout: 2)

    monkeypatch.setattr(cli.subprocess, "Popen", spawn)
    result = runner.invoke(cli.app, ["start", "--root", str(tmp_path), "--json",
                                     "--champion", "arbitrary", "--max-ticks", "1"])
    assert result.exit_code == 1, result.output
    output = json.loads(result.stdout)
    assert output["status"] == "failed"
    status = read_status(tmp_path, output["run_id"])
    assert status["details"]["exit_code"] == 2
    assert (tmp_path / output["run_id"] / "console.log").read_text() == "startup error\n"
    assert "arbitrary" in calls[0][0]
    assert calls[0][1]["env"]["LORWRIGHT_RUNS_DIR"] == str(tmp_path)
    assert calls[0][1]["stdin"] == subprocess.DEVNULL


def test_start_spawn_error(tmp_path, monkeypatch):
    def spawn(*args, **kwargs):
        raise OSError("cannot spawn")

    monkeypatch.setattr(cli.subprocess, "Popen", spawn)
    result = runner.invoke(cli.app, ["start", "--root", str(tmp_path), "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["reason"] == "spawn_failed"


def test_detach_windows_options(monkeypatch):
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "DETACHED_PROCESS", 8, raising=False)
    monkeypatch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 512, raising=False)
    monkeypatch.setattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000, raising=False)
    assert cli._detach_options() == {"creationflags": 0x01000208}


def test_start_success_reserves_id_and_passes_replay(tmp_path, monkeypatch):
    calls = []

    def spawn(command, **kwargs):
        calls.append(command)

        def wait(timeout):
            raise subprocess.TimeoutExpired(command, timeout)

        return SimpleNamespace(pid=os.getpid(), wait=wait)

    monkeypatch.setattr(cli.subprocess, "Popen", spawn)
    result = runner.invoke(cli.app, ["start", "--root", str(tmp_path), "--json",
                                     "--replay", str(tmp_path)])
    assert result.exit_code == 0, result.output
    output = json.loads(result.stdout)
    assert output["status"] == "starting"
    assert read_status(tmp_path, output["run_id"])["health"] == "starting"
    with RunSession(tmp_path, mode="battle", champion="", device=str(tmp_path),
                    run_id=output["run_id"]):
        pass
    assert "--jsonl" not in calls[0]
    assert output["console_log_format"] == "text"


@pytest.mark.parametrize("option", ["--spell-already-played", "--jinx-summoned",
                                    "--confirm-empty-hand-once"])
def test_start_battle_recovery_option(tmp_path, monkeypatch, option):
    commands = []

    def spawn(command, **kwargs):
        commands.append(command)

        def wait(timeout):
            raise subprocess.TimeoutExpired(command, timeout)

        return SimpleNamespace(pid=os.getpid(), wait=wait)

    monkeypatch.setattr(cli.subprocess, "Popen", spawn)
    bad = runner.invoke(cli.app, ["start", "--root", str(tmp_path), "--mode", "adventure", option])
    assert bad.exit_code == 2 and not commands
    good = runner.invoke(cli.app, ["start", "--root", str(tmp_path), "--mode", "battle", option])
    assert good.exit_code == 0, good.output
    assert "run" in commands[0] and option in commands[0]


def test_start_rocket_recovery_validation_and_forwarding(tmp_path, monkeypatch):
    commands = []

    def spawn(command, **kwargs):
        commands.append(command)

        def wait(timeout):
            raise subprocess.TimeoutExpired(command, timeout)

        return SimpleNamespace(pid=os.getpid(), wait=wait)

    monkeypatch.setattr(cli.subprocess, "Popen", spawn)
    base = ["start", "--root", str(tmp_path), "--rockets-already-played"]
    for args in (["1"], ["3", "--champion", "jinx", "--jinx-summoned"],
                 ["1", "--champion", "elise", "--jinx-summoned"],
                 ["1", "--champion", "jinx", "--jinx-summoned", "--mode", "adventure"]):
        assert runner.invoke(cli.app, base + args).exit_code == 2
    assert not commands
    result = runner.invoke(cli.app, base + ["1", "--champion", "jinx", "--jinx-summoned"])
    assert result.exit_code == 0, result.output
    index = commands[0].index("--rockets-already-played")
    assert commands[0][index + 1] == "1"


def test_start_weekly_replay_slot_validation_and_forwarding(tmp_path, monkeypatch):
    commands = []

    def spawn(command, **kwargs):
        commands.append(command)

        def wait(timeout):
            raise subprocess.TimeoutExpired(command, timeout)

        return SimpleNamespace(pid=os.getpid(), wait=wait)

    monkeypatch.setattr(cli.subprocess, "Popen", spawn)
    base = ["start", "--root", str(tmp_path), "--weekly-replay-slot"]
    assert runner.invoke(cli.app, base + ["2"]).exit_code == 2
    assert runner.invoke(cli.app, base + ["4", "--mode", "adventure"]).exit_code == 2
    assert not commands
    result = runner.invoke(cli.app, base + ["2", "--mode", "adventure"])
    assert result.exit_code == 0, result.output
    index = commands[0].index("--weekly-replay-slot")
    assert commands[0][index + 1] == "2"


def test_start_passes_riot_login_option_only_for_bootstrap(tmp_path, monkeypatch):
    commands = []

    def spawn(command, **kwargs):
        commands.append(command)

        def wait(timeout):
            raise subprocess.TimeoutExpired(command, timeout)

        return SimpleNamespace(pid=os.getpid(), wait=wait)

    monkeypatch.setattr(cli.subprocess, "Popen", spawn)
    bad = runner.invoke(cli.app, ["start", "--root", str(tmp_path), "--mode", "adventure",
                                  "--open-riot-login"])
    assert bad.exit_code == 2 and not commands
    good = runner.invoke(cli.app, ["start", "--root", str(tmp_path), "--mode", "adventure",
                                   "--bootstrap-f1", "--open-riot-login", "--auto-login", "--json"])
    assert good.exit_code == 0, good.output
    assert "--bootstrap-f1" in commands[0] and "--open-riot-login" in commands[0]
    assert "--auto-login" in commands[0]


def test_real_cli_subprocess_json_utf8(tmp_path):
    with RunSession(tmp_path, mode="adventure", champion="任意英雄", device="fake") as run:
        pass
    result = subprocess.run(
        [sys.executable, "-c", "from lorwright.cli.sessions import app; app()",
         "status", run.run_id, "--json"],
        env=dict(os.environ, LORWRIGHT_RUNS_DIR=str(tmp_path),
                 PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src")),
        capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8")
    assert json.loads(result.stdout.decode("utf-8"))["champion"] == "任意英雄"


def test_follow_returns_when_heartbeat_is_lost(tmp_path, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(session.time, "time", lambda: clock[0])
    with RunSession(tmp_path, mode="battle", champion="", device="fake", heartbeat_s=100) as run:
        clock[0] = 401.0
        result = runner.invoke(cli.app, ["events", run.run_id, "--root", str(tmp_path),
                                         "--jsonl", "--follow"])
        assert result.exit_code == 2, result.output
        assert "unresponsive" in result.stderr
        assert json.loads(result.stdout)["type"] == "session_started"


def test_windows_lock_uses_single_byte(tmp_path, monkeypatch):
    import types

    calls = []
    fake = types.ModuleType("msvcrt")
    fake.LK_NBLCK = 2
    fake.locking = lambda *args: calls.append(args)
    monkeypatch.setattr(session, "_device_lock_root", lambda: tmp_path / "locks")
    lock = session._DeviceLock("fake")
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    monkeypatch.setattr(session.sys, "platform", "win32")
    lock.acquire()
    assert calls[0][1:] == (2, 1)
    assert lock.path.read_bytes() == b"0"
    lock.release()
    assert lock.file is None


def test_dead_background_start_is_not_permanently_starting(tmp_path, monkeypatch):
    def spawn(command, **kwargs):
        def wait(timeout):
            raise subprocess.TimeoutExpired(command, timeout)
        return SimpleNamespace(pid=99999999, wait=wait)

    monkeypatch.setattr(cli.subprocess, "Popen", spawn)
    monkeypatch.setattr(session, "process_alive", lambda pid: False)
    result = runner.invoke(cli.app, ["start", "--root", str(tmp_path), "--json",
                                     "--mode", "adventure", "--replay", str(tmp_path),
                                     "--stall-timeout", "12"])
    assert result.exit_code == 0, result.output
    saved = read_status(tmp_path, json.loads(result.stdout)["run_id"])
    assert saved["status"] == "failed"
    assert saved["stall_timeout_s"] == 12


def test_wait_deadline_not_extended_by_repeated_ticks(tmp_path, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(session.time, "time", lambda: clock[0])
    with RunSession(tmp_path, mode="battle", champion="", device="fake", heartbeat_s=100) as run:
        report("waiting", "animation", wait_s=2, tick=1)
        clock[0] = 101
        report("capture", tick=2)
        report("waiting", "animation", wait_s=2, tick=2)
        assert read_status(tmp_path, run.run_id)["wait_deadline"] == 102
        clock[0] = 102
        assert read_status(tmp_path, run.run_id)["health"] == "stalled"
        report("verified", progress=True)
        assert read_status(tmp_path, run.run_id)["health"] == "running"


def test_terminal_preserves_diagnostics_and_snapshot(tmp_path):
    with RunSession(tmp_path, mode="battle", champion="", device="fake") as run:
        report("waiting", "animation", tick=7, ui="unknown", current_action="play")
        record_event("snapshot", path="frame.png")
        report("stopped", "unknown_ui")
        run.finish("stopped", "unknown_ui", extra="reason")
    result = read_status(tmp_path, run.run_id)
    assert result["details"] == dict(tick=7, ui="unknown", current_action="play", extra="reason")
    assert result["last_snapshot"] == "frame.png"
    assert result["last_event"]["type"] == "session_finished"
    assert result["last_event"]["ts_utc"].endswith("Z")


@pytest.mark.parametrize("command", ["status", "stop", "events"])
def test_missing_session_machine_error(tmp_path, command):
    flag = "--jsonl" if command == "events" else "--json"
    result = runner.invoke(cli.app, [command, "missing", "--root", str(tmp_path), flag])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["code"] == "session_unavailable"


@pytest.mark.parametrize("health", ["running", "waiting", "stalled", "unresponsive", "completed"])
def test_status_wait_is_bounded_and_outputs_once(monkeypatch, health):
    clock = [0.0]
    queries = []
    sleeps = []

    def lookup(root, run_id, machine):
        queries.append(run_id)
        return dict(run_id="fixed", status="completed" if health == "completed" else "running",
                    health=health, heartbeat_at=clock[0], last_progress_at=clock[0])

    def sleep(duration):
        sleeps.append(duration)
        clock[0] += duration

    monkeypatch.setattr(cli, "_status", lookup)
    monkeypatch.setattr(cli.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(cli.time, "sleep", sleep)
    result = runner.invoke(cli.app, ["status", "--wait", "1", "--json"])
    assert result.exit_code == 0, result.output
    assert len(result.stdout.splitlines()) == 1
    assert json.loads(result.stdout)["health"] == health
    if health in {"stalled", "unresponsive", "completed"}:
        assert not sleeps
        assert len(queries) == 1
    else:
        assert clock[0] == 1
        assert max(sleeps) <= 0.2
        assert queries[1:] == ["fixed"] * (len(queries) - 1)


def test_status_wait_returns_on_terminal_before_deadline(monkeypatch):
    clock = [0.0]

    def lookup(root, run_id, machine):
        return dict(run_id="fixed", status="running" if clock[0] == 0 else "stopped",
                    health="running" if clock[0] == 0 else "stopped")

    def sleep(duration):
        clock[0] += duration

    monkeypatch.setattr(cli, "_status", lookup)
    monkeypatch.setattr(cli.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(cli.time, "sleep", sleep)
    result = runner.invoke(cli.app, ["status", "--wait", "30", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["status"] == "stopped"
    assert clock[0] == 0.2


def _win_sharing_error() -> OSError:
    exc = PermissionError("sharing violation")
    exc.winerror = 32  # type: ignore[attr-defined]
    return exc


def test_non_terminal_event_skips_windows_sharing_conflict_but_finish_does_not(tmp_path, monkeypatch):
    monkeypatch.setattr(session.time, "sleep", lambda _: None)
    with RunSession(tmp_path, mode="battle", champion="jinx", device="fake", heartbeat_s=100) as run:
        def fail_replace(src, dst):
            raise _win_sharing_error()

        monkeypatch.setattr(session.os, "replace", fail_replace)
        run.report("recognize", progress=True)
        # events.jsonl 已写入，游戏主循环未被共享冲突打崩。
        events = [json.loads(line) for line in (run.path / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        assert any(e["type"] == "phase" and e["payload"]["phase"] == "recognize" for e in events)
        # 终态 finish 严禁跳过共享冲突，且 __exit__ 在锁恢复后仍会补写终态到磁盘。
        with pytest.raises(PermissionError):
            run.finish("stopped", "done")
        assert run._terminal_unpersisted is True
        monkeypatch.undo()
    saved = read_status(tmp_path, run.run_id)
    assert saved["status"] == "stopped"
    assert saved["reason"] == "done"


def test_read_status_retries_short_sharing_conflict(tmp_path, monkeypatch):
    monkeypatch.setattr(session.time, "sleep", lambda _: None)
    with RunSession(tmp_path, mode="battle", champion="jinx", device="fake", heartbeat_s=100) as run:
        run.finish("completed", "done")
        real_read_text = Path.read_text
        attempts = [0]

        def flaky_read_text(self, *args, **kwargs):
            if self.name == "status.json" and attempts[0] < 2:
                attempts[0] += 1
                raise _win_sharing_error()
            return real_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", flaky_read_text)
        status = read_status(tmp_path, run.run_id)
        assert status["status"] == "completed"
        assert attempts[0] == 2


def test_heartbeat_thread_survives_non_sharing_oserror(tmp_path, monkeypatch):
    calls = [0]
    with RunSession(tmp_path, mode="battle", champion="jinx", device="fake", heartbeat_s=0.02) as run:
        real_persist = run._persist

        def flaky_persist(*args, **kwargs):
            calls[0] += 1
            if calls[0] == 1:
                raise OSError("transient disk error")
            return real_persist(*args, **kwargs)

        monkeypatch.setattr(run, "_persist", flaky_persist)
        deadline = session.time.monotonic() + 2.0
        while session.time.monotonic() < deadline and calls[0] < 2:
            session.time.sleep(0.02)
        assert calls[0] >= 2
        assert run._thread is not None and run._thread.is_alive()
        run.finish("completed", "done")
