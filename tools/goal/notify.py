"""Wake an optional fifth-layer `improve` agent while a fourth-layer /goal runs.

Run inside a Herdr pane below the improve session; the improve agent starts it itself:

    python3 tools/goal/notify.py <goal-pane> "$HERDR_PANE_ID"
    python3 tools/goal/notify.py w5:pJ w5:p5 --tick-min 20 --interval 60 --confirm 3

The notifier makes no decisions. Every `--interval` seconds it reads the goal pane
and sends prompts to the improve pane through `herdr agent prompt`, which starts
a full agent turn there:

- tick: every `--tick-min` minutes, a read-only check-in on the goal;
- event: once the goal has stopped for `--confirm` consecutive reads (not inside a
  turn and not at the 50-turn pause, which `watch.py` handles) or its agent is
  gone, it sends the hand-over prompt and exits.

"Inside a turn" is read from the input placeholder and spinner lines, not from
the footer's `Goal running`, because narrow panes truncate the footer.
Exit codes: 0 the hand-over prompt was sent or another notifier holds the lock,
1 herdr stayed unreachable, 2 bad arguments. Log and lock default to
`logs/goals/notify-<goal>.log|.lock` (ignored by Git).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from watch import GOAL_STATUS_PREFIXES, PAUSE_PREFIX, acquire_lock, agent_exists, log, read_screen  # noqa: E402

IN_TURN_MARKERS = ("Guide Devin while it works", "Running tools", "Thinking")
WORKING, PAUSED, STOPPED = "working", "paused", "stopped"

TICK_TEXT = ("[improve-tick] 定时只读检查第四层 goal（pane {goal}，当前 {state}）。"
             "按 workflows/dev-iteration.md 第五层「运行期」规则记录观察，不改仓库文件，不打断 goal。")
EVENT_TEXT = ("[improve-notify] 第四层 goal（pane {goal}）{what}，已连续 {count} 次确认。"
              "按 workflows/dev-iteration.md 第五层「收口优化」规则先核对 goal 已结束、本机工作区干净、"
              "f1 无非终态会话，再接手收口。")


def goal_state(screen: str) -> str:
    lines = [line.strip() for line in screen.splitlines() if line.strip()]
    if any(marker in line for line in lines[-8:] for marker in IN_TURN_MARKERS):
        return WORKING
    statuses = [line for line in lines if line.startswith(GOAL_STATUS_PREFIXES)]
    if statuses and statuses[-1].startswith(PAUSE_PREFIX):
        return PAUSED
    return STOPPED


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
        while True:
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
                what = "的 agent 已消失" if state == "gone" else "已停止（不在回合内，也不是 50 轮暂停）"
                if send_prompt(improve, EVENT_TEXT.format(goal=goal, what=what, count=stopped)):
                    log(log_path, f"exit: hand-over sent after {stopped} {state} reads")
                    return 0
                log(log_path, "hand-over prompt failed, retrying next read")
            elif time.monotonic() >= next_tick:
                sent = send_prompt(improve, TICK_TEXT.format(goal=goal, state=state or "unknown"))
                log(log_path, f"tick sent={sent} state={state}")
                if sent:
                    next_tick = time.monotonic() + tick_s
            time.sleep(interval)
    finally:
        lock.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("goal", help="Herdr pane id or agent name hosting the fourth-layer goal")
    parser.add_argument("improve", help="Herdr pane id or agent name of the improve agent to wake")
    parser.add_argument("--tick-min", type=float, default=20.0)
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
        tick_s=args.tick_min * 60,
        interval=args.interval,
        confirm=args.confirm,
        log_path=args.log or Path("logs/goals") / f"notify-{safe}.log",
        lock_path=args.lock or Path("logs/goals") / f"notify-{safe}.lock",
        max_read_errors=args.max_read_errors,
    )


if __name__ == "__main__":
    sys.exit(main())
