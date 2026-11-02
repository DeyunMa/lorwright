"""复盘脚本：把 events.jsonl 汇总成可读摘要（可粘给 LLM 分析）。

用法：
    python tools/analyze.py logs/2026-11-02
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


def load(path: Path) -> list[dict]:
    events: list[dict] = []
    for f in sorted(path.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python tools/analyze.py <logs/日期目录>")
        raise SystemExit(1)

    root = Path(sys.argv[1])
    if not root.exists():
        print(f"目录不存在: {root}")
        raise SystemExit(1)

    events = load(root)
    if not events:
        print("没有事件记录。")
        return

    total = len(events)
    layers = Counter(e.get("layer", "?") for e in events)
    actions = Counter(e.get("action", "?") for e in events)
    uis = Counter(e.get("ui", "?") for e in events)
    ms = [e.get("ms", 0) for e in events if isinstance(e.get("ms"), int)]
    stuck = sum(1 for e in events if e.get("stuck"))

    print(f"# 复盘摘要：{root}\n")
    print(f"- 总回合数：{total}")
    print(f"- 卡住次数：{stuck}")
    if ms:
        print(f"- 单回合耗时：平均 {sum(ms)//len(ms)}ms，最大 {max(ms)}ms")

    print("\n## 决策层分布")
    for k, v in layers.most_common():
        print(f"- {k}: {v} ({v/total:.1%})")

    print("\n## 动作分布")
    for k, v in actions.most_common():
        print(f"- {k}: {v} ({v/total:.1%})")

    print("\n## UI 状态分布")
    for k, v in uis.most_common():
        print(f"- {k}: {v} ({v/total:.1%})")


if __name__ == "__main__":
    main()
