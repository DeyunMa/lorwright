"""重建金克丝（Jinx）英雄之路的候选卡池，逐条标注出处。

为什么要这个脚本：上游需求引用了「Jinx 全部 62 张牌」的清单，其来源
docs/kingt/金克丝英雄包完整复盘.md 在 lorwright、lorwright-artifacts 与 f1 三处都不存在。
卡池也不能从静态客户端数据推出来——奖励选项卡所在的 AdventureCardChoiceData 结构体
字段数为 0，AdventureNodeData 只有 WorldSpacePosition 与 GdsGuid（节点到遭遇的分配是
运行时决定的，research/adventure-catalog 记录 node_encounter_assignments = 0）。

所以本脚本只产出有出处的候选口径，并保留每个卡码的证据链，不假装它就是那 62 张。

用法：
    python tools/kingt/derive_jinx_pool.py --out docs/kingt/jinx_pool_candidates.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from lorwright.champions.jinx.deck import JINX_DECK, JINX_TOKENS  # noqa: E402

CARD_CODE = re.compile(r"^\d{2}[A-Z]{2}\d{3}(?:T\d+)?$")
FALLBACK_ART = "research/poc-card-art-fallback/data/cards"


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_catalog(artifacts: Path) -> dict[str, dict]:
    """卡码 -> 客户端牌表条目（繁中名 / 英文名 / 费用 / 类型）。"""
    for candidate in (
        artifacts / "research/poc-card-names/data/cards.jsonl",
        artifacts / "research/card-text/data/cards.jsonl",
    ):
        if not candidate.is_file():
            continue
        rows = [json.loads(x) for x in candidate.read_text(encoding="utf-8").splitlines() if x]
        catalog = {}
        for row in rows:
            code = row.get("code")
            if not code:
                continue
            catalog[code] = {
                "name_zh_tw": row.get("name_zh_tw"),
                "name_en": row.get("name_en"),
                "cost": row.get("cost"),
                "type_name": row.get("type_name"),
                "supertype_name": row.get("supertype_name"),
                "rarity_name": row.get("rarity_name"),
            }
        catalog["_source"] = {"path": str(candidate)}
        return catalog
    raise SystemExit(f"找不到客户端牌表 cards.jsonl（在 {artifacts}/research 下）")


def campaign_referenced(artifacts: Path) -> tuple[list[str], str]:
    """rgds_path / dev_name 含 Jinx 的条目直接连出的卡码（links 深度 1）。"""
    sqlite_path = artifacts / "analysis/stages/02-domain/domain.sqlite"
    if not sqlite_path.is_file():
        return [], f"missing {sqlite_path}"
    conn = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        roots = [
            dict(r)
            for r in conn.execute(
                "select path_hash, type_name, dev_name, code, rgds_path from entries "
                "where rgds_path like '%Jinx%' or dev_name like '%Jinx%'"
            )
        ]
        codes: set[str] = set()
        for row in roots:
            own = row["code"]
            if own and CARD_CODE.match(own):
                codes.add(own)
            for target in conn.execute("select target from links where owner = ?", (row["path_hash"],)):
                entry = conn.execute(
                    "select code from entries where path_hash = ?", (target["target"],)
                ).fetchone()
                if entry and entry["code"] and CARD_CODE.match(entry["code"]):
                    codes.add(entry["code"])
        evidence = (
            f"domain.sqlite：{len(roots)} 个 Jinx 相关条目（AdventureEncounterData / "
            "AdventurePowerRank / AdventureConfig / SpeAbilityDefinition_Client / "
            "ClientCardData 等）及其一层 links 指向的 ClientCardData.code"
        )
        return sorted(codes), evidence
    finally:
        conn.close()


def faction_of(code: str) -> str:
    match = re.match(r"^\d{2}([A-Z]{2})", code)
    return match.group(1) if match else ""


def evidence_paths(artifacts: Path, catalog_source: str) -> list[str]:
    candidates = [
        catalog_source,
        str(artifacts / "research/champion-progression/data/champions.jsonl"),
        str(artifacts / "analysis/stages/02-domain/domain.sqlite"),
        str(artifacts / "research/adventure-catalog/data/encounters.jsonl"),
    ]
    return [path for path in candidates if Path(path).is_file()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--artifacts",
        default=os.environ.get("LORWRIGHT_ARTIFACTS") or str(REPO.parent / "lorwright-artifacts"),
        help="lorwright-artifacts 根目录",
    )
    ap.add_argument("--out", default="docs/kingt/jinx_pool_candidates.json")
    args = ap.parse_args()

    artifacts = Path(args.artifacts).resolve()
    if not artifacts.is_dir():
        raise SystemExit(f"artifacts 目录不存在：{artifacts}")

    catalog = load_catalog(artifacts)
    catalog_source = catalog.pop("_source")["path"]
    codes = sorted(catalog)
    camp_codes, camp_evidence = campaign_referenced(artifacts)
    death_rocket = {c for c in codes if catalog[c].get("name_en") == "Super Mega Death Rocket!"}
    rocket_barrage = {c for c in codes if catalog[c].get("name_en") == "Rocket Barrage"}

    groups = {
        "starting_deck": {
            "desc": "起始牌组 9 种 ×2 = 18 张",
            "confidence": "确证",
            "codes": sorted({c.code for c in JINX_DECK}),
            "evidence": "src/lorwright/champions/jinx/deck.py JINX_DECK；交叉核验 "
                        "champion-progression/data/champions.jsonl anchors.Jinx"
                        "（deck_size 9 / total 18）",
        },
        "jinx_tokens": {
            "desc": "Jinx 下场后由能力生成的牌，不在 18 张起始牌组里但要能识别",
            "confidence": "确证",
            "codes": sorted({c.code for c in JINX_TOKENS}),
            "evidence": "src/lorwright/champions/jinx/deck.py JINX_TOKENS",
        },
        "campaign_referenced": {
            "desc": "客户端数据里名字/路径含 Jinx 的冒险条目直接连出的卡码",
            "confidence": "确证的引用关系，不等于完整奖励池",
            "codes": camp_codes,
            "evidence": camp_evidence,
        },
        "rocket_spells": {
            "desc": "复盘点名的两张法术：超威能死亡火箭各卡码，以及火箭轰击"
                    "（简体译名，繁中客户端作「火箭亂發」，英文 Rocket Barrage）",
            "confidence": "确证卡码",
            "codes": sorted(
                {c for c in codes if c.startswith("01PZ040T")} | death_rocket | rocket_barrage
            ),
            "evidence": f"{catalog_source} 按 name_en 精确匹配",
        },
        "poc_pz_pool": {
            "desc": "PoC 专属皮城/祖安卡（00PZ*/99PZ*，含各英雄战役卡，Data Dragon 无图）",
            "confidence": "确证卡码集合；是否属于 Jinx 局需按战役归属逐张判断",
            "codes": sorted(c for c in codes if c[:2] in ("00", "99") and faction_of(c) == "PZ"),
            "evidence": f"{catalog_source} 卡码前缀过滤",
        },
        "pz_region_superset": {
            "desc": "皮城/祖安全部卡码，奖励池的最大候选口径，用于兜底取图",
            "confidence": "超集，非清单",
            "codes": sorted(c for c in codes if faction_of(c) == "PZ"),
            "evidence": f"{catalog_source} 阵营过滤",
        },
    }

    members: dict[str, list[str]] = {}
    for name, group in groups.items():
        for code in group["codes"]:
            members.setdefault(code, []).append(name)

    confirmed = sorted(
        set().union(
            *(set(g["codes"]) for g in groups.values() if g["confidence"].startswith("确证"))
        )
    )
    cards = [
        {
            "code": code,
            "groups": members[code],
            **{k: catalog[code].get(k) for k in
               ("name_zh_tw", "name_en", "cost", "type_name", "supertype_name", "rarity_name")},
            "in_client_catalog": True,
            "local_art_fallback": (
                str(artifacts / FALLBACK_ART / f"{code}.png")
                if (artifacts / FALLBACK_ART / f"{code}.png").is_file() else None
            ),
        }
        for code in sorted(members)
    ]

    payload = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "artifacts_root": str(artifacts),
        "purpose": "为 jinx_card_templates_manifest.json 提供带出处的卡码集合。"
                   "上游引用的 62 张清单文件不存在，所以这里给候选口径而非唯一答案。",
        "groups": groups,
        "counts": {name: len(group["codes"]) for name, group in groups.items()},
        "counts_summary": {
            "union_all_groups": len(members),
            "union_confirmed_groups": len(confirmed),
            "starting_deck_plus_poc_pz_dedup": len(
                set(groups["starting_deck"]["codes"]) | set(groups["poc_pz_pool"]["codes"])
            ),
        },
        "union_confirmed_groups": confirmed,
        "notes": [
            "静态客户端数据编码不出奖励可选卡：AdventureCardChoiceData 字段数为 0，"
            "AdventureNodeData 只有坐标与 GdsGuid，节点到遭遇的分配在运行时决定。",
            "没有任何一个自然过滤结果等于 62。最接近的是起始 9 种 + PoC 专属 99PZ/00PZ "
            "非 token 52 种（去掉与起始牌组重复的 99PZ104/99PZ130）再补火箭 token 与火箭轰击，"
            "数值接近 62 属巧合，不作为结论。",
            "火箭轰击 = 05PZ038 Rocket Barrage（繁中「火箭亂發」）；超威能死亡火箭有 "
            "01PZ040T1（6 费）/01PZ040T2（1 费）/00PZ012T1（2 费）三个卡码。",
        ],
        "evidence_files": [
            {"path": path, "sha256": sha256_of(Path(path))}
            for path in evidence_paths(artifacts, catalog_source)
        ],
        "cards": cards,
    }

    out = Path(args.out)
    if not out.is_absolute():
        out = REPO / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"已写出 {out}")
    print(f"分组计数：{payload['counts']}")
    print(f"并集 {len(members)} 张，确证组并集 {len(confirmed)} 张，"
          f"起始+PoC专属去重 {payload['counts_summary']['starting_deck_plus_poc_pz_dedup']} 张")


if __name__ == "__main__":
    main()
