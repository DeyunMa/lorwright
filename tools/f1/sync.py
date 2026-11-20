"""Preflight-checked fast-forward sync of the f1 checkout over SSH.

Examples:
    python3 tools/f1/sync.py                 # preview only (fetch + preflight)
    python3 tools/f1/sync.py --apply         # fast-forward + reinstall deps if pyproject.toml changed

Preflight checks on f1 before mutating:
- Checkout exists and is on the expected branch (default: main).
- Working tree has no uncommitted or untracked files.
- No running lorwright process (non-terminal status.json files without a live
  process are reported as `stale_sessions` warnings instead of blocking sync).
  Only the default `<repo>\\logs\\runs` directory is inspected; custom
  `LORWRIGHT_RUNS_DIR` locations are not checked by this script.
- Current HEAD is an ancestor of origin/<branch> (strictly fast-forwardable).
- By default, verifies origin/<branch> matches local Mac HEAD (override with
  `--expect <sha>` or disable with `--any-target`).

Outputs a single JSON object to stdout. Exit codes:
  0  preview or sync succeeded
  1  blocked by preflight check, SSH failure, or sync/install failure
  2  invalid CLI arguments
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HOST = "f1"
DEFAULT_REPO = r"C:\Code\lorwright"
DEFAULT_BRANCH = "main"
DEFAULT_TIMEOUT = 600


def local_head(repo_dir: Path = ROOT) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_dir), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    sha = proc.stdout.strip()
    return sha if re.fullmatch(r"[0-9a-f]{40}", sha) else None


def build_remote_script(
    repo: str,
    branch: str,
    *,
    apply: bool,
    skip_deps: bool,
    expect_head: str | None = None,
) -> str:
    apply_lit = "$true" if apply else "$false"
    skip_deps_lit = "$true" if skip_deps else "$false"
    expect_lit = f"'{expect_head}'" if expect_head else "$null"
    # Use Continue so native commands (git fetch/merge, pip) writing progress or
    # warnings to stderr do not raise terminating NativeCommandError under PS 5.1.
    # Wrap in `& { ... }\n\n` so `powershell.exe -Command -` executes the whole
    # payload as one statement rather than pseudo-interactive line-by-line input.
    return rf"""& {{
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$repo = '{repo}'
$branch = '{branch}'
$apply = {apply_lit}
$skipDeps = {skip_deps_lit}
$expectHead = {expect_lit}

$result = [ordered]@{{
    ok = $false
    applied = $false
    repo = $repo
    branch = $branch
    current_branch = $null
    before_head = $null
    target_head = $null
    expect_head = $expectHead
    after_head = $null
    already_up_to_date = $false
    deps_changed = $false
    deps_installed = $false
    blocked_reason = $null
    dirty_files = @()
    stale_sessions = @()
    running_processes = @()
}}

function Finish([string]$reason = $null) {{
    if ($reason) {{ $result.blocked_reason = $reason }}
    $result | ConvertTo-Json -Depth 6 -Compress
    exit 0
}}

if (!(Test-Path -LiteralPath $repo -PathType Container)) {{
    Finish 'repo_missing'
}}

try {{
    Set-Location -LiteralPath $repo -ErrorAction Stop
}} catch {{
    Finish 'set_location_failed'
}}

$currentBranch = (& git rev-parse --abbrev-ref HEAD 2>$null | Out-String).Trim()
if ($LASTEXITCODE -ne 0) {{ Finish 'git_rev_parse_failed' }}
$result.current_branch = $currentBranch
if ($currentBranch -ne $branch) {{ Finish "wrong_branch:$currentBranch" }}

$beforeHead = (& git rev-parse HEAD 2>$null | Out-String).Trim()
if ($LASTEXITCODE -ne 0) {{ Finish 'git_head_failed' }}
$result.before_head = $beforeHead
$result.after_head = $beforeHead

$statusLines = @(& git status --porcelain 2>$null | Where-Object {{ $_ -and $_.Trim().Length -gt 0 }})
if ($LASTEXITCODE -ne 0) {{ Finish 'git_status_failed' }}
if ($statusLines.Count -gt 0) {{
    $result.dirty_files = $statusLines
    Finish 'dirty_worktree'
}}

$procs = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {{
    ($_.Name -ieq 'lorwright.exe') -or (
        $_.Name -match '^python(w)?\.exe$' -and $_.CommandLine -and $_.CommandLine -match 'lorwright'
    )
}} | ForEach-Object {{ @{{ pid = $_.ProcessId; name = $_.Name }} }})

$terminal = @('completed', 'stopped', 'failed', 'cancelled')
$nonTerminal = @()
$runsDir = Join-Path $repo 'logs\runs'
if (Test-Path -LiteralPath $runsDir -PathType Container) {{
    Get-ChildItem -LiteralPath $runsDir -Directory -ErrorAction SilentlyContinue | ForEach-Object {{
        $sf = Join-Path $_.FullName 'status.json'
        if (Test-Path -LiteralPath $sf -PathType Leaf) {{
            try {{
                $st = Get-Content -LiteralPath $sf -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json
                if ($st.status -and ($terminal -notcontains $st.status)) {{
                    $nonTerminal += @{{ run_id = $_.Name; status = $st.status }}
                }}
            }} catch {{
                $nonTerminal += @{{ run_id = $_.Name; status = 'unreadable' }}
            }}
        }}
    }}
}}

if ($procs.Count -gt 0) {{
    $result.running_processes = $procs
    $result.stale_sessions = $nonTerminal
    Finish 'lorwright_process_running'
}}
$result.stale_sessions = $nonTerminal

& git fetch origin $branch 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {{ Finish 'git_fetch_failed' }}

$targetHead = (& git rev-parse "origin/$branch" 2>$null | Out-String).Trim()
if ($LASTEXITCODE -ne 0) {{ Finish 'git_target_failed' }}
$result.target_head = $targetHead

if ($expectHead -and ($targetHead -ne $expectHead)) {{
    Finish 'target_mismatch'
}}

& git merge-base --is-ancestor $beforeHead $targetHead 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {{ Finish 'cannot_fast_forward' }}

if ($beforeHead -eq $targetHead) {{
    $result.already_up_to_date = $true
    $result.ok = $true
    Finish
}}

$depDiff = @(& git diff --name-only "$beforeHead..$targetHead" -- pyproject.toml 2>$null | Where-Object {{ $_ -and $_.Trim().Length -gt 0 }})
if ($LASTEXITCODE -ne 0) {{ Finish 'git_diff_failed' }}
$result.deps_changed = ($depDiff.Count -gt 0)

if (-not $apply) {{
    $result.ok = $true
    Finish
}}

& git merge --ff-only "origin/$branch" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {{ Finish 'git_merge_ff_failed' }}

$afterHead = (& git rev-parse HEAD 2>$null | Out-String).Trim()
$result.after_head = $afterHead
if ($afterHead -ne $targetHead) {{ Finish 'head_mismatch_after_merge' }}
$result.applied = $true

if ($result.deps_changed -and (-not $skipDeps)) {{
    $venvPy = Join-Path $repo '.venv\Scripts\python.exe'
    if (!(Test-Path -LiteralPath $venvPy -PathType Leaf)) {{ Finish 'venv_python_missing' }}
    & $venvPy -m pip install -e . --quiet 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {{ Finish 'pip_install_failed' }}
    $result.deps_installed = $true
}}

$result.ok = $true
Finish
}}

