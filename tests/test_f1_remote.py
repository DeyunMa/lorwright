"""tools/f1/remote.py 的远端脚本、解析与等待逻辑测试（纯离线，不连 f1）。"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


def _load():
    path = Path(__file__).resolve().parents[1] / "tools" / "f1" / "remote.py"
    spec = importlib.util.spec_from_file_location("f1_remote", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["f1_remote"] = module
    spec.loader.exec_module(module)
    return module


def _proc(stdout="", returncode=0):
    return subprocess.CompletedProcess(args=["ssh"], returncode=returncode, stdout=stdout, stderr="")


def test_remote_scripts_run_as_one_block_and_connect_adb_in_the_same_call() -> None:
    mod = _load()
    for body in (mod.shot_body(), mod.focus_body(), mod.net_body(), mod.status_body("R", 30)):
        script = mod.ps_script(body)
        assert script.startswith("& {\n") and script.endswith("}\n\n")
    assert "connect 127.0.0.1:5555" in mod.shot_body() and "connect 127.0.0.1:5555" in mod.focus_body()


def test_live_screenshot_is_pulled_as_a_file_not_redirected() -> None:
    body = _load().shot_body()
    assert "screencap -p /sdcard/lw-live.png" in body
    assert "pull /sdcard/lw-live.png" in body and "logs\\live\\live.png" in body
    assert "exec-out" not in body and " > " not in body


def test_ssh_calls_cannot_hang_on_a_half_open_link(monkeypatch) -> None:
    mod = _load()
    seen = {}
    monkeypatch.setattr(mod.subprocess, "run", lambda cmd, **kw: seen.update(cmd=cmd, kw=kw) or _proc())
    mod.run_ps("f1", "Get-Date", timeout=5)
    assert "BatchMode=yes" in seen["cmd"] and "ServerAliveInterval=10" in seen["cmd"]
    assert seen["cmd"][-1] == "-" and seen["kw"]["input"].startswith("& {")
    scp = mod.scp_command("f1", ["C:/Code/lorwright/logs/runs/R/snapshots"], Path("logs/f1-pulls/R"))
    assert "f1:C:/Code/lorwright/logs/runs/R/snapshots" in scp and "ServerAliveInterval=10" in scp


def test_status_parser_skips_console_noise() -> None:
    mod = _load()
    assert mod.parse_status('warning\n{"status": "running", "health": "waiting"}')["status"] == "running"
    assert mod.parse_status("no json here") is None


def _wait(mod, monkeypatch, outputs):
    outputs = iter(outputs)
    clock = iter(range(0, 10_000, 30))

    def fake(host, body, timeout=120):
        item = next(outputs)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(mod, "run_ps", fake)
    return mod.wait("f1", "R", 300, clock=lambda: next(clock))


def test_wait_returns_on_terminal_and_tolerates_ssh_errors(monkeypatch, capsys) -> None:
    mod = _load()
    running = _proc(json.dumps({"status": "running", "health": "waiting", "phase": "battle", "seq": 3}))
    stopped = _proc(json.dumps({"status": "stopped", "health": "stopped", "reason": "action_timeout", "seq": 9}))
    stopped_rc3 = subprocess.CompletedProcess(args=["ssh"], returncode=3, stdout=stopped.stdout, stderr="")
    code = _wait(mod, monkeypatch, [subprocess.TimeoutExpired("ssh", 90), _proc(returncode=255), running, stopped_rc3])
    out = capsys.readouterr().out
    assert code == 0
    assert out.count("ERR") == 2 and "action_timeout" in out


def test_wait_reports_stalled_sessions_and_budget(monkeypatch) -> None:
    mod = _load()
    stalled = _proc(json.dumps({"status": "running", "health": "stalled", "seq": 4}))
    assert _wait(mod, monkeypatch, [stalled]) == 3
    running = _proc(json.dumps({"status": "running", "health": "running", "seq": 1}))
    assert _wait(mod, monkeypatch, [running] * 20) == 4


def test_condensed_events_drop_polling_noise() -> None:
    mod = _load()
    lines = [
        json.dumps({"seq": 1, "ts_utc": "2026-11-20T07:31:28.1Z", "type": "phase", "payload": {"phase": "capture"}}),
        json.dumps({"seq": 2, "ts_utc": "2026-11-20T07:31:29.1Z", "type": "health", "payload": {}}),
        json.dumps({"seq": 3, "ts_utc": "2026-11-20T07:31:30.1Z", "type": "session_finished",
                    "payload": {"status": "stopped", "reason": "login_transition_unverified", "snapshot": "x.png"}}),
        "not json",
    ]
    out = mod.condensed_events(lines)
    assert len(out) == 1
    assert out[0].startswith("3 07:31:30 session_finished") and "login_transition_unverified" in out[0]
    assert "x.png" not in out[0]
