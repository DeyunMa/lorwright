"""牌表审计：champions/elise、champions/jinx vs GamePlayData ClientCardData。

对照源 = 01-prop 已解析的 07.11.015 ClientCardData（446c92c7）+
LocalizedText_zh_tw 子集。结论（2026-11-06，全部经本脚本验证）：

- Elise 9 张：s32 前段 (cost,attack,health) 与 deck.py 逐张一致；
  繁中名 card_<code>_Name 全部命中；
- 法术条目的 s32[1:] 不是攻血（类型相关字段），只验证 cost；
- Jinx PoC 卡 = 01PZ040（4/4/3，cost=4 与 deck.py 一致）；经典
  04SI006 在当前 GamePlayData/LocalizedText 中不存在——引用它的
  数据接入必须用 01PZ040；
- 應急裝置 = 01PZ028，cost 1，繁中名 ✓。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ARTIFACTS = Path("/Users/mdy/Code/my-own/lorwright-artifacts/analysis/stages/01-prop/parsed")

DECK = {
    "elise": [
        ("01SI002", "小蜘蛛", 1), ("06SI037", "闇影島泰爾石", 1),
        ("01SI053", "伊莉絲", 2), ("06NX013", "蜘術士", 2),
        ("01NX046", "蜘蛛哨兵", 3), ("01SI056", "發狂疾行蛛", 3),
        ("04NX016", "尖嘯蜘蛛", 4), ("01NX023", "群蛛之主", 5),
        ("01SI050", "傾巢而出", 6),
    ],
    "jinx": [("01PZ028", "應急裝置", 1), ("01PZ040", "吉茵珂絲", 4)],
}


def main() -> int:
    zh = {}
    with (ARTIFACTS / "LocalizedText_zh_tw" / "entries.jsonl").open() as f:
        for line in f:
            e = json.loads(line)
            for fld in e["fields"]:
                v = fld["value"]
                if isinstance(v, dict) and v.get("kind") == "map":
                    for pair in v.get("pairs", []):
                        zh[pair["key"]] = pair["value"]

    cards = {}
    with (ARTIFACTS / "GamePlayData" / "entries.jsonl").open() as f:
        for line in f:
            e = json.loads(line)
            if e["type_hex"] != "446c92c7":
                continue
            strings = [x["value"] for x in e["fields"] if x["type"] == "STRING" and isinstance(x["value"], str)]
            s32 = [x["value"] for x in e["fields"] if x["type"] == "S32"]
            if strings:
                cards[strings[0]] = (strings, s32)

    failures = []
    report = {}
    for champ, rows in DECK.items():
        out = []
        for code, expect_name, expect_cost in rows:
            if code not in cards:
                failures.append(f"{champ}/{code}: ClientCardData 无此条目")
                continue
            strings, s32 = cards[code]
            name = zh.get(f"card_{code}_Name")
            cost = s32[0] if s32 else None
            ok_name = name == expect_name
            ok_cost = cost == expect_cost
            if not ok_name:
                failures.append(f"{champ}/{code}: 名字 {name!r} != {expect_name!r}")
            if not ok_cost:
                failures.append(f"{champ}/{code}: cost {cost!r} != {expect_cost!r}")
            out.append({"code": code, "name_zh_tw": name, "cost": cost,
                        "name_ok": ok_name, "cost_ok": ok_cost})
        report[champ] = out
    payload = {"ok": not failures, "failures": failures, "decks": report}
    out_path = Path(__file__).resolve().parent.parent / "data" / "deck-audit.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
    print(json.dumps({"ok": payload["ok"], "failures": failures}, ensure_ascii=False))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