"""


def build_ssh_command(host: str) -> list[str]:
    return [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=10",
        "-o", "ServerAliveInterval=10",
        "-o", "ServerAliveCountMax=3",
        host,
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "-",
    ]


def run_remote_powershell(host: str, script: str, timeout: int = DEFAULT_TIMEOUT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        build_ssh_command(host),
        input=script,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def sync_f1(
    host: str,
    repo: str,
    branch: str,
    *,
    apply: bool = False,
    skip_deps: bool = False,
    expect_head: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    script = build_remote_script(
        repo,
        branch,
        apply=apply,
        skip_deps=skip_deps,
        expect_head=expect_head,
    )
    try:
        proc = run_remote_powershell(host, script, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "host": host,
            "repo": repo,
            "branch": branch,
            "blocked_reason": "ssh_timeout",
            "hint": "remote may have fast-forwarded or still be installing dependencies; re-run preview to verify HEAD",
        }
    except OSError as exc:
        return {"ok": False, "host": host, "repo": repo, "branch": branch, "blocked_reason": f"ssh_error:{exc}"}

    if proc.returncode != 0:
        return {
            "ok": False,
            "host": host,
            "repo": repo,
            "branch": branch,
            "blocked_reason": "ssh_failed",
            "returncode": proc.returncode,
            "stderr": proc.stderr.strip(),
        }

    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if not lines:
        return {"ok": False, "host": host, "repo": repo, "branch": branch, "blocked_reason": "empty_remote_output"}
    try:
        payload = json.loads(lines[-1])
    except ValueError:
        return {
            "ok": False,
            "host": host,
            "repo": repo,
            "branch": branch,
            "blocked_reason": "invalid_remote_json",
            "stdout": lines[-1][:400],
        }
    payload["host"] = host
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default=DEFAULT_HOST, help="SSH host alias (default: f1)")
    parser.add_argument("--repo", default=DEFAULT_REPO, help=r"Windows checkout path (default: C:\Code\lorwright)")
    parser.add_argument("--branch", default=DEFAULT_BRANCH, help="Branch to fast-forward (default: main)")
    parser.add_argument("--apply", action="store_true", help="Apply ff-only merge (and dep reinstall if needed); default is preview")
    parser.add_argument("--skip-deps", action="store_true", help="Skip pip reinstall even if pyproject.toml changed")
    parser.add_argument("--expect", help="Expected 40-char commit SHA on origin/<branch> (default: local HEAD)")
    parser.add_argument("--any-target", action="store_true", help="Do not require origin/<branch> to match local HEAD")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help=f"SSH command timeout in seconds (default: {DEFAULT_TIMEOUT})")
    args = parser.parse_args(argv)

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", args.host):
        parser.error("host must be a valid SSH host alias")
    if not re.fullmatch(r"[A-Za-z0-9._/-]{1,128}", args.branch):
        parser.error("branch contains unsupported characters")
    if not re.fullmatch(r"[A-Za-z]:\\[A-Za-z0-9_\\ .-]+", args.repo):
        parser.error("repo must be a safe Windows path")
    if args.expect and not re.fullmatch(r"[0-9a-f]{40}", args.expect):
        parser.error("expect must be a full 40-character lowercase git SHA")

    expect_head: str | None = None
    if not args.any_target:
        expect_head = args.expect or local_head()

    result = sync_f1(
        args.host,
        args.repo,
        args.branch,
        apply=args.apply,
        skip_deps=args.skip_deps,
        expect_head=expect_head,
        timeout=args.timeout,
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
