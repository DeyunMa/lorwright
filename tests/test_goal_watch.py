"""/goal 看守的画面判定测试。画面文字取自 2026-11-19 Devin CLI v3000.14.30821 实测。"""

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


def test_unreadable_agent_exits_after_confirmation(monkeypatch, tmp_path) -> None:
    mod = _load_watch()
    monkeypatch.setattr(mod, "read_screen", lambda target: None)
    monkeypatch.setattr(mod, "send_resume", lambda target: (_ for _ in ()).throw(AssertionError))
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    assert mod.watch("w1:p1", 0, 10, 2, tmp_path / "watch.log") == 0
