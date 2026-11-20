"""从阶段基线恢复或校验库外测试图片，原样保留字节和相对路径。"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "491dc94f16cce6ce8941abb644c96be550ff9de3"
DESTINATIONS = {
    "tests/fixtures": "fixtures",
    "research/archives": "archives",
    "research/lor-client-07.10.013-v1/images": "research/lor-client-07.10.013-v1/images",
}
RETIRED_FIXTURES = {"screens/1080p_my_units.png"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
_IMAGE_REF_RE = re.compile(r"[A-Za-z0-9_./-]+\.(?:png|jpg|jpeg)\b", re.IGNORECASE)


def data_root() -> Path:
    configured = os.environ.get("LORWRIGHT_TEST_DATA")
    return Path(configured).expanduser().resolve() if configured else ROOT.parent / "lorwright-test-data"


def fixtures_root() -> Path:
    path = data_root() / "fixtures"
    if not path.is_dir():
        raise FileNotFoundError(f"缺少测试图片目录 {path}。请运行 python tools/test_data.py")
    return path


def _git(*args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def baseline_fixtures() -> set[str]:
    """返回阶段基线中应存在于 fixtures/ 下的相对路径集合（不含已退役图片）。"""
    output = _git("ls-tree", "-rz", "--name-only", BASELINE, "--", "tests/fixtures")
    result: set[str] = set()
    for source in filter(None, output.decode("utf-8").split("\0")):
        if PurePosixPath(source).suffix.lower() not in IMAGE_SUFFIXES:
            continue
        relative = source.removeprefix("tests/fixtures/")
        if relative not in RETIRED_FIXTURES:
            result.add(relative)
    return result


def documented_fixtures(meta_root: Path | None = None) -> set[str]:
    """扫描 tests/fixtures/**/README.md 中登记的图片相对路径。"""
    base = meta_root or (ROOT / "tests" / "fixtures")
    refs: set[str] = set()
    if not base.is_dir():
        return refs
    for readme in base.rglob("README.md"):
        rel_dir = readme.parent.relative_to(base).as_posix()
        text = readme.read_text(encoding="utf-8", errors="ignore")
        for match in _IMAGE_REF_RE.findall(text):
            cleaned = match.lstrip("./")
            if "/" in cleaned:
                refs.add(cleaned)
            elif rel_dir != ".":
                refs.add(f"{rel_dir}/{cleaned}")
            else:
                refs.add(cleaned)
    return refs


def check_fixtures(
    root: Path,
    *,
    baseline: set[str] | None = None,
    meta_root: Path | None = None,
) -> dict[str, Any]:
    """只读核对本地 fixtures 目录与阶段基线、README 登记的一致性。"""
    fixtures_dir = root.resolve() / "fixtures"
    expected = baseline_fixtures() if baseline is None else set(baseline)
    local: set[str] = set()
    if fixtures_dir.is_dir():
        for path in fixtures_dir.rglob("*"):
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
                local.add(path.relative_to(fixtures_dir).as_posix())
    missing_from_baseline = sorted(expected - local)
    local_only = sorted(local - expected)
    docs = documented_fixtures(meta_root)
    undocumented_local_only = sorted(item for item in local_only if item not in docs)
    return {
        "ok": not missing_from_baseline and not undocumented_local_only,
        "fixtures_dir": str(fixtures_dir),
        "baseline_count": len(expected),
        "local_count": len(local),
        "missing_from_baseline": missing_from_baseline,
        "local_only": local_only,
        "undocumented_local_only": undocumented_local_only,
    }


def restore_baseline(root: Path, *, include_history: bool = False) -> tuple[int, int]:
    root = root.resolve()
    output = _git("ls-tree", "-rz", "--name-only", BASELINE, "--", *DESTINATIONS)
    images = {}
    for source in filter(None, output.decode("utf-8").split("\0")):
        if PurePosixPath(source).suffix.lower() not in IMAGE_SUFFIXES:
            continue
        prefix = next(path for path in DESTINATIONS if source.startswith(path + "/"))
        relative = source.removeprefix(prefix + "/")
        destination = DESTINATIONS[prefix]
        if destination == "fixtures" and relative in RETIRED_FIXTURES:
            destination = "archives/retired-fixtures"
        if destination == "fixtures" or include_history:
            images[source] = root / destination / relative
    if not images:
        raise ValueError("阶段基线没有测试图片")

    archive = _git("archive", "--format=zip", BASELINE, "--", *images)
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        pending = []
        for source, target in images.items():
            if not target.resolve().is_relative_to(root) or target.is_symlink():
                raise ValueError(f"图片路径越界或为符号链接：{target}")
            if not target.exists():
                pending.append((source, target))
            elif target.read_bytes() != bundle.read(source):
                raise ValueError(f"同名图片内容不同，保留现有文件：{target}")
        for source, target in pending:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as out:
                out.write(bundle.read(source))
    return len(images), len(pending)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-history", action="store_true", help="同时恢复退役截图和研究原图")
    parser.add_argument("--check", action="store_true", help="只读核对本地 fixtures 与基线和 README 的差异")
    parser.add_argument("--json", action="store_true", help="配合 --check 以 JSON 输出核对结果")
    args = parser.parse_args(argv)
    root = data_root()
    if args.check:
        try:
            report = check_fixtures(root)
        except subprocess.CalledProcessError as exc:
            parser.exit(1, f"无法读取 {BASELINE}。浅克隆请先获取该提交。\n{exc}\n")
        if args.json:
            print(json.dumps(report, ensure_ascii=False))
        else:
            print(
                f"{report['fixtures_dir']}：基线 {report['baseline_count']} 张，"
                f"本地 {report['local_count']} 张，缺失基线 {len(report['missing_from_baseline'])} 张，"
                f"仅本地 {len(report['local_only'])} 张（未登记 {len(report['undocumented_local_only'])} 张）"
            )
            for label, items in (
                ("缺失基线", report["missing_from_baseline"]),
                ("仅本地（注意备份）", report["local_only"]),
                ("仅本地且未在 README 登记", report["undocumented_local_only"]),
            ):
                if items:
                    print(f"  {label}:")
                    for item in items:
                        print(f"    - {item}")
        if not report["ok"]:
            parser.exit(1)
        return

    try:
        total, added = restore_baseline(root, include_history=args.include_history)
    except subprocess.CalledProcessError as exc:
        parser.exit(1, f"无法读取 {BASELINE}。浅克隆请先获取该提交。\n{exc}\n")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    print(f"{root}：基线 {total} 张，写入 {added} 张，已一致 {total - added} 张")


if __name__ == "__main__":
    main()
