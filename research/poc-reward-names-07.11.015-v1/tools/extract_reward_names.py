"""从 01-prop 已解析的 PROP 数据提取 PoC 奖励名称表（能力/圣物/道具）。

只依赖标准库。输入是 01-prop 解析产物（已通过该阶段的严格校验），
不做二进制重解析：

  - parsed/GamePlayData/entries.jsonl        （按 type_hex 过滤）
  - parsed/LocalizedText_<locale>/entries.jsonl （MAP(STRING,STRING)）

用法：
  python3 extract_reward_names.py --out data/reward-names.json
默认路径指向本机 artifacts；换机器时用 --gameplay / --locale-dir 覆盖。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

# type-catalog.json（02-domain）关联的 native 类型：
#   CardStickerData 75890ae2 = 道具节点奖励（I 码，ReforgedCampaigns/Items/…）
#   RelicData      d50c7f54 = 圣物（R 码，Loot/CardMetaProgression/Relics/…）
ITEM_TYPE_HEX = "75890ae2"
RELIC_TYPE_HEX = "d50c7f54"

ARTIFACTS = Path("/Users/mdy/Code/my-own/lorwright-artifacts/analysis/stages/01-prop/parsed")
ADVENTURE = Path("/Users/mdy/Code/my-own/lorwright-artifacts/analysis/stages/03-adventure")


def loc_dict(entries_path: Path) -> dict[str, str]:
    """LocalizedText entries.jsonl → {key: 文案}。"""
    out: dict[str, str] = {}
    with entries_path.open() as f:
        for line in f:
            e = json.loads(line)
            for fld in e["fields"]:
                v = fld["value"]
                if isinstance(v, dict) and v.get("kind") == "map":
                    for pair in v.get("pairs", []):
                        out[pair["key"]] = pair["value"]
    return out


def entry_strings(entry: dict) -> list[str]:
    """顶层（含一层 STRUCT 内）STRING 字段值，按文件顺序。"""
    out = []
    for fld in entry["fields"]:
        v = fld["value"]
        if fld["type"] == "STRING" and isinstance(v, str):
            out.append(v)
        elif fld["type"] == "STRUCT" and isinstance(v, dict):
            out.extend(
                s["value"]
                for s in v.get("fields", [])
                if s.get("type") == "STRING" and isinstance(s.get("value"), str)
            )
    return out


def entry_s32(entry: dict) -> list[int]:
    return [f["value"] for f in entry["fields"] if f["type"] == "S32"]


def extract_definitions(entries_path: Path, type_hex: str) -> list[dict]:
    """按 type_hex 抽定义条目：code/name_key/desc_key/rarity/dev_name/路径。"""
    out = []
    with entries_path.open() as f:
        for line in f:
            e = json.loads(line)
            if e["type_hex"] != type_hex:
                continue
            strings = entry_strings(e)
            # 约定（实测 2026-11-06）：name_key = sticker_<code>_Name 形态；
            # RelicData 有 DevName（紧跟首 BOOL 后的第一个非 key 字符串）；
            # 代码是最短的全大写字母数字串（I0148 / R0153 / ephemeralcopy）。
            name_key = next((s for s in strings if s.endswith("_Name") and "_UpperCase" not in s), None)
            desc_key = next((s for s in strings if s.endswith("_Description")), None)
            code = ""
            if name_key:
                code = name_key.removeprefix("sticker_").removesuffix("_Name")
            path = next((s for s in strings if "/" in s), "")
            dev_name = ""
            for s in strings:
                if s == name_key or s == desc_key or s.endswith("_UpperCase") or "/" in s or s == code:
                    continue
                if s.startswith("sticker_"):
                    continue
                dev_name = s
                break
            s32 = entry_s32(e)
            out.append(
                {
                    "code": code,
                    "name_key": name_key,
                    "description_key": desc_key,
                    "rarity_raw": s32[0] if s32 else None,
                    "dev_name": dev_name,
                    "data_path": path,
                    "entry_sha256": e["entry_sha256"],
                }
            )
    return out


def powers_from_adventure(path: Path) -> list[dict]:
    """03-adventure/powers.jsonl 已含本地化，直接规整。"""
    out = []
    with path.open() as f:
        for line in f:
            e = json.loads(line)
            zh = e.get("localized_name_zh_tw") or [{}]
            zh_blurb = e.get("localized_blurb_zh_tw") or [{}]
            out.append(
                {
                    "ability_code": e.get("ability_code") or (e.get("name_key") or "").removeprefix("ability_").removesuffix("_Name"),
                    "dev_name": e.get("dev_name"),
                    "name_key": e.get("name_key"),
                    "rarity_raw": e.get("rarity_raw"),
                    "rgds_path": e.get("rgds_path"),
                    "name_zh_tw": zh[0].get("value"),
                    "description_zh_tw": zh_blurb[0].get("value"),
                }
            )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gameplay", type=Path, default=ARTIFACTS / "GamePlayData" / "entries.jsonl")
    ap.add_argument("--locale-dir", type=Path, default=ARTIFACTS)
    ap.add_argument("--powers", type=Path, default=ADVENTURE / "powers.jsonl")
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent.parent / "data" / "reward-names.json")
    args = ap.parse_args()

    zh = loc_dict(args.locale_dir / "LocalizedText_zh_tw" / "entries.jsonl")
    en = loc_dict(args.locale_dir / "LocalizedText_en_us" / "entries.jsonl")

    def decorate(rows: list[dict]) -> list[dict]:
        for r in rows:
            nk, dk = r.get("name_key"), r.get("description_key")
            r["name_zh_tw"] = zh.get(nk or "")
            r["name_en"] = en.get(nk or "")
            r["description_zh_tw"] = zh.get(dk or "")
            r["description_en"] = en.get(dk or "")
        return rows

    # 只保留有 name_key 的真实奖励条目；其余是无 name_key 的开发残留
    # （Labs/Items 路径、图标占位等），对识别无用且污染计数。
    items = [r for r in decorate(extract_definitions(args.gameplay, ITEM_TYPE_HEX)) if r["name_key"]]
    relics = [r for r in decorate(extract_definitions(args.gameplay, RELIC_TYPE_HEX)) if r["name_key"]]
    powers = decorate(powers_from_adventure(args.powers))

    gameplay_sha = hashlib.sha256(args.gameplay.read_bytes()).hexdigest() if args.gameplay.stat().st_size < 64 * 1024 * 1024 else None
    payload = {
        "schema_version": 1,
        "note": "静态客户端数据；描述为客户端文案，不代表实现验证。来源与 SHA 见 README。",
        "counts": {"items": len(items), "relics": len(relics), "powers": len(powers)},
        "items": items,
        "relics": relics,
        "powers": powers,
        "source": {
            "gameplay_entries_sha256": gameplay_sha,
            "locale_dir": str(args.locale_dir),
            "powers_jsonl": str(args.powers),
        },
    }
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
    print("counts:", payload["counts"], "->", args.out)


if __name__ == "__main__":
    main()
