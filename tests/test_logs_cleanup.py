from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import logs_cleanup as lc


def _touch_dir(path: Path, mtime: float, payload_bytes: int = 1024) -> None:
    path.mkdir(parents=True, exist_ok=True)
    snap = path / "shot.png"
    snap.write_bytes(b"x" * payload_bytes)
    os.utime(snap, (mtime, mtime))
    os.utime(path, (mtime, mtime))


def test_local_cleanup_dry_run_and_apply_keeps_newest_pulls_and_text_ledgers(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    pulls = logs / "f1-pulls"
    goals = logs / "goals"
    improve = logs / "improve"
    goals.mkdir(parents=True)
    improve.mkdir(parents=True)

    ledger = goals / "2026-11-20-jinx.md"
    ledger.write_text("# ledger\n", encoding="utf-8")
    notes = improve / "notes.md"
    notes.write_text("# notes\n", encoding="utf-8")
    live = pulls / "live.png"
    pulls.mkdir(parents=True)
    live.write_bytes(b"live")

    base = 1_700_000_000.0
    for idx in range(5):
        _touch_dir(pulls / f"run-{idx}", base + idx * 10, payload_bytes=2048)

    dry = lc.run_local_cleanup(tmp_path, keep_pulls=2, apply=False)
    assert not dry.applied
    assert dry.pulls_kept == 2
    assert len(dry.pulls_pruned) == 3
    assert dry.reclaimed_bytes == 3 * 2048
    assert (pulls / "run-0").exists()

    applied = lc.run_local_cleanup(tmp_path, keep_pulls=2, apply=True)
    assert applied.applied
    assert sorted(p.name for p in pulls.iterdir() if p.is_dir()) == ["run-3", "run-4"]
    assert live.exists()
    assert ledger.exists()
    assert notes.exists()


def test_local_cleanup_truncates_oversized_watcher_logs(tmp_path: Path) -> None:
    goals = tmp_path / "logs" / "goals"
    goals.mkdir(parents=True)
    watch_log = goals / "watch-w5-pJ.log"
    watch_log.write_bytes((b"line-of-text\n") * 2000)  # ~26 KB

    plan = lc.run_local_cleanup(
        tmp_path,
        max_log_mb=0.01,
        truncate_keep_mb=0.004,
        apply=True,
    )
    assert plan.logs_truncated == ["logs/goals/watch-w5-pJ.log"]
    assert watch_log.stat().st_size <= int(0.004 * 1024 * 1024)
    assert watch_log.read_text(encoding="utf-8").endswith("line-of-text\n")


def test_local_cleanup_legacy_opt_in_only_removes_old_loose_artifacts(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir(parents=True)
    now = 1_700_100_000.0
    old_ts = now - 10 * 86400
    fresh_ts = now - 1 * 86400

    old_png = logs / "f1-old-1108.png"
    old_png.write_bytes(b"a" * 512)
    os.utime(old_png, (old_ts, old_ts))

    fresh_png = logs / "f1-fresh.png"
    fresh_png.write_bytes(b"b" * 512)
    os.utime(fresh_png, (fresh_ts, fresh_ts))

    old_mat = logs / "f1-material-20261106"
    _touch_dir(old_mat, old_ts, payload_bytes=1024)

    # Without --include-legacy, nothing removed.
    p1 = lc.run_local_cleanup(tmp_path, include_legacy=False, apply=True, now=now)
    assert p1.legacy_pruned == []
    assert old_png.exists() and old_mat.exists()

    # With --include-legacy, only old artifacts are removed.
    p2 = lc.run_local_cleanup(tmp_path, include_legacy=True, legacy_days=7, apply=True, now=now)
    assert sorted(p2.legacy_pruned) == ["logs/f1-material-20261106", "logs/f1-old-1108.png"]
    assert not old_png.exists()
    assert not old_mat.exists()
    assert fresh_png.exists()


def test_select_f1_runs_to_prune_skips_non_terminal() -> None:
    runs = [
        {"name": "r1", "status": "completed", "mtime": 100},
        {"name": "r2", "status": "stopped", "mtime": 200},
        {"name": "r3", "status": "failed", "mtime": 300},
        {"name": "r4", "status": "running", "mtime": 50},
        {"name": "r5", "status": "unknown", "mtime": 10},
    ]
    to_prune, kept, skipped = lc.select_f1_runs_to_prune(runs, keep_runs=2)
    assert [r["name"] for r in kept] == ["r3", "r2"]
    assert [r["name"] for r in to_prune] == ["r1"]
    assert sorted(r["name"] for r in skipped) == ["r4", "r5"]


def test_cancelled_f1_runs_count_as_terminal() -> None:
    runs = [{"run_id": "a", "status": "cancelled", "mtime": 2.0}, {"run_id": "b", "status": "running", "mtime": 1.0}]
    prune, kept, skipped = lc.select_f1_runs_to_prune(runs, keep_runs=0)
    assert [r["run_id"] for r in prune] == ["a"]
    assert [r["run_id"] for r in skipped] == ["b"]
