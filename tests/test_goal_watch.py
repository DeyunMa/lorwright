"""/goal 看守的画面判定与鲁棒性测试。画面文字取自 2026-11-19 Devin CLI v3000.14.30821 实测。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_watch():
    path = Path(__file__).resolve().parents[1] / "tools" / "goal" / "watch.py"
    spec = importlib.util.spec_from_file_location("goal_watch", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["goal_watch"] = module
    spec.loader.exec_module(module)
    return module


PROMPT_BOX = """
 ⏺ /private/tmp/goaltest
────────────────────────────────────────── Append next integer to counter.txt, one… ─
❭ Ask Devin to build features, fix bugs, or work on your code
──────────────────────────────────────────────────────────────────────────────────────
"""

RUNNING = """
 ✱ Continuing goal (turn 47)
""" + PROMPT_BOX + "Claude Opus 5.5 High · bypass · ⏺ Goal running        ctrl+v to paste image\n"

PAUSED = """
 ✱ Continuing goal (turn 50)

 ✓ f=/tmp/goaltest/counter.txt; echo $n >> $f; …

 已追加

 ✱ Goal paused after 50 turns. Use /goal resume to continue.
""" + PROMPT_BOX + "Claude Opus 5.5 High · bypass        ctrl+v to paste image\n"

COMPLETE = """
 ✱ Continuing goal (turn 55)

 ✓ f=/tmp/goaltest/counter.txt; echo $n >> $f; …

 ✓ Goal complete
""" + PROMPT_BOX + "Claude Opus 5.5 High · bypass · ✓ Goal complete        ctrl+v to paste image\n"

RESUMED_LATER_STOPPED = """
 ✱ Goal paused after 50 turns. Use /goal resume to continue.

 ✱ Continuing goal (turn 51)

 用户按 Esc 中断
""" + PROMPT_BOX + "Claude Opus 5.5 High · bypass        ctrl+v to paste image\n"


def test_running_goal_is_left_alone() -> None:
    assert _load_watch().classify(RUNNING) == "running"


def test_turn_limit_pause_requests_resume() -> None:
    assert _load_watch().classify(PAUSED) == "resume"


def test_completed_goal_ends_the_watch() -> None:
    assert _load_watch().classify(COMPLETE) == "ended"


def test_stop_after_an_earlier_pause_is_not_resumed() -> None:
    assert _load_watch().classify(RESUMED_LATER_STOPPED) == "ended"


def test_screen_without_goal_status_ends_the_watch() -> None:
    assert _load_watch().classify(PROMPT_BOX) == "ended"


def test_quoted_goal_running_or_tool_line_in_body_does_not_mask_pause() -> None:
    screen = """
 ✱ Continuing goal (turn 50)

 ✓ rg "Goal running" workflows/dev-iteration.md

 文档中提到底栏会显示 Goal running 直到第 50 轮。

 ✱ Goal paused after 50 turns. Use /goal resume to continue.
""" + PROMPT_BOX + "Claude Opus 5.5 High · bypass        ctrl+v to paste image\n"
    assert _load_watch().classify(screen) == "resume"


def test_resume_limit_leaves_goal_paused(monkeypatch, tmp_path) -> None:
    mod = _load_watch()
    sent: list[str] = []
    monkeypatch.setattr(mod, "read_screen", lambda target: PAUSED)
    monkeypatch.setattr(mod, "send_resume", lambda target: sent.append(target) or True)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    log = tmp_path / "watch.log"
    assert mod.watch("w1:p1", 0, 2, 2, log) == 3
    assert sent == ["w1:p1", "w1:p1"]
    assert "resume limit 2 reached" in log.read_text(encoding="utf-8")


def test_missing_agent_exits_after_confirmation(monkeypatch, tmp_path) -> None:
    mod = _load_watch()
    monkeypatch.setattr(mod, "read_screen", lambda target: None)
    monkeypatch.setattr(mod, "agent_exists", lambda target: False)
    monkeypatch.setattr(mod, "send_resume", lambda target: (_ for _ in ()).throw(AssertionError))
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    log = tmp_path / "watch.log"
    assert mod.watch("w1:p1", 0, 10, 2, log) == 0
    assert "agent not found" in log.read_text(encoding="utf-8")


def test_transient_read_failure_does_not_exit_while_agent_alive(monkeypatch, tmp_path) -> None:
    mod = _load_watch()
    screens = iter([None, None, None, COMPLETE, COMPLETE])
    monkeypatch.setattr(mod, "read_screen", lambda target: next(screens))
    monkeypatch.setattr(mod, "agent_exists", lambda target: True)
    monkeypatch.setattr(mod, "send_resume", lambda target: (_ for _ in ()).throw(AssertionError))
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    log = tmp_path / "watch.log"
    assert mod.watch("w1:p1", 0, 10, 2, log) == 0
    text = log.read_text(encoding="utf-8")
    assert "read failed (3/10)" in text
    assert "goal no longer active" in text


def test_herdr_unreachable_exits_after_max_read_errors(monkeypatch, tmp_path) -> None:
    mod = _load_watch()
    monkeypatch.setattr(mod, "read_screen", lambda target: None)
    monkeypatch.setattr(mod, "agent_exists", lambda target: None)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    log = tmp_path / "watch.log"
    assert mod.watch("w1:p1", 0, 10, 2, log, max_read_errors=3) == 1
    assert "herdr unreachable for 3 reads" in log.read_text(encoding="utf-8")


def test_single_instance_lock_prevents_duplicate_watcher(monkeypatch, tmp_path) -> None:
    mod = _load_watch()
    lock = tmp_path / "watch.lock"
    log = tmp_path / "watch.log"
    holder = mod.acquire_lock(lock)
    assert holder is not None
    try:
        monkeypatch.setattr(mod, "read_screen", lambda target: (_ for _ in ()).throw(AssertionError))
        assert mod.watch("w1:p1", 0, 10, 2, log, lock_path=lock) == 0
        assert "already holds lock" in log.read_text(encoding="utf-8")
    finally:
        holder.close()
    reacquired = mod.acquire_lock(lock)
    assert reacquired is not None
    reacquired.close()
