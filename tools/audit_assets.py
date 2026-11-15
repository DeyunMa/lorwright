"""审计 Git 图片与静态引用；候选不等于未使用。仅使用标准库，不读取 .env。"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import defaultdict
from pathlib import Path

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
TEXT_SUFFIXES = {".py", ".json", ".md", ".txt", ".yaml", ".yml", ".toml", ".ps1"}


def audit(root: Path) -> dict:
    tracked = subprocess.check_output(
        ["git", "-C", str(root), "ls-files", "-z"],
    ).decode("utf-8").split("\0")
    paths = sorted({name for name in tracked if name and (root / name).is_file()})
    images = [name for name in paths if Path(name).suffix.lower() in IMAGE_SUFFIXES]
    # 只扫描已跟踪的文档/代码格式，明确排除环境文件；不打开图片和任意本地文件。
    sources = [
        name for name in paths
        if Path(name).suffix.lower() in TEXT_SUFFIXES
        and not any(part.startswith(".env") for part in Path(name).parts)
        and name != "tools/audit_assets.py"
    ]
    texts = [(name, (root / name).read_text(encoding="utf-8", errors="replace"))
             for name in sources]
    hashes: dict[str, list[str]] = defaultdict(list)
    directories: dict[str, dict] = {}
    candidates = []
    total_bytes = 0
    for name in images:
        data = (root / name).read_bytes()
        total_bytes += len(data)
        hashes[hashlib.sha256(data).hexdigest()].append(name)
        if name.startswith("tests/fixtures/"):
            directory = str(Path(name).parent)
            entry = directories.setdefault(directory, {"count": 0, "bytes": 0})
            entry["count"] += 1
            entry["bytes"] += len(data)
        # 文件名查找可覆盖常见的目录拼接；动态生成名称和 glob 无法据此判断。
        basename = Path(name).name
        if not any(basename in text for _, text in texts):
            candidates.append(name)
    return {
        "schema_version": 1,
        "scope": "git ls-files (working-tree contents; missing tracked paths excluded)",
        "tracked_images": {"count": len(images), "bytes": total_bytes},
        "test_fixture_directories": directories,
        "identical_content": [
            {"sha256": digest, "paths": names}
            for digest, names in sorted(hashes.items()) if len(names) > 1
        ],
        "static_unreferenced_candidates": candidates,
        "limitations": (
            "静态扫描只在已跟踪代码和文档中查找图片文件名；动态名称、glob、"
            "目录批量读取和外部消费者可能漏检。候选不是 unused 证明，不能据此自动删除。"
            "文档引用也不证明图片仍参与回归；同内容不同名称可能表达不同测试语义。"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="输出 JSON，供 Agent 消费")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    result = audit(root)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    images = result["tracked_images"]
    print(f"Git 图片：{images['count']} 张，{images['bytes']} bytes")
    print("测试素材目录：")
    for name, stats in result["test_fixture_directories"].items():
        print(f"  {name}: {stats['count']} 张，{stats['bytes']} bytes")
    print("完全相同内容：")
    for group in result["identical_content"]:
        print("  " + " = ".join(group["paths"]))
    print("静态未见引用候选：")
    for name in result["static_unreferenced_candidates"]:
        print(f"  {name}")
    print(result["limitations"])


if __name__ == "__main__":
    main()
