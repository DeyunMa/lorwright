"""伊莉絲（Elise）英雄包 —— 蜘蛛快攻。

牌组细节见 `docs/champions/elise.md`。
"""

from __future__ import annotations

from lorwright.champions.elise.deck import BY_NAME, SPIDER_AGGRO, Effect, EliseCard, lookup
from lorwright.champions.elise.policy import SpiderAggroPolicy, rank_playable, score
from lorwright.decide.card import CardDef


class ElisePack:
    name = "elise"
    display_name = "伊莉絲"

    #: 牌表（对外只承诺通用字段，EliseCard 是 CardDef 的子类）
    deck: tuple[CardDef, ...] = SPIDER_AGGRO

    def make_policy(self) -> SpiderAggroPolicy:
        return SpiderAggroPolicy()


PACK = ElisePack()

__all__ = [
    "BY_NAME",
    "PACK",
    "SPIDER_AGGRO",
    "Effect",
    "EliseCard",
    "ElisePack",
    "SpiderAggroPolicy",
    "lookup",
    "rank_playable",
    "score",
]
