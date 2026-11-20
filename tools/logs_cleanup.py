"""Bounded log and screenshot retention helper for Mac and f1.

Default mode is dry-run; pass ``--apply`` to actually delete or truncate files.
Text ledgers (``logs/goals/*.md``) and fifth-layer notes (``logs/improve/notes.md``)
are never deleted by this tool.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

TERMINAL_STATUSES = frozenset({"completed", "stopped", "failed", "cancelled"})
DEFAULT_KEEP_PULLS = 50  # ~3 adventures of Mac logs/f1-pulls/<run_id>
DEFAULT_KEEP_F1_RUNS = 100  # ~6 adventures of terminal f1 logs/runs/<run_id>
DEFAULT_MAX_LOG_MB = 5.0
DEFAULT_TRUNCATE_KEEP_MB = 1.0
DEFAULT_LEGACY_DAYS = 7


@dataclass
class CleanupPlan:
    applied: bool = False
    pulls_kept: int = 0
    pulls_pruned: list[str] = field(default_factory=list)
    legacy_pruned: list[str] = field(default_factory=list)
    logs_truncated: list[str] = field(default_factory=list)
    reclaimed_bytes: int = 0
    f1: dict[str, Any] | None = None


def _path_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file() or path.is_symlink():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
    return total


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _truncate_tail(path: Path, keep_bytes: int) -> int:
    size = path.stat().st_size
    if size <= keep_bytes:
        return 0
    with path.open("rb") as fh:
        fh.seek(max(0, size - keep_bytes))
        tail = fh.read()
    # Align to next newline when possible so truncated log remains readable.
    nl = tail.find(b"\n")
    if nl != -1 and nl + 1 < len(tail):
        tail = tail[nl + 1 :]
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(tail)
    os.replace(tmp, path)
    return size - len(tail)


def run_local_cleanup(
    repo_root: Path,
    *,
    keep_pulls: int = DEFAULT_KEEP_PULLS,
    max_log_mb: float = DEFAULT_MAX_LOG_MB,
    truncate_keep_mb: float = DEFAULT_TRUNCATE_KEEP_MB,
    include_legacy: bool = False,
    legacy_days: int = DEFAULT_LEGACY_DAYS,
    apply: bool = False,
    now: float | None = None,
) -> CleanupPlan:
    plan = CleanupPlan(applied=apply)
    logs_dir = repo_root / "logs"
    if not logs_dir.exists():
        return plan

    # 1. Prune logs/f1-pulls/<run_id> directories, keeping newest `keep_pulls`.
    pulls_dir = logs_dir / "f1-pulls"
    if pulls_dir.is_dir():
        run_dirs = [p for p in pulls_dir.iterdir() if p.is_dir()]
        run_dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        keep_n = max(0, keep_pulls)
        plan.pulls_kept = min(len(run_dirs), keep_n)
        for old_dir in run_dirs[keep_n:]:
            size = _path_size(old_dir)
            plan.pulls_pruned.append(str(old_dir.relative_to(repo_root)))
            plan.reclaimed_bytes += size
            if apply:
                _remove_path(old_dir)

    # 2. Truncate oversized watcher / notifier text logs (> max_log_mb).
    max_bytes = int(max_log_mb * 1024 * 1024)
    keep_bytes = int(truncate_keep_mb * 1024 * 1024)
    log_globs = [
        logs_dir / "goals" / "watch-*.log",
        logs_dir / "improve" / "notify-*.log",
    ]
    for pattern in log_globs:
        parent = pattern.parent
        if not parent.is_dir():
            continue
        for log_file in sorted(parent.glob(pattern.name)):
            if not log_file.is_file():
                continue
            size = log_file.stat().st_size
            if size > max_bytes:
                plan.logs_truncated.append(str(log_file.relative_to(repo_root)))
                if apply:
                    plan.reclaimed_bytes += _truncate_tail(log_file, keep_bytes)
                else:
                    plan.reclaimed_bytes += max(0, size - keep_bytes)

    # 3. Optional opt-in cleanup of historical loose screenshots / material / sync dumps.
    if include_legacy:
        cutoff = (now if now is not None else time.time()) - legacy_days * 86400
        for entry in sorted(logs_dir.iterdir()):
            name = entry.name
            is_legacy_file = entry.is_file() and entry.suffix.lower() in {".png", ".jpg", ".jpeg"}
            is_legacy_dir = entry.is_dir() and (
                name.startswith("f1-material-") or name.startswith("lorwright-sync-")
            )
            if not (is_legacy_file or is_legacy_dir):
                continue
            try:
                mtime = entry.stat().st_mtime
            except OSError:
                continue
            if mtime >= cutoff:
                continue
            size = _path_size(entry)
            plan.legacy_pruned.append(str(entry.relative_to(repo_root)))
            plan.reclaimed_bytes += size
            if apply:
                _remove_path(entry)

    return plan


def select_f1_runs_to_prune(
    runs: list[dict[str, Any]],
    *,
    keep_runs: int = DEFAULT_KEEP_F1_RUNS,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Partition f1 runs into (to_prune, kept_terminal, skipped_non_terminal)."""
    terminal: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for item in runs:
        if item.get("status") in TERMINAL_STATUSES:
            terminal.append(item)
        else:
            skipped.append(item)
    terminal.sort(key=lambda r: float(r.get("mtime", 0.0)), reverse=True)
    keep_n = max(0, keep_runs)
    return terminal[keep_n:], terminal[:keep_n], skipped


