"""Wake an optional fifth-layer `improve` agent while a fourth-layer /goal runs.

Run inside a Herdr pane below the improve session; the improve agent starts it itself:

    python3 tools/goal/notify.py <goal-pane> "$HERDR_PANE_ID"
    python3 tools/goal/notify.py w5:pJ w5:p5 --tick-interval 1800 --interval 60 --confirm 3

The notifier makes no decisions. Every `--interval` seconds it reads the goal pane
and sends prompts to the improve pane through `herdr agent prompt`, which starts
a full agent turn there:

- tick: every `--tick-interval` seconds, a read-only check-in on the goal;
- event: once the goal has stopped for `--confirm` consecutive reads (not inside a
  turn and not at the 50-turn pause, which `watch.py` handles) or its agent is
  gone, it sends the hand-over prompt and exits.

Prompts are only sent while the improve agent is `idle` or `done` in Herdr, so a
conversation or turn already running there is never interrupted: a tick that
finds it busy is skipped until the next tick, the hand-over is retried every read.

"Inside a turn" is read from the input placeholder and spinner lines, not from
the footer's `Goal running`, because narrow panes truncate the footer.
To stop it on purpose, create the `.off` file next to its log
(`logs/improve/notify-<goal>.off`); it exits within one interval.
Exit codes: 0 the hand-over prompt was sent, the `.off` file exists, or another notifier holds the lock,
1 herdr stayed unreachable, 2 bad arguments. Log and lock default to
`logs/improve/notify-<goal>.log|.lock` (ignored by Git).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from watch import (  # noqa: E402
    GOAL_STATUS_PREFIXES,
    PAUSE_PREFIX,
    acquire_lock,
    agent_exists,
    in_turn,
    log,
    read_screen,
)

WORKING, PAUSED, STOPPED = "working", "paused", "stopped"
READY_STATES = ("idle", "done")

TICK_TEXT = ("[improve-tick] 定时只读检查第四层 goal（pane {goal}，当前 {state}）。"
             "按 workflows/improve.md「运行期」规则把观察记到 logs/improve/notes.md，不改仓库文件，不打断 goal。")
EVENT_TEXT = ("[improve-notify] 第四层 goal（pane {goal}）{what}，已连续 {count} 次确认。"
              "按 workflows/improve.md「收口优化」规则先核对 goal 已结束、本机工作区干净、"
              "f1 无非终态会话，再按 logs/improve/notes.md 的记录接手收口。")


def goal_state(screen: str) -> str:
    lines = [line.strip() for line in screen.splitlines() if line.strip()]
    if in_turn(lines):
        return WORKING
    statuses = [line for line in lines if line.startswith(GOAL_STATUS_PREFIXES)]
    if statuses and statuses[-1].startswith(PAUSE_PREFIX):
        return PAUSED
    return STOPPED


def agent_status(target: str) -> str | None:
    """Herdr lifecycle state of the agent in target, or None if it cannot be read."""
    try:
        result = subprocess.run(
            ["herdr", "agent", "get", target],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)["result"]["agent"]["agent_status"]
    except (subprocess.TimeoutExpired, OSError, ValueError, KeyError, TypeError):
        return None


def send_prompt(target: str, text: str) -> bool:
    try:
        result = subprocess.run(
            ["herdr", "agent", "prompt", target, text],
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0


def notify(
    goal: str,
    improve: str,
    *,
    tick_s: float,
    interval: float,
    confirm: int,
    log_path: Path,
    lock_path: Path,
    max_read_errors: int = 10,
) -> int:
    lock = acquire_lock(lock_path)
    if lock is None:
        log(log_path, f"exit: another notifier already holds lock for {goal}")
        return 0
    try:
        stopped = read_errors = 0
        next_tick = time.monotonic() + tick_s
        log(log_path, f"notifying {improve} about {goal} tick={tick_s:.0f}s interval={interval}s confirm={confirm}")
        off_path = log_path.with_suffix(".off")
        while True:
            if off_path.exists():
                log(log_path, f"exit: disabled by {off_path}")
                return 0
            screen = read_screen(goal)
            if screen is None:
                exists = agent_exists(goal)
                if exists is None:
                    read_errors += 1
                    if read_errors >= max_read_errors:
                        log(log_path, f"exit: herdr unreachable for {read_errors} reads")
                        return 1
                    state = None
                else:
                    read_errors = 0
                    state = "gone" if exists is False else None
            else:
                read_errors = 0
                state = goal_state(screen)
            stopped = stopped + 1 if state in (STOPPED, "gone") else 0
            if stopped >= confirm:
                improve_state = agent_status(improve)
                what = "的 agent 已消失" if state == "gone" else "已停止（不在回合内，也不是 50 轮暂停）"
                if improve_state not in READY_STATES:
                    log(log_path, f"hand-over deferred: improve is {improve_state}")
                elif send_prompt(improve, EVENT_TEXT.format(goal=goal, what=what, count=stopped)):
                    log(log_path, f"exit: hand-over sent after {stopped} {state} reads")
                    return 0
                else:
                    log(log_path, "hand-over prompt failed, retrying next read")
            elif time.monotonic() >= next_tick:
                improve_state = agent_status(improve)
                if improve_state in READY_STATES:
                    sent = send_prompt(improve, TICK_TEXT.format(goal=goal, state=state or "unknown"))
                    log(log_path, f"tick sent={sent} goal={state}")
                else:
                    log(log_path, f"tick skipped: improve is {improve_state}")
                next_tick = time.monotonic() + tick_s
            time.sleep(interval)
    finally:
        lock.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("goal", help="Herdr pane id or agent name hosting the fourth-layer goal")
    parser.add_argument("improve", help="Herdr pane id or agent name of the improve agent to wake")
    parser.add_argument("--tick-interval", type=float, default=1800.0, help="seconds between [improve-tick] prompts")
    parser.add_argument("--interval", type=float, default=60.0)
    parser.add_argument("--confirm", type=int, default=3)
    parser.add_argument("--max-read-errors", type=int, default=10)
    parser.add_argument("--log", type=Path)
    parser.add_argument("--lock", type=Path)
    args = parser.parse_args(argv)
    safe = args.goal.replace(":", "-")
    return notify(
        args.goal,
        args.improve,
        tick_s=args.tick_interval,
        interval=args.interval,
        confirm=args.confirm,
        log_path=args.log or Path("logs/improve") / f"notify-{safe}.log",
        lock_path=args.lock or Path("logs/improve") / f"notify-{safe}.lock",
        max_read_errors=args.max_read_errors,
    )


if __name__ == "__main__":
    sys.exit(main())
