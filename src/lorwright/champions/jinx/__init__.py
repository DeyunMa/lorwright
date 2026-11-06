"""Jinx 英雄包：目前只实现经用户确认的两步起手。"""

from lorwright.champions.base import Preference
from lorwright.champions.jinx.policy import JinxOpeningPolicy
from lorwright.champions.jinx.vision import recognize_hand
from lorwright.decide.card import CardDef, CardKind

# 奖励偏好（用户确认，2026-11-05）。未命中走默认「品质>费用」。
# 名字对照来自游戏本地化数据（LocalizedText_zh_tw.bin 的
# sticker_ephemeralcopy / power_summon_stabilize 键）。
RELIC_PREFERENCES = (
    Preference(
        names=("Shadow Totem", "闇影圖騰"),
        note="出牌：召唤该牌的閃靈複製單位 —— 召唤流核心遗物",
    ),
)
POWER_PREFERENCES = (
    Preference(
        names=("Stabilize", "分身術"),
        note="打出英雄时召唤该英雄的閃靈複製單位",
    ),
)
ITEM_PREFERENCES: tuple[Preference, ...] = ()
SPELL_PREFERENCES: tuple[Preference, ...] = ()


class JinxPack:
    name = "jinx"
    display_name = "金克丝"
    deck = (
        CardDef("應急裝置", "Jury-Rig", cost=1, kind=CardKind.SPELL),
        CardDef("吉茵珂絲", "Jinx", cost=4, kind=CardKind.CHAMPION),
    )
    recognize_hand = staticmethod(recognize_hand)

    relic_preferences = RELIC_PREFERENCES
    item_preferences = ITEM_PREFERENCES
    spell_preferences = SPELL_PREFERENCES
    power_preferences = POWER_PREFERENCES

    def make_policy(self) -> JinxOpeningPolicy:
        return JinxOpeningPolicy()


PACK = JinxPack()
