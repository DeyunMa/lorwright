"""Jinx 英雄之路起始牌组（9 种 × 2 = 18 张）。

数据来源：`lorwright-artifacts/research/champion-progression/data/champions.jsonl`
（champion=Jinx，champion_card_code=01PZ040），已对 07.11.015 GamePlayData
的 ClientCardData 交叉核验。99PZ130/99PZ104 是 PoC 专属卡。
"""

from __future__ import annotations

from dataclasses import dataclass

from lorwright.decide.card import CardDef, CardKind


@dataclass(frozen=True)
class JinxCard(CardDef):
    code: str = ""
    count: int = 2


JINX_DECK: tuple[JinxCard, ...] = (
    JinxCard("吉茵珂絲", "Jinx", 4, 4, 3, CardKind.CHAMPION, code="01PZ040"),
    JinxCard("砰砰", "Pow-Pow", 2, kind=CardKind.SPELL, code="99PZ130"),
    JinxCard("爆破幫菜鳥", "Boomcrew Rookie", 2, 1, 3, code="01PZ054"),
    JinxCard("懸浮飛板初學者", "Amateur Aeronaut", 3, 2, 3, code="01PZ009"),
    JinxCard("火箭滑板", "Rocketboarder", 2, 3, 3, code="99PZ104"),
    JinxCard("勤奮的學徒", "Eager Apprentice", 2, 2, 1, code="01PZ019"),
    JinxCard("佐恩小乞丐", "Zaunite Urchin", 1, 2, 1, code="01PZ045"),
    JinxCard("汙水坑疏濬機器人", "Sump Dredger", 3, 4, 3, code="01PZ038"),
    JinxCard("應急裝置", "Jury-Rig", 1, kind=CardKind.SPELL, code="01PZ028"),
)

# Jinx 下场后由能力生成的牌，不在 18 张起始牌组里，但手牌识别要能命名。
JINX_TOKENS: tuple[JinxCard, ...] = (
    JinxCard(
        "超威能死亡火箭！", "Super Mega Death Rocket!", 6,
        kind=CardKind.SPELL, code="01PZ040T1", count=0,
    ),
)

BY_CODE: dict[str, JinxCard] = {
    card.code: card for card in (*JINX_DECK, *JINX_TOKENS)
}
BY_NAME: dict[str, JinxCard] = {
    card.name: card for card in (*JINX_DECK, *JINX_TOKENS)
}

# 常见简体/别名
_ALIASES = {
    "祖安小乞丐": "佐恩小乞丐",
    "金克丝": "吉茵珂絲",
    "应急装置": "應急裝置",
    "悬浮飞板初学者": "懸浮飛板初學者",
    "勤奋的学徒": "勤奮的學徒",
    "爆破帮菜鸟": "爆破幫菜鳥",
    "污水坑疏浚机器人": "汙水坑疏濬機器人",
    "超究极死神飞弹": "超威能死亡火箭！",
    "超究極死神飛彈": "超威能死亡火箭！",
    "威能死亡火箭！": "超威能死亡火箭！",
    "威能死亡火箭": "超威能死亡火箭！",
}


def lookup(name: str) -> JinxCard | None:
    if name in BY_NAME:
        return BY_NAME[name]
    alias = _ALIASES.get(name)
    return BY_NAME.get(alias) if alias else None


__all__ = [
    "BY_CODE", "BY_NAME", "JINX_DECK", "JINX_TOKENS", "JinxCard", "lookup",
]
