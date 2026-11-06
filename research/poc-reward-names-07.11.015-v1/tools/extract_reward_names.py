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

# 范围过滤（2026-11-06 按全量路径统计定，非推断）：
#   CardStickerData 中只有 ReforgedCampaigns/Items/ 前缀的是道具节点奖励
#   （Mods/Power_4/Stickers 是 power 贴图变体、Mods/Power_XP1 与 XP1 是
#   活动贴纸、CardProfiles 是美术条目——全排除）；RelicData 同理只取
#   Loot/…/Relics 前缀（CardProfiles/Illustrations 是美术变体）。
ITEM_PATH_PREFIX = "ReforgedCampaigns/Items/"
RELIC_PATH_PREFIX = "Loot/CardMetaProgression/Relics"
CODE_TOKEN = __import__("re").compile(r"^[A-Z]\d{4}$")

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
            # 条目里有两个带 / 的字符串：图标路径（Assets/…png，先出现）
            # 和数据路径（ReforgedCampaigns/Items/… 或 Loot/…/Relics/…）。
            # 各按前缀取，不能拿“第一个带 / 的”凑合——那是图标路径。
            prefix = ITEM_PATH_PREFIX if type_hex == ITEM_TYPE_HEX else RELIC_PATH_PREFIX
            path = next((s for s in strings if s.startswith(prefix)), None)
            if not path:
                continue
            icon_path = next((s for s in strings if s.startswith("Assets/AssetLibrary")), None)
            # 键名大小写不统一：Heavy Hands 用 _Name/_Name_UpperCase，
            # Shadow Totem(I0012) 用 _name/_name_caps —— 必须大小写不敏感，
            # 否则会漏掉整条奖励（2026-11-06 用户纠错：闇影圖騰被漏）。
            def is_name_key(s: str) -> bool:
                low = s.lower()
                return low.endswith("_name") and "_uppercase" not in low and "_caps" not in low

            def is_desc_key(s: str) -> bool:
                return s.lower().endswith("_description")

            name_key = next((s for s in strings if is_name_key(s)), None)
            desc_key = next((s for s in strings if is_desc_key(s)), None)
            # code 是独立的 I####/R#### token；不从 name_key 推导
            # （键名大小写不一，且 ephemeralcopy 这类命名键不含 code）。
            code = next((s for s in strings if CODE_TOKEN.match(s)), None)
            dev_name = ""
            for s in strings:
                low = s.lower()
                if s == name_key or s == desc_key or s == code or "/" in s:
                    continue
                if low.startswith("sticker_") or low.endswith("_name") or low.endswith("_caps") or low.endswith("_description"):
                    continue
                if CODE_TOKEN.match(s):
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
                    "icon_path": icon_path,
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


def _split_named(rows: list[dict], cat: str) -> tuple[list[dict], list[dict]]:
    """按「name_key 能解析出名字且 code 唯一」收录；其余进 excluded。"""
    named, excluded = [], []
    seen: set[str] = set()
    for r in rows:
        if r.get("name_zh_tw") and r.get("code") and r["code"] not in seen:
            seen.add(r["code"])
            named.append(r)
        else:
            reasons = []
            if not r.get("name_zh_tw"):
                reasons.append("name_key 不在 LocalizedText（Equipment 子变体/事件贴纸）")
            if not r.get("code"):
                reasons.append("无 code token")
            if r.get("code") in seen:
                reasons.append("code 重复")
            excluded.append({**r, "exclude_reason": "；".join(reasons) or "unknown"})
    return named, excluded


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

    raw_items = decorate(extract_definitions(args.gameplay, ITEM_TYPE_HEX))
    raw_relics = decorate(extract_definitions(args.gameplay, RELIC_TYPE_HEX))

    # 收录规则（数据证据，2026-11-06）：范围过滤后仍有两类条目没有
    # 可显示名——Equipment 子变体（Sheen/TitansAxe/ChaliceofHarmony 等
    # 双形态道具的部件贴纸，显示名来自父道具）、8A_ITEMS 事件贴纸与
    # 关键词贴纸（name_key 不在 LocalizedText）。这些不是独立奖励选项，
    # 单独放进 excluded（不静默丢弃）；收录体 = name_key 能解析出名字
    # 且 code 唯一的条目。
    items, excluded_items = _split_named(raw_items, "items")
    relics, excluded_relics = _split_named(raw_relics, "relics")
    powers = decorate(powers_from_adventure(args.powers))

    gameplay_sha = hashlib.sha256(args.gameplay.read_bytes()).hexdigest() if args.gameplay.stat().st_size < 64 * 1024 * 1024 else None
    payload = {
        "schema_version": 1,
        "note": "静态客户端数据；描述为客户端文案，不代表实现验证。来源与 SHA 见 README。",
        "counts": {"items": len(items), "relics": len(relics), "powers": len(powers)},
        "items": items,
        "relics": relics,
        "powers": powers,
        "excluded_no_display_name": {"items": excluded_items, "relics": excluded_relics},
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
