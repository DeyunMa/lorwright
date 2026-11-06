"""Jinx 英雄包：目前只实现经用户确认的两步起手。"""

from lorwright.champions.jinx.policy import JinxOpeningPolicy
from lorwright.champions.jinx.vision import recognize_hand
from lorwright.decide.card import CardDef, CardKind


class JinxPack:
    name = "jinx"
    display_name = "金克丝"
    deck = (
        CardDef("應急裝置", "Jury-Rig", cost=1, kind=CardKind.SPELL),
        CardDef("吉茵珂絲", "Jinx", cost=4, kind=CardKind.CHAMPION),
    )
    recognize_hand = staticmethod(recognize_hand)

    def make_policy(self) -> JinxOpeningPolicy:
        return JinxOpeningPolicy()


PACK = JinxPack()
