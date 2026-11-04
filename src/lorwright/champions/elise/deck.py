"""伊莉絲英雄之路起始牌组的牌表。

数据来源（已交叉验证）：
  - 牌表：https://wiki.leagueoflegends.com/en-us/LoR:Elise/PoC
  - 数值/效果/中文名：Riot Data Dragon `7_10_0`

9 种 × 2 = 18 张。游戏内是繁体中文，文档和测试里常写简体 —— 两种都认。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from lorwright.decide.card import CardDef, CardKind


class Effect(StrEnum):
    """这套牌的卡牌效果分类。评分按这个分项，核心层不认识它。"""

    NONE = "none"
    BUFF_PERMANENT = "buff_permanent"          # 群蛛之主：召唤时其他蜘蛛 +2|+0（永久）
    BUFF_ON_ATTACK = "buff_on_attack"          # 尖嘯蜘蛛：攻击时蜘蛛 +2|+0（本回合）
    BUFF_ON_SUMMON = "buff_on_summon"          # 發狂疾行蛛：召唤时其他蜘蛛 +1|+0，敌军 -1|-0
    SUMMON_SPIDERLINGS = "summon_spiderlings"  # 傾巢而出：召唤 3 只小蜘蛛并 +1|+0
    STUN = "stun"                              # 蜘蛛哨兵 / 蜘術士
    ATTACK_SUMMON = "attack_summon"            # 伊莉絲：攻击时召唤小蜘蛛
    GENERATE_CHOICE = "generate_choice"        # 闇影島泰爾石：生成三选一


#: 打出后会增强「之后打出的牌」的效果 —— 同一回合里应该先出
BUFFER_EFFECTS = frozenset(
    {
        Effect.BUFF_PERMANENT,
        Effect.BUFF_ON_ATTACK,
        Effect.BUFF_ON_SUMMON,
        Effect.SUMMON_SPIDERLINGS,
    }
)


@dataclass(frozen=True)
class EliseCard(CardDef):
    """在通用 CardDef 上补这套牌需要的字段。"""

    effect: Effect = Effect.NONE
    summons: int = 0       # 召唤的小蜘蛛数量
    buff_attack: int = 0   # 给其他蜘蛛的攻击加成

    @property
    def is_buffer(self) -> bool:
        return self.effect in BUFFER_EFFECTS


#: 伊莉絲英雄之路起始牌组（18 张 = 9 种 × 2）
SPIDER_AGGRO: tuple[EliseCard, ...] = (
    EliseCard("小蜘蛛", "Spiderling", 1, 1, 1),
    EliseCard(
        # 基础费用 1；英雄之路里常被能力减到 0（牌面显示 0），
        # 但牌表记的是基础值，减费属于对局状态。
        "闇影島泰爾石",
        "Shadow Isles Tellstones",
        1,
        kind=CardKind.SPELL,
        effect=Effect.GENERATE_CHOICE,
    ),
    EliseCard(
        "伊莉絲",
        "Elise",
        2,
        2,
        3,
        kind=CardKind.CHAMPION,
        keywords=frozenset({"fearsome"}),
        effect=Effect.ATTACK_SUMMON,
        summons=1,
    ),
    EliseCard(
        "蜘術士",
        "Spell Slinger",
        2,
        1,
        1,
        keywords=frozenset({"fearsome"}),
        effect=Effect.STUN,
    ),
    EliseCard("蜘蛛哨兵", "Arachnoid Sentry", 3, 3, 2, effect=Effect.STUN),
    EliseCard(
        "發狂疾行蛛",
        "Frenzied Skitterer",
        3,
        3,
        3,
        keywords=frozenset({"fearsome"}),
        effect=Effect.BUFF_ON_SUMMON,
        buff_attack=1,
    ),
    EliseCard(
        "尖嘯蜘蛛",
        "Shrieking Spinner",
        4,
        2,
        4,
        effect=Effect.BUFF_ON_ATTACK,
        buff_attack=2,
    ),
    EliseCard(
        "群蛛之主",
        "Arachnoid Host",
        5,
        5,
        3,
        effect=Effect.BUFF_PERMANENT,
        buff_attack=2,
    ),
    EliseCard(
        "傾巢而出",
        "Brood Awakening",
        6,
        kind=CardKind.SPELL,
        effect=Effect.SUMMON_SPIDERLINGS,
        summons=3,
        buff_attack=1,
    ),
)

#: 游戏内是繁体，文档/测试常写简体
_ALIASES: dict[str, str] = {
    "尖啸蜘蛛": "尖嘯蜘蛛",
    "伊莉丝": "伊莉絲",
    "蜘术士": "蜘術士",
    "发狂疾行蛛": "發狂疾行蛛",
    "倾巢而出": "傾巢而出",
    "暗影岛泰尔石": "闇影島泰爾石",
}

BY_NAME: dict[str, EliseCard] = {c.name: c for c in SPIDER_AGGRO}
BY_NAME.update({alias: BY_NAME[target] for alias, target in _ALIASES.items()})


def lookup(name: str) -> EliseCard | None:
    """按卡名查定义。查不到返回 None（感知层识别错字时不要崩）。"""
    return BY_NAME.get(name.strip())
