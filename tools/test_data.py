"""从阶段基线恢复库外测试图片，原样保留字节和相对路径。"""

from __future__ import annotations

import argparse
import io
import os
import subprocess
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "491dc94f16cce6ce8941abb644c96be550ff9de3"
DESTINATIONS = {
    "tests/fixtures": "fixtures",
    "research/archives": "archives",
    "research/lor-client-07.10.013-v1/images": "research/lor-client-07.10.013-v1/images",
}
RETIRED_FIXTURES = {"screens/1080p_my_units.png"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}


def data_root() -> Path:
    configured = os.environ.get("LORWRIGHT_TEST_DATA")
    return Path(configured).expanduser().resolve() if configured else ROOT.parent / "lorwright-test-data"


def fixtures_root() -> Path:
    path = data_root() / "fixtures"
    if not path.is_dir():
        raise FileNotFoundError(f"缺少测试图片目录 {path}。请运行 python tools/test_data.py")
    return path


def restore_baseline(root: Path, *, include_history: bool = False) -> tuple[int, int]:
    root = root.resolve()

    def git(*args: str) -> bytes:
        return subprocess.check_output(["git", "-C", str(ROOT), *args])

    output = git("ls-tree", "-rz", "--name-only", BASELINE, "--", *DESTINATIONS)
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

    archive = git("archive", "--format=zip", BASELINE, "--", *images)
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-history", action="store_true", help="同时恢复退役截图和研究原图")
    args = parser.parse_args()
    root = data_root()
    try:
        total, added = restore_baseline(root, include_history=args.include_history)
    except subprocess.CalledProcessError as exc:
        parser.exit(1, f"无法读取 {BASELINE}。浅克隆请先获取该提交。\n{exc}\n")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    print(f"{root}：基线 {total} 张，写入 {added} 张，已一致 {total - added} 张")


if __name__ == "__main__":
    main()
