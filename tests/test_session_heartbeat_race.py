"""Windows 状态文件共享冲突的恢复与可观测性。"""

import json
import threading

import pytest

from lorwright.core.runtime import session


def sharing_error():
    error = PermissionError("sharing conflict")
    error.winerror = 5
    return error


def test_atomic_replace_retries_and_cleans_up(tmp_path, monkeypatch):
    path = tmp_path / "status.json"
    path.write_text('{"old": true}')
    replace = session.os.replace
    attempts = []

    def flaky(source, target):
        attempts.append(source)
        if len(attempts) < 3:
            raise sharing_error()
        replace(source, target)

    monkeypatch.setattr(session.os, "replace", flaky)
    monkeypatch.setattr(session.time, "sleep", lambda _: None)
    session._atomic_json(path, {"new": True})
    assert len(attempts) == 3
    assert json.loads(path.read_text()) == {"new": True}
    assert list(tmp_path.iterdir()) == [path]


def test_atomic_replace_persistent_conflict_preserves_original(tmp_path, monkeypatch):
    path = tmp_path / "status.json"
    path.write_text('{"old": true}')
    attempts = []

    def fail(source, target):
        attempts.append(source)
        raise sharing_error()

    monkeypatch.setattr(session.os, "replace", fail)
    monkeypatch.setattr(session.time, "sleep", lambda _: None)
    with pytest.raises(PermissionError):
        session._atomic_json(path, {"new": True})
    assert len(attempts) == 5
    assert json.loads(path.read_text()) == {"old": True}
    assert list(tmp_path.iterdir()) == [path]


def test_heartbeat_recovers_after_persistent_conflict(tmp_path, monkeypatch, capsys):
    run = session.RunSession(tmp_path, mode="battle", champion="", device=str(tmp_path),
                             heartbeat_s=0.01)
    with run:
        failed = threading.Event()
        recovered = threading.Event()
        allow = threading.Event()
        original = run._persist
        before = session.read_status(tmp_path, run.run_id)["heartbeat_at"]

        def persist():
            if threading.current_thread().name == "run-heartbeat":
                if not allow.is_set():
                    failed.set()
                    raise sharing_error()
                original()
                recovered.set()
            else:
                original()

        monkeypatch.setattr(run, "_persist", persist)
        assert failed.wait(2)
        with run._mutex:
            assert run._status["heartbeat_at"] == before
        assert session.read_status(tmp_path, run.run_id)["heartbeat_at"] == before
        assert run._thread.is_alive()
        allow.set()
        assert recovered.wait(2)
        with run._mutex:
            assert run._status["heartbeat_at"] > before
        assert session.read_status(tmp_path, run.run_id)["heartbeat_at"] > before
    output = capsys.readouterr().err
    assert "状态访问失败" in output
    assert "状态访问已恢复" in output
