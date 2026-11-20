"""tools/f1/sync.py 的参数校验、命令构造、结果解析与预检拦截测试（纯离线，不连 f1）。"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


def _load_sync():
    path = Path(__file__).resolve().parents[1] / "tools" / "f1" / "sync.py"
    spec = importlib.util.spec_from_file_location("f1_sync", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["f1_sync"] = module
    spec.loader.exec_module(module)
    return module


def _proc(stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["ssh"], returncode=returncode, stdout=stdout, stderr=stderr)


def test_ssh_command_uses_stdin_and_stays_under_windows_limit() -> None:
    mod = _load_sync()
    cmd = mod.build_ssh_command("f1")
    assert cmd[-2:] == ["-Command", "-"]
    assert len(" ".join(cmd)) < 8000


def test_build_remote_script_uses_continue_utf8_and_flags() -> None:
    mod = _load_sync()
    sha = "a" * 40
    preview = mod.build_remote_script(r"C:\Code\lorwright", "main", apply=False, skip_deps=False, expect_head=sha)
    assert preview.startswith("& {\n")
    assert preview.endswith("}\n\n")
    assert "$ErrorActionPreference = 'Continue'" in preview
    assert "-Encoding UTF8" in preview
    assert "$apply = $false" in preview
    assert "$skipDeps = $false" in preview
    assert f"$expectHead = '{sha}'" in preview
    applied = mod.build_remote_script(r"C:\Code\lorwright", "main", apply=True, skip_deps=True)
    assert "$apply = $true" in applied
    assert "$skipDeps = $true" in applied
    assert "$expectHead = $null" in applied


def test_sync_f1_parses_successful_apply_with_stale_sessions_warning(monkeypatch) -> None:
    mod = _load_sync()
    payload = {
        "ok": True,
        "applied": True,
        "repo": r"C:\Code\lorwright",
        "branch": "main",
        "before_head": "a" * 40,
        "target_head": "b" * 40,
        "after_head": "b" * 40,
        "already_up_to_date": False,
        "deps_changed": True,
        "deps_installed": True,
        "blocked_reason": None,
        "stale_sessions": [{"run_id": "20261119T000000-dead", "status": "running"}],
    }
    monkeypatch.setattr(mod, "run_remote_powershell", lambda host, script, timeout=600: _proc(json.dumps(payload)))
    result = mod.sync_f1("f1", r"C:\Code\lorwright", "main", apply=True, expect_head="b" * 40)
    assert result["ok"] is True
    assert result["applied"] is True
    assert result["deps_installed"] is True
    assert len(result["stale_sessions"]) == 1
    assert result["host"] == "f1"


def test_sync_f1_reports_blocked_preflight_and_target_mismatch(monkeypatch) -> None:
    mod = _load_sync()
    payload = {
        "ok": False,
        "applied": False,
        "blocked_reason": "target_mismatch",
        "target_head": "c" * 40,
        "expect_head": "b" * 40,
    }
    monkeypatch.setattr(mod, "run_remote_powershell", lambda host, script, timeout=600: _proc(json.dumps(payload)))
    result = mod.sync_f1("f1", r"C:\Code\lorwright", "main", apply=True, expect_head="b" * 40)
    assert result["ok"] is False
    assert result["blocked_reason"] == "target_mismatch"


def test_sync_f1_handles_ssh_timeout_with_hint(monkeypatch) -> None:
    mod = _load_sync()

    def _timeout(host, script, timeout=600):
        raise subprocess.TimeoutExpired(cmd="ssh", timeout=timeout)

    monkeypatch.setattr(mod, "run_remote_powershell", _timeout)
    result = mod.sync_f1("f1", r"C:\Code\lorwright", "main")
    assert result["ok"] is False
    assert result["blocked_reason"] == "ssh_timeout"
    assert "re-run preview" in result["hint"]


def test_sync_f1_handles_ssh_nonzero_exit(monkeypatch) -> None:
    mod = _load_sync()
    monkeypatch.setattr(
        mod,
        "run_remote_powershell",
        lambda host, script, timeout=600: _proc(stderr="Permission denied", returncode=255),
    )
    result = mod.sync_f1("f1", r"C:\Code\lorwright", "main")
    assert result["ok"] is False
    assert result["blocked_reason"] == "ssh_failed"
    assert result["returncode"] == 255


def test_main_rejects_unsafe_args() -> None:
    mod = _load_sync()
    with pytest.raises(SystemExit) as exc1:
        mod.main(["--host", "f1; rm -rf /"])
    assert exc1.value.code == 2
    with pytest.raises(SystemExit) as exc2:
        mod.main(["--repo", r"C:\Code\lorwright'; whoami"])
    assert exc2.value.code == 2
    with pytest.raises(SystemExit) as exc3:
        mod.main(["--expect", "not-a-sha"])
    assert exc3.value.code == 2


def test_main_passes_local_head_unless_any_target(monkeypatch, capsys) -> None:
    mod = _load_sync()
    seen: list[str | None] = []
    sha = "d" * 40
    monkeypatch.setattr(mod, "local_head", lambda: sha)

    def _fake_sync(*a, **kw):
        seen.append(kw.get("expect_head"))
        return {"ok": True, "applied": False}

    monkeypatch.setattr(mod, "sync_f1", _fake_sync)
    assert mod.main(["--host", "f1"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert mod.main(["--host", "f1", "--any-target"]) == 0
    capsys.readouterr()
    assert seen == [sha, None]
