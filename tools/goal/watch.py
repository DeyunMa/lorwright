"""Resume a Devin CLI /goal that paused at its 50-turn limit.

Run inside a Herdr pane next to the goal session; the goal starts it itself:

    python3 tools/goal/watch.py w5:p5
    python3 tools/goal/watch.py w5:p5 --interval 60 --max-resumes 10

The watcher makes no decisions about the work. Every interval it reads the goal
pane's recent unwrapped output (so narrow panes do not break the pause line) and
only sends `/goal resume` when the footer (last 3 non-empty lines) no longer
shows `Goal running` and the latest goal status line starts with the turn-limit
pause message. A per-target lock file prevents duplicate watchers after resume
or compaction. Transient read errors are checked against `herdr agent list` so
brief hiccups do not terminate the watcher early.

Exit codes:
  0  the goal is no longer active, agent is gone, or another watcher holds the lock
  1  herdr remained unreachable for `--max-read-errors` consecutive reads
  2  bad arguments
  3  the resume limit was reached

Each resume and the exit reason are appended to the log
(default `logs/goals/watch-<target>.log`, ignored by Git).
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import TextIO

PAUSE_PREFIX = "✱ Goal paused after 50 turns"
RUNNING_TEXT = "Goal running"
GOAL_STATUS_PREFIXES = (
    "✱ Continuing goal",
    "✱ Goal ",
    "✓ Goal ",
    "✗ Goal ",
    "⚠ Goal ",
)

RUNNING, RESUME, ENDED = "running", "resume", "ended"


def classify(screen: str) -> str:
    non_empty = [line.strip() for line in screen.splitlines() if line.strip()]
    footer = non_empty[-3:]
    if any(RUNNING_TEXT in line for line in footer):
        return RUNNING
    statuses = [line for line in non_empty if line.startswith(GOAL_STATUS_PREFIXES)]
    if statuses and statuses[-1].startswith(PAUSE_PREFIX):
        return RESUME
    return ENDED


def read_screen(target: str, lines: int = 40) -> str | None:
    try:
        result = subprocess.run(
            ["herdr", "agent", "read", target, "--source", "recent-unwrapped", "--lines", str(lines)],
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    return result.stdout if result.returncode == 0 else None


def agent_exists(target: str) -> bool | None:
    """Return True if target is in live Herdr agents, False if absent, None if herdr failed."""
    try:
        result = subprocess.run(
            ["herdr", "agent", "list"],
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout)
        agents = payload["result"]["agents"]
    except (ValueError, KeyError, TypeError):
        return None
    if not isinstance(agents, list):
        return None
    return any(
        isinstance(item, dict) and (item.get("pane_id") == target or item.get("name") == target)
        for item in agents
    )


def send_resume(target: str) -> bool:
    try:
        result = subprocess.run(
            ["herdr", "agent", "prompt", target, "/goal resume"],
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0


def acquire_lock(lock_path: Path) -> TextIO | None:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    handle.seek(0)
    handle.truncate()
    handle.write(f"{os.getpid()}\n")
    handle.flush()
    return handle


def log(path: Path, message: str) -> None:
    line = f"{datetime.now().isoformat(timespec='seconds')} {message}"
    print(line, flush=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def watch(
    target: str,
    interval: float,
    max_resumes: int,
    confirm: int,
    log_path: Path,
    *,
    lock_path: Path | None = None,
    max_read_errors: int = 10,
) -> int:
    resolved_lock = lock_path or log_path.with_suffix(".lock")
    lock_handle = acquire_lock(resolved_lock)
    if lock_handle is None:
        log(log_path, f"exit: another watcher already holds lock for {target}")
        return 0
    try:
        resumes = ended_reads = read_errors = 0
        log(log_path, f"watching {target} interval={interval}s max_resumes={max_resumes}")
        while True:
            screen = read_screen(target)
            if screen is None:
                exists = agent_exists(target)
                if exists is False:
                    read_errors = 0
                    ended_reads += 1
                    if ended_reads >= confirm:
                        log(log_path, f"exit: agent not found after {resumes} resumes")
                        return 0
                else:
                    ended_reads = 0
                    read_errors += 1
                    log(log_path, f"read failed ({read_errors}/{max_read_errors}), agent_exists={exists}")
                    if exists is None and read_errors >= max_read_errors:
                        log(log_path, f"exit: herdr unreachable for {read_errors} reads after {resumes} resumes")
                        return 1
            else:
                read_errors = 0
                state = classify(screen)
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
                        log(log_path, f"exit: goal no longer active after {resumes} resumes")
                        return 0
            time.sleep(interval)
    finally:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        finally:
            lock_handle.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target", nargs="?", help="Herdr pane id or agent name hosting the goal")
    parser.add_argument("--interval", type=float, default=60.0)
    parser.add_argument("--max-resumes", type=int, default=10)
    parser.add_argument("--confirm", type=int, default=2, help="consecutive non-running reads before exiting")
    parser.add_argument("--max-read-errors", type=int, default=10, help="consecutive herdr-unreachable reads before exiting")
    parser.add_argument("--log", type=Path)
    parser.add_argument("--lock", type=Path)
    parser.add_argument("--classify", action="store_true", help="classify a screen read from stdin and exit")
    args = parser.parse_args(argv)
    if args.classify:
        print(classify(sys.stdin.read()))
        return 0
    if not args.target:
        parser.error("target is required")
    safe_target = args.target.replace(":", "-")
    log_path = args.log or Path("logs/goals") / f"watch-{safe_target}.log"
    lock_path = args.lock or Path("logs/goals") / f"watch-{safe_target}.lock"
    return watch(
        args.target,
        args.interval,
        args.max_resumes,
        args.confirm,
        log_path,
        lock_path=lock_path,
        max_read_errors=args.max_read_errors,
    )


if __name__ == "__main__":
    sys.exit(main())
