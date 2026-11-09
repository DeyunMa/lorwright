"""伊莉絲（Elise）英雄包 —— 蜘蛛快攻。

牌组细节见 `docs/champions/elise.md`。
"""

from __future__ import annotations

from lorwright.champions.base import Preference
from lorwright.champions.elise.deck import BY_NAME, SPIDER_AGGRO, Effect, EliseCard, lookup
from lorwright.champions.elise.policy import SpiderAggroPolicy, rank_playable, score
from lorwright.champions.elise.vision import recognize_hand
from lorwright.decide.card import CardDef

# 奖励偏好（用户确认，2026-11-05）。未命中走默认「品质>费用」。
# 重拳出擊（Heavy Hands）名字对照来自游戏本地化数据
# （LocalizedText_zh_tw.bin 的 sticker_I0130 键）。
RELIC_PREFERENCES: tuple[Preference, ...] = ()
ITEM_PREFERENCES = (
    Preference(
        names=("Heavy Hands", "重拳出擊"),
        note="雙重攻擊：蜘蛛快攻攻击频率翻倍，道具最优先"
        "（已有双攻/閃靈/不可移动的卡不吃）",
    ),
)
POWER_PREFERENCES: tuple[Preference, ...] = ()
SPELL_PREFERENCES: tuple[Preference, ...] = ()


class ElisePack:
    name = "elise"
    display_name = "伊莉絲"

    #: 牌表（对外只承诺通用字段，EliseCard 是 CardDef 的子类）
    deck: tuple[CardDef, ...] = SPIDER_AGGRO
    lookup = staticmethod(lookup)
    recognize_hand = staticmethod(recognize_hand)

    relic_preferences = RELIC_PREFERENCES
    item_preferences = ITEM_PREFERENCES
    spell_preferences = SPELL_PREFERENCES
    power_preferences = POWER_PREFERENCES

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
