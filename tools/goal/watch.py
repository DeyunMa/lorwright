"""Resume a Devin CLI /goal that paused at its 50-turn limit.

Run inside a Herdr pane next to the goal session; the goal starts it itself:

    python3 tools/goal/watch.py w5:p5
    python3 tools/goal/watch.py w5:p5 --interval 60 --max-resumes 10

The watcher makes no decisions about the work. Every interval it reads the goal
pane's visible screen and only sends `/goal resume` when the footer no longer
shows `Goal running` and the latest goal status line is the turn-limit pause.
Any other stopped state (complete, blocked, interrupted or cleared by the user,
agent gone) ends the watcher after `--confirm` consecutive reads. Exit codes:
0 the goal is no longer active, 3 the resume limit was reached, 2 bad arguments.
Each resume and the exit reason are appended to the log
(default `logs/goals/watch-<target>.log`, ignored by Git).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PAUSE_TEXT = "Goal paused after 50 turns"
RUNNING_TEXT = "Goal running"
STATUS_MARKERS = ("✱ ", "✓ ", "✗ ", "⚠ ")

RUNNING, RESUME, ENDED = "running", "resume", "ended"


def classify(screen: str) -> str:
    if RUNNING_TEXT in screen:
        return RUNNING
    statuses = [
        line.strip()
        for line in screen.splitlines()
        if line.strip().startswith(STATUS_MARKERS) and "goal" in line.lower()
    ]
    if statuses and PAUSE_TEXT in statuses[-1]:
        return RESUME
    return ENDED


def read_screen(target: str) -> str | None:
    result = subprocess.run(
        ["herdr", "agent", "read", target, "--source", "visible"],
        capture_output=True, text=True, timeout=30,
    )
    return result.stdout if result.returncode == 0 else None


def send_resume(target: str) -> bool:
    result = subprocess.run(
        ["herdr", "agent", "prompt", target, "/goal resume"],
        capture_output=True, text=True, timeout=30,
    )
    return result.returncode == 0


def log(path: Path, message: str) -> None:
    line = f"{datetime.now().isoformat(timespec='seconds')} {message}"
    print(line, flush=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def watch(target: str, interval: float, max_resumes: int, confirm: int, log_path: Path) -> int:
    resumes = ended_reads = 0
    log(log_path, f"watching {target} interval={interval}s max_resumes={max_resumes}")
    while True:
        screen = read_screen(target)
        state = ENDED if screen is None else classify(screen)
        if state == RUNNING:
            ended_reads = 0
        elif state == RESUME:
            ended_reads = 0
            if resumes >= max_resumes:
                log(log_path, f"exit: resume limit {max_resumes} reached, goal left paused")
                return 3
            sent = send_resume(target)
            resumes += sent
            log(log_path, f"resume {resumes}/{max_resumes}" if sent else "resume submission failed, retrying next read")
        else:
            ended_reads += 1
            if ended_reads >= confirm:
                reason = "agent not readable" if screen is None else "goal no longer active"
                log(log_path, f"exit: {reason} after {resumes} resumes")
                return 0
        time.sleep(interval)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target", nargs="?", help="Herdr pane id or agent name hosting the goal")
    parser.add_argument("--interval", type=float, default=60.0)
    parser.add_argument("--max-resumes", type=int, default=10)
    parser.add_argument("--confirm", type=int, default=2, help="consecutive non-running reads before exiting")
    parser.add_argument("--log", type=Path)
    parser.add_argument("--classify", action="store_true", help="classify a screen read from stdin and exit")
    args = parser.parse_args(argv)
    if args.classify:
        print(classify(sys.stdin.read()))
        return 0
    if not args.target:
        parser.error("target is required")
    log_path = args.log or Path("logs/goals") / f"watch-{args.target.replace(':', '-')}.log"
    return watch(args.target, args.interval, args.max_resumes, args.confirm, log_path)


if __name__ == "__main__":
    sys.exit(main())
