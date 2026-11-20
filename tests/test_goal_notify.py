"""第五层唤醒器的画面判定与唤醒时序测试。画面取自 2026-11-20 goal-jinx（67 列窄 pane）实测。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_notify():
    path = Path(__file__).resolve().parents[1] / "tools" / "goal" / "notify.py"
    spec = importlib.util.spec_from_file_location("goal_notify", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["goal_notify"] = module
    spec.loader.exec_module(module)
    return module


IN_TURN_TRUNCATED = """
 ✓ cd /Users/mdy/Code/my-own/lorwright && logs/goals/pull.sh 20…
 ⏺ cd /Users/mdy/Code/my-own/lorwright && for i in 1 2 3 4 5; d…
⠈⠉ Running tools · 3m 2s (esc twice to interrupt)
────────────────────── 按 dev-iteration.md 执行第四层循环并验… ─
❭ Guide Devin while it works
────────────────────────────────────────────────────────────────
Claude Opus 5.5 Medium Fast · bypass · 1 shell ↓ · ⏺ Goal r…
"""

IDLE_BOX = """
────────────────────── 按 dev-iteration.md 执行第四层循环并验… ─
❭ Ask Devin to build features, fix bugs, or work on your code
────────────────────────────────────────────────────────────────
"""

PAUSED = """
 ✱ Continuing goal (turn 50)
 已追加
 ✱ Goal paused after 50 turns. Use /goal resume to continue.
""" + IDLE_BOX + "Claude Opus 5.5 Medium Fast · bypass        ctrl+v t…\n"

COMPLETE = """
 ✱ Continuing goal (turn 12)
 ✓ Goal complete
""" + IDLE_BOX + "Claude Opus 5.5 Medium Fast · bypass · ✓ Goal complete\n"

CANCELED = """
 ✓ R=20261120T035554-905357f970d3; mkdir -p logs/f1-pulls/$R && scp -q …
 ✱ Canceled. What should Devin do?
