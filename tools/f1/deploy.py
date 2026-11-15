"""Deploy runtime files to a new, isolated Windows F1 directory over system SSH.

Examples:
    python tools/f1/deploy.py --host f1 --name build-20261115
    python tools/f1/deploy.py --host f1 --name build-20261115 --apply

Requires Windows OpenSSH, PowerShell and an existing C:\\Code directory on the
host. The first command is a local-only dry run. Applying creates a new directory
under C:\\Code\\lorwright-deployments; it refuses to reuse an existing name,
does not alter either existing checkout, and retains the archive and manifest.
The receiver verifies every extracted file's SHA-256 before marking the release
ready. On failure the incomplete directory is retained for diagnosis; select a
new name for a retry. The caller must provide a Python environment with project
dependencies and run from the deployed directory with its src on PYTHONPATH.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REMOTE_ROOT = r"C:\Code\lorwright-deployments"


def runtime_files() -> list[Path]:
    """Collect only runtime source/assets and the non-secret project settings."""
    files: list[Path] = []
    for directory in (ROOT / "src" / "lorwright", ROOT / "assets", ROOT / "tools"):
        for path in directory.rglob("*"):
            if path.is_symlink():
                raise ValueError(f"拒绝同步符号链接：{path.relative_to(ROOT)}")
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            if path.name.startswith("._") or path.suffix.lower() not in {
                ".py", ".ps1", ".json", ".png", ".jpg", ".jpeg", ".webp",
            }:
                continue
            files.append(path)
    files.extend((ROOT / "config" / "settings.yaml", ROOT / "pyproject.toml"))
    files.sort(key=lambda item: item.relative_to(ROOT).as_posix())
    names = [p.relative_to(ROOT).as_posix().casefold() for p in files]
    if len(names) != len(set(names)):
        raise ValueError("文件路径在 Windows 上大小写冲突")
    return files


def powershell(host: str, script: str) -> None:
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host,
         "powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        check=True, timeout=55,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="系统 SSH 的目标主机，例如 f1")
    parser.add_argument("--name", required=True, help="新部署目录名称；不能覆盖已有目录")
    parser.add_argument("--apply", action="store_true", help="实际上传并校验；默认只预览")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", args.name):
        parser.error("name 只允许字母、数字、下划线和连字符")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", args.host):
        parser.error("host 必须是系统 SSH 中的主机别名")
    files = runtime_files()
    destination = REMOTE_ROOT + "\\" + args.name
    print(json.dumps({"host": args.host, "destination": destination, "files": len(files),
                      "bytes": sum(p.stat().st_size for p in files), "apply": args.apply},
                     ensure_ascii=True), flush=True)
    if not args.apply:
        return 0

    with tempfile.TemporaryDirectory(prefix="lorwright-deploy-") as temporary:
        archive = Path(temporary) / "bundle.zip"
        manifest = []
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for path in files:
                name = path.relative_to(ROOT).as_posix()
                data = path.read_bytes()
                manifest.append({"path": name, "size": len(data),
                                 "sha256": hashlib.sha256(data).hexdigest()})
                bundle.writestr(name, data)
            bundle.writestr("deploy-manifest.json", json.dumps(manifest, indent=2))
        # All interpolated path characters were constrained above.
        powershell(args.host, rf"""
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$parent='{REMOTE_ROOT}'
$target='{destination}'
if (!(Test-Path -LiteralPath 'C:\Code' -PathType Container)) {{ throw 'C:\Code is missing' }}
if (!(Test-Path -LiteralPath $parent)) {{ New-Item -ItemType Directory -Path $parent | Out-Null }}
if (Test-Path -LiteralPath $target) {{ throw 'Deployment name already exists' }}
New-Item -ItemType Directory -Path $target | Out-Null
""")
        remote_archive = f"{args.host}:C:/Code/lorwright-deployments/{args.name}/bundle.zip"
        subprocess.run(["scp", "-q", str(archive), remote_archive], check=True, timeout=55)
        powershell(args.host, rf"""
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$target='{destination}'
Expand-Archive -LiteralPath (Join-Path $target 'bundle.zip') -DestinationPath $target
$manifest=Get-Content -LiteralPath (Join-Path $target 'deploy-manifest.json') -Raw | ConvertFrom-Json
foreach ($entry in $manifest) {{
    $file=Join-Path $target $entry.path
    if (!(Test-Path -LiteralPath $file -PathType Leaf)) {{ throw "Missing $($entry.path)" }}
    $actual=(Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $entry.sha256) {{ throw "Hash mismatch $($entry.path)" }}
}}
@{{ status='ready'; files=@($manifest).Count; verified='sha256' }} |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $target 'deploy-receipt.json') -Encoding UTF8
Write-Output "VERIFIED $($manifest.Count) files: $target"
""")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"部署失败：{error}", file=sys.stderr)
        raise SystemExit(1) from error
