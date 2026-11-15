"""Jinx 英雄包：目前只实现经用户确认的两步起手。"""

from lorwright.core.champions.base import Preference
from lorwright.core.champions.jinx.deck import JINX_DECK, lookup
from lorwright.core.champions.jinx.policy import JinxOpeningPolicy, pick_card_reward
from lorwright.core.champions.jinx.vision import (
    recognize_hand,
    recognize_hero,
    recognize_mulligan,
    recognize_selected_hero,
    recognize_targeted_spell,
)

# 奖励偏好（用户确认，2026-11-05）。未命中走默认「品质>费用」。
# 名字对照来自游戏本地化数据（LocalizedText_zh_tw.bin 的
# sticker_ephemeralcopy / power_summon_stabilize 键）。
RELIC_PREFERENCES: tuple[Preference, ...] = ()
ITEM_PREFERENCES = (
    Preference(
        names=("Shadow Totem", "闇影圖騰"),
        note="出牌：召唤该牌的閃靈複製單位 —— 召唤流核心道具",
    ),
)
POWER_PREFERENCES = (
    Preference(
        names=("Stabilize", "分身術"),
        note="打出英雄时召唤该英雄的閃靈複製單位",
    ),
)
SPELL_PREFERENCES: tuple[Preference, ...] = ()
CARD_PREFERENCES: tuple[Preference, ...] = ()


class JinxPack:
    name = "jinx"
    display_name = "金克丝"
    # 9 种 × 2 = 18 张；数据来源见 deck.py。
    deck = JINX_DECK
    lookup = staticmethod(lookup)
    recognize_hand = staticmethod(recognize_hand)
    recognize_map_hero = staticmethod(recognize_hero)
    recognize_selected_hero = staticmethod(recognize_selected_hero)
    recognize_mulligan = staticmethod(recognize_mulligan)
    recognize_targeted_spell = staticmethod(recognize_targeted_spell)
    pick_card_reward = staticmethod(pick_card_reward)

    relic_preferences = RELIC_PREFERENCES
    item_preferences = ITEM_PREFERENCES
    card_preferences = CARD_PREFERENCES
    spell_preferences = SPELL_PREFERENCES
    power_preferences = POWER_PREFERENCES

    def make_policy(
        self, *, spell_already_played: bool = False, jinx_summoned: bool = False,
        rockets_already_played: int = 0,
    ) -> JinxOpeningPolicy:
        return JinxOpeningPolicy(
            spell_already_played=spell_already_played,
            jinx_summoned=jinx_summoned,
            rockets_already_played=rockets_already_played,
        )


PACK = JinxPack()

__all__ = ["JINX_DECK", "PACK", "JinxPack", "lookup"]