""" + IDLE_BOX + "Claude Opus 5.5 Medium Fast · bypass · ⏺ Goal running\n"


def test_truncated_footer_inside_a_turn_is_working() -> None:
    assert _load_notify().goal_state(IN_TURN_TRUNCATED) == "working"


def test_turn_limit_pause_is_left_to_the_watcher() -> None:
    assert _load_notify().goal_state(PAUSED) == "paused"


def test_complete_and_canceled_goals_count_as_stopped() -> None:
    mod = _load_notify()
    assert mod.goal_state(COMPLETE) == "stopped"
    assert mod.goal_state(CANCELED) == "stopped"


def _run(mod, monkeypatch, tmp_path, screens, *, tick_s=1e9, confirm=3, send_ok=True, improve=None):
    sent: list[str] = []
    improve_states = iter(improve) if improve is not None else None
    screens = iter(screens)
    clock = iter(range(0, 10_000, 100))
    monkeypatch.setattr(mod, "read_screen", lambda target: next(screens))
    monkeypatch.setattr(mod, "agent_exists", lambda target: False)
    monkeypatch.setattr(mod, "agent_status", lambda target: next(improve_states) if improve_states else "idle")
    monkeypatch.setattr(mod, "send_prompt", lambda target, text: sent.append(text) or send_ok)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(mod.time, "monotonic", lambda: next(clock))
    code = mod.notify("w5:pJ", "w5:p5", tick_s=tick_s, interval=0, confirm=confirm,
                      log_path=tmp_path / "n.log", lock_path=tmp_path / "n.lock")
    return code, sent


def test_hand_over_needs_consecutive_stopped_reads(monkeypatch, tmp_path) -> None:
    mod = _load_notify()
    screens = [COMPLETE, IN_TURN_TRUNCATED, COMPLETE, COMPLETE, COMPLETE]
    code, sent = _run(mod, monkeypatch, tmp_path, screens)
    assert code == 0
    assert len(sent) == 1 and sent[0].startswith("[improve-notify]")


def test_pause_never_triggers_hand_over(monkeypatch, tmp_path) -> None:
    mod = _load_notify()
    screens = [PAUSED] * 5 + [COMPLETE] * 3
    code, sent = _run(mod, monkeypatch, tmp_path, screens)
    assert code == 0
    assert [text[:16] for text in sent] == ["[improve-notify]"]


def test_vanished_goal_agent_triggers_hand_over(monkeypatch, tmp_path) -> None:
    mod = _load_notify()
    code, sent = _run(mod, monkeypatch, tmp_path, [None, None, None])
    assert code == 0
    assert "已消失" in sent[0]


def test_ticks_wake_the_improve_agent_while_the_goal_works(monkeypatch, tmp_path) -> None:
    mod = _load_notify()
    screens = [IN_TURN_TRUNCATED] * 6 + [COMPLETE] * 3
    code, sent = _run(mod, monkeypatch, tmp_path, screens, tick_s=200)
    ticks = [text for text in sent if text.startswith("[improve-tick]")]
    assert code == 0
    assert len(ticks) >= 2
    assert sent[-1].startswith("[improve-notify]")


def test_failed_hand_over_is_retried(monkeypatch, tmp_path) -> None:
    mod = _load_notify()
    attempts: list[str] = []
    results = iter([False, True])
    screens = iter([COMPLETE] * 5)
    monkeypatch.setattr(mod, "read_screen", lambda target: next(screens))
    monkeypatch.setattr(mod, "agent_status", lambda target: "idle")
    monkeypatch.setattr(mod, "send_prompt", lambda target, text: attempts.append(text) or next(results))
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    code = mod.notify("w5:pJ", "w5:p5", tick_s=1e9, interval=0, confirm=3,
                      log_path=tmp_path / "n.log", lock_path=tmp_path / "n.lock")
    assert code == 0
    assert len(attempts) == 2


def test_second_notifier_exits_on_the_lock(monkeypatch, tmp_path) -> None:
    mod = _load_notify()
    holder = mod.acquire_lock(tmp_path / "n.lock")
    try:
        monkeypatch.setattr(mod, "read_screen", lambda target: (_ for _ in ()).throw(AssertionError))
        assert mod.notify("w5:pJ", "w5:p5", tick_s=60, interval=0, confirm=3,
                          log_path=tmp_path / "n.log", lock_path=tmp_path / "n.lock") == 0
        assert "already holds lock" in (tmp_path / "n.log").read_text(encoding="utf-8")
    finally:
        holder.close()


def test_tick_is_skipped_while_the_improve_agent_is_busy(monkeypatch, tmp_path) -> None:
    mod = _load_notify()
    sent: list[str] = []
    screens = iter([IN_TURN_TRUNCATED] * 6 + [COMPLETE] * 3)
    current = {"screen": None}
    clock = iter(range(0, 10_000, 100))

    def read(target):
        current["screen"] = next(screens)
        return current["screen"]

    monkeypatch.setattr(mod, "read_screen", read)
    monkeypatch.setattr(mod, "agent_status",
                        lambda target: "working" if current["screen"] is IN_TURN_TRUNCATED else "idle")
    monkeypatch.setattr(mod, "send_prompt", lambda target, text: sent.append(text) or True)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(mod.time, "monotonic", lambda: next(clock))
    code = mod.notify("w5:pJ", "w5:p5", tick_s=150, interval=0, confirm=3,
                      log_path=tmp_path / "n.log", lock_path=tmp_path / "n.lock")
    log = (tmp_path / "n.log").read_text(encoding="utf-8")
    assert code == 0
    assert "tick skipped: improve is working" in log
    assert sent[-1].startswith("[improve-notify]")
    assert all("goal=working" not in line for line in log.splitlines() if "tick sent" in line)


def test_hand_over_waits_until_the_improve_agent_is_idle(monkeypatch, tmp_path) -> None:
    mod = _load_notify()
    screens = [COMPLETE] * 6
    code, sent = _run(mod, monkeypatch, tmp_path, screens, improve=["working", "blocked", "done"])
    assert code == 0
    assert len(sent) == 1 and sent[0].startswith("[improve-notify]")
    text = (tmp_path / "n.log").read_text(encoding="utf-8")
    assert "hand-over deferred: improve is working" in text
    assert "hand-over deferred: improve is blocked" in text


def test_cli_defaults_to_twenty_minute_ticks_and_improve_logs(monkeypatch) -> None:
    mod = _load_notify()
    seen = {}
    monkeypatch.setattr(mod, "notify", lambda goal, improve, **kw: seen.update(kw) or 0)
    assert mod.main(["w5:pJ", "w5:p5"]) == 0
    assert seen["tick_s"] == 1800
    assert str(seen["log_path"]) == "logs/improve/notify-w5-pJ.log"
    assert str(seen["lock_path"]) == "logs/improve/notify-w5-pJ.lock"


def test_off_file_stops_the_notifier(monkeypatch, tmp_path) -> None:
    mod = _load_notify()
    (tmp_path / "n.off").write_text("", encoding="utf-8")
    monkeypatch.setattr(mod, "read_screen", lambda target: (_ for _ in ()).throw(AssertionError))
    assert mod.notify("w5:pJ", "w5:p5", tick_s=60, interval=0, confirm=3,
                      log_path=tmp_path / "n.log", lock_path=tmp_path / "n.lock") == 0
    assert "disabled by" in (tmp_path / "n.log").read_text(encoding="utf-8")