def run_f1_cleanup(
    *,
    host: str = "f1",
    keep_runs: int = DEFAULT_KEEP_F1_RUNS,
    apply: bool = False,
) -> dict[str, Any]:
    """Inspect (and with --apply, prune) terminal run dirs in f1 C:\\Code\\lorwright\\logs\\runs."""
    ps_script = f"""& {{
    $runsRoot = 'C:\\Code\\lorwright\\logs\\runs'
    $keep = {int(keep_runs)}
    $apply = ${str(apply).lower()}
    if (-not (Test-Path $runsRoot)) {{
        @{{ ok = $true; runs_total = 0; kept = 0; skipped_non_terminal = 0; pruned = @(); reclaimed_bytes = 0; applied = $apply }} | ConvertTo-Json -Compress
        exit 0
    }}
    $terminal = @()
    $skipped = @()
    foreach ($dir in (Get-ChildItem -Path $runsRoot -Directory -ErrorAction SilentlyContinue)) {{
        $stFile = Join-Path $dir.FullName 'status.json'
        $status = 'unknown'
        if (Test-Path $stFile) {{
            try {{
                $obj = Get-Content -Path $stFile -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($obj.status) {{ $status = [string]$obj.status }}
            }} catch {{ $status = 'corrupt' }}
        }}
        $bytes = ((Get-ChildItem -Path $dir.FullName -Recurse -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum)
        if ($null -eq $bytes) {{ $bytes = 0 }}
        $entry = [PSCustomObject]@{{ name = $dir.Name; path = $dir.FullName; status = $status; mtime = $dir.LastWriteTimeUtc.Ticks; bytes = [int64]$bytes }}
        if ($status -in @('completed', 'stopped', 'failed', 'cancelled')) {{
            $terminal += $entry
        }} else {{
            $skipped += $entry
        }}
    }}
    $sorted = @($terminal | Sort-Object -Property mtime -Descending)
    $toPrune = if ($sorted.Count -gt $keep) {{ @($sorted[$keep..($sorted.Count - 1)]) }} else {{ @() }}
    $prunedNames = @()
    [int64]$reclaimed = 0
    foreach ($item in $toPrune) {{
        $prunedNames += $item.name
        $reclaimed += $item.bytes
        if ($apply) {{
            Remove-Item -Path $item.path -Recurse -Force -ErrorAction SilentlyContinue
        }}
    }}
    @{{
        ok = $true
        applied = $apply
        runs_total = ($terminal.Count + $skipped.Count)
        kept = [Math]::Min($sorted.Count, $keep)
        skipped_non_terminal = $skipped.Count
        pruned_count = $prunedNames.Count
        pruned = $prunedNames
        reclaimed_bytes = $reclaimed
    }} | ConvertTo-Json -Compress
}}

"""
    proc = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host, "powershell.exe -NoProfile -Command -"],
        input=ps_script,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0:
        return {"ok": False, "returncode": proc.returncode, "stderr": proc.stderr.strip()}
    out = proc.stdout.strip().splitlines()
    for line in reversed(out):
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    return {"ok": False, "stdout": proc.stdout.strip(), "stderr": proc.stderr.strip()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bounded retention cleanup for lorwright logs and screenshots.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent, help="Repo root path")
    parser.add_argument("--keep-pulls", type=int, default=DEFAULT_KEEP_PULLS, help="Max Mac logs/f1-pulls run dirs to keep")
    parser.add_argument("--max-log-mb", type=float, default=DEFAULT_MAX_LOG_MB, help="Truncate watch/notify logs larger than this (MB)")
    parser.add_argument("--include-legacy", action="store_true", help="Also prune old loose screenshots and f1-material/sync dirs in logs/")
    parser.add_argument("--legacy-days", type=int, default=DEFAULT_LEGACY_DAYS, help="Age threshold in days for --include-legacy")
    parser.add_argument("--f1", action="store_true", help="Also inspect/prune terminal runs in f1 C:\\Code\\lorwright\\logs\\runs")
    parser.add_argument("--host", default="f1", help="SSH host alias for --f1")
    parser.add_argument("--keep-f1-runs", type=int, default=DEFAULT_KEEP_F1_RUNS, help="Max terminal f1 run dirs to keep")
    parser.add_argument("--apply", action="store_true", help="Actually delete/truncate (default is dry-run)")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    args = parser.parse_args(argv)

    plan = run_local_cleanup(
        args.root,
        keep_pulls=args.keep_pulls,
        max_log_mb=args.max_log_mb,
        include_legacy=args.include_legacy,
        legacy_days=args.legacy_days,
        apply=args.apply,
    )
    if args.f1:
        plan.f1 = run_f1_cleanup(host=args.host, keep_runs=args.keep_f1_runs, apply=args.apply)

    if args.json:
        print(json.dumps(asdict(plan), ensure_ascii=False, indent=2))
    else:
        mode = "APPLIED" if plan.applied else "DRY-RUN"
        mb = plan.reclaimed_bytes / (1024 * 1024)
        print(
            f"[{mode}] local pulls_kept={plan.pulls_kept} pulls_pruned={len(plan.pulls_pruned)} "
            f"legacy_pruned={len(plan.legacy_pruned)} logs_truncated={len(plan.logs_truncated)} "
            f"reclaimed={mb:.1f} MB"
        )
        if plan.f1 is not None:
            f1_mb = plan.f1.get("reclaimed_bytes", 0) / (1024 * 1024)
            print(
                f"[{mode}] f1 ok={plan.f1.get('ok')} kept={plan.f1.get('kept')} "
                f"skipped_non_terminal={plan.f1.get('skipped_non_terminal')} "
                f"pruned={plan.f1.get('pruned_count')} reclaimed={f1_mb:.1f} MB"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
