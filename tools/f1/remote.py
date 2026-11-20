"""Read-only f1 inspection from the Mac over SSH, for the /goal loop and humans.

Examples:
    python3 tools/f1/remote.py status RUN_ID          # one status JSON
    python3 tools/f1/remote.py wait RUN_ID --max 540  # bounded wait until terminal / stalled
    python3 tools/f1/remote.py pull RUN_ID            # copy snapshots + events, print condensed events
    python3 tools/f1/remote.py shot                   # live emulator screenshot to logs/f1-pulls/
    python3 tools/f1/remote.py focus                  # foreground window and activity stack
    python3 tools/f1/remote.py net                    # TCP reachability + netwatchdog summary

Nothing here sends input to the game or changes f1 state beyond writing the live
screenshot under `C:\\Code\\lorwright\\logs\\live\\`. Every SSH call uses BatchMode
and keep-alives so a half-open Tailscale relay cannot hang the caller. Remote
PowerShell is sent on stdin wrapped in `& { ... }` (see tools/f1/sync.py for why).
ADB is connected inside the same remote call because f1 reaps the adb daemon when
an SSH session ends (docs/environment.md §5). Screenshots are taken on the device
and pulled as files: Windows PowerShell 5.1 corrupts binary output redirected
with `>`.

Exit codes: 0 ok / terminal state reached, 1 SSH or remote failure,
3 session stalled or unresponsive, 4 wait budget used up.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HOST = "f1"
REPO = r"C:\Code\lorwright"
REPO_SCP = "C:/Code/lorwright"
LORWRIGHT = REPO + r"\.venv\Scripts\lorwright.exe"
ADB = r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe"
SERIAL = "127.0.0.1:5555"
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
            "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=3"]
TERMINAL = ("completed", "stopped", "failed", "cancelled")
UNHEALTHY = ("stalled", "unresponsive")
QUIET_PHASES = ("capture", "recognize", "adventure")
QUIET_KEYS = ("phase", "reason", "progress", "wait_deadline", "iteration", "iteration_limit",
              "message", "ui", "capture_ms", "snapshot")


def ps_script(body: str) -> str:
    return "& {\n$ErrorActionPreference = 'Continue'\n" + body.strip() + "\n}\n\n"


def run_ps(host: str, body: str, timeout: float = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["ssh", *SSH_OPTS, host, "powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "-"],
        input=ps_script(body), capture_output=True, text=True, timeout=timeout,
    )


def adb_prelude() -> str:
    return f"$adb = '{ADB}'\n& $adb connect {SERIAL} 2>&1 | Out-Null\n"


def status_body(run_id: str, wait_s: int = 0) -> str:
    wait = f" --wait {wait_s}" if wait_s else ""
    return f"Set-Location '{REPO}'\n& '{LORWRIGHT}' sessions status {run_id}{wait} --json"


def shot_body() -> str:
    return adb_prelude() + (
        f"New-Item -ItemType Directory -Force '{REPO}\\logs\\live' | Out-Null\n"
        f"& $adb -s {SERIAL} shell screencap -p /sdcard/lw-live.png\n"
        f"& $adb -s {SERIAL} pull /sdcard/lw-live.png '{REPO}\\logs\\live\\live.png' 2>&1 | Out-Null\n"
        "if ($LASTEXITCODE -ne 0) { 'pull_failed' }"
    )


def focus_body() -> str:
    return adb_prelude() + (
        f"& $adb -s {SERIAL} shell \"dumpsys window windows | grep -E 'mCurrentFocus|mFocusedApp'; "
        "dumpsys activity activities | grep -E 'Run #|realActivity' | head -20\""
    )


def net_body() -> str:
    return (
        "foreach ($h in 'auth.riotgames.com','www.google.com') {\n"
        "  $r = Test-NetConnection $h -Port 443 -WarningAction SilentlyContinue\n"
        "  '{0} tcp={1}' -f $h, $r.TcpTestSucceeded\n"
        "}\n"
        "$f = Get-ChildItem C:\\Windows\\Temp\\*net*watch*.log -ErrorAction SilentlyContinue | Select-Object -First 1\n"
        "if ($f) {\n"
        "  $f.FullName\n"
        "  Get-Content $f -Tail 40000 | Where-Object { $_ -like '*end result=*' } |\n"
        "    ForEach-Object { $_.Substring(1,13) + ' ' + ($_ -replace '.*end result=(\\w+).*','$1') } |\n"
        "    Group-Object | Select-Object -Last 12 | ForEach-Object { $_.Name + ' ' + $_.Count }\n"
        "  Get-Content $f -Tail 8\n"
        "}"
    )


def parse_status(text: str) -> dict | None:
    start = text.find("{")
    if start < 0:
        return None
    try:
        return json.loads(text[start:])
    except ValueError:
        return None


def summary(status: dict) -> str:
    details = status.get("details") or {}
    return " ".join(str(v) for v in (status.get("status"), status.get("health"), status.get("phase"),
                                     status.get("reason"), details.get("scene"), status.get("seq")))


def wait(host: str, run_id: str, max_s: float, *, clock=time.monotonic) -> int:
    deadline = clock() + max_s
    while clock() < deadline:
        try:
            proc = run_ps(host, status_body(run_id, wait_s=30), timeout=90)
            status = parse_status(proc.stdout)
        except subprocess.TimeoutExpired:
            status = None
        stamp = datetime.now().strftime("%H:%M:%S")
        if status is None:
            print(f"{stamp} ERR ssh/status unavailable", flush=True)
            continue
        print(f"{stamp} {summary(status)}", flush=True)
        if status.get("status") in TERMINAL:
            print(json.dumps(status, ensure_ascii=False), flush=True)
            return 0
        if status.get("health") in UNHEALTHY:
            print(json.dumps(status, ensure_ascii=False)[:3000], flush=True)
            return 3
    print(f"{datetime.now():%H:%M:%S} wait budget {max_s:.0f}s used up", flush=True)
    return 4


def condensed_events(lines) -> list[str]:
    out = []
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        payload = event.get("payload") or {}
        if event.get("type") == "health" or payload.get("phase") in QUIET_PHASES:
            continue
        extra = {k: v for k, v in payload.items() if k not in QUIET_KEYS}
        out.append(" ".join([str(event.get("seq")), str(event.get("ts_utc", ""))[11:19], str(event.get("type")),
                             str(payload.get("phase") or ""), str(payload.get("reason") or ""),
                             json.dumps(extra, ensure_ascii=False)[:200]]))
    return out


def scp_command(host: str, remote_paths: list[str], dest: Path) -> list[str]:
    return ["scp", "-q", "-r", *SSH_OPTS, *(f"{host}:{path}" for path in remote_paths), str(dest) + "/"]


def pull(host: str, run_id: str, root: Path) -> int:
    dest = root / run_id
    dest.mkdir(parents=True, exist_ok=True)
    base = f"{REPO_SCP}/logs/runs/{run_id}"
    proc = subprocess.run(scp_command(host, [f"{base}/snapshots", f"{base}/events.jsonl", f"{base}/status.json"], dest),
                          capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        print(proc.stderr.strip(), file=sys.stderr)
    snapshots = sorted(p.name for p in (dest / "snapshots").glob("*")) if (dest / "snapshots").is_dir() else []
    print(f"{dest}  snapshots={len(snapshots)}")
    for name in snapshots[-10:]:
        print(f"  {name}")
    events = dest / "events.jsonl"
    if events.is_file():
        print("\n".join(condensed_events(events.read_text(encoding="utf-8").splitlines())[-60:]))
    return 0 if proc.returncode == 0 else 1


def shot(host: str, root: Path) -> int:
    proc = run_ps(host, shot_body(), timeout=90)
    if proc.returncode != 0 or "pull_failed" in proc.stdout:
        print(proc.stdout + proc.stderr, file=sys.stderr)
        return 1
    root.mkdir(parents=True, exist_ok=True)
    dest = root / f"live-{datetime.now():%Y%m%d-%H%M%S}.png"
    copy = subprocess.run(["scp", "-q", *SSH_OPTS, f"{host}:{REPO_SCP}/logs/live/live.png", str(dest)],
                          capture_output=True, text=True, timeout=120)
    if copy.returncode != 0:
        print(copy.stderr.strip(), file=sys.stderr)
        return 1
    print(dest)
    return 0


def run_print(host: str, body: str, timeout: float = 120) -> int:
    proc = run_ps(host, body, timeout=timeout)
    sys.stdout.write(proc.stdout)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
    return 0 if proc.returncode == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default=HOST)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "wait", "pull"):
        cmd = sub.add_parser(name)
        cmd.add_argument("run_id")
        if name == "wait":
            cmd.add_argument("--max", type=float, default=540, help="wait budget in seconds")
        if name == "pull":
            cmd.add_argument("--dest", type=Path, default=Path("logs/f1-pulls"))
    sub.add_parser("shot").add_argument("--dest", type=Path, default=Path("logs/f1-pulls"))
    sub.add_parser("focus")
    sub.add_parser("net")
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            return run_print(args.host, status_body(args.run_id))
        if args.command == "wait":
            return wait(args.host, args.run_id, args.max)
        if args.command == "pull":
            return pull(args.host, args.run_id, args.dest)
        if args.command == "shot":
            return shot(args.host, args.dest)
        return run_print(args.host, focus_body() if args.command == "focus" else net_body())
    except subprocess.TimeoutExpired:
        print(f"{args.command}: ssh timed out", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
