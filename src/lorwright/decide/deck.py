"""伊莉絲蜘蛛快攻牌组的卡牌知识 + 出牌评分。

数据来源（已交叉验证）：
  - 牌表：https://wiki.leagueoflegends.com/en-us/LoR:Elise/PoC
  - 数值/效果：Riot Data Dragon `7_10_0`

纯数据 + 纯函数，不碰截图/网络/文件，可以直接单测。

为什么需要这个模块：v1 的评分公式 `atk*2 + hp - cost*1.5` 把这套牌当纯快攻算，
但实际收益结构是 **buff 叠乘** —— 群蛛之主 +2|+0、尖嘯蜘蛛 +2|+0、發狂疾行蛛 +1|+0
都是「喂给其他蜘蛛」的，场上蜘蛛越多越值。所以评分必须含「场上蜘蛛数」。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from lorwright.decide.combat import Combatant, Keyword
from lorwright.models import CardInHand, GameState, Unit


class CardKind(StrEnum):
    UNIT = "unit"
    SPELL = "spell"
    CHAMPION = "champion"


class Effect(StrEnum):
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
class CardDef:
    name: str
    name_en: str
    cost: int
    attack: int = 0
    health: int = 0
    kind: CardKind = CardKind.UNIT
    keywords: frozenset[str] = frozenset()
    effect: Effect = Effect.NONE
    summons: int = 0       # 召唤的小蜘蛛数量
    buff_attack: int = 0   # 给其他蜘蛛的攻击加成

    @property
    def is_buffer(self) -> bool:
        return self.effect in BUFFER_EFFECTS


#: 伊莉絲英雄之路起始牌组（18 张 = 9 种 × 2）
SPIDER_AGGRO: tuple[CardDef, ...] = (
    CardDef("小蜘蛛", "Spiderling", 1, 1, 1),
    CardDef(
        "闇影島泰爾石",
        "Shadow Isles Tellstones",
        1,
        kind=CardKind.SPELL,
        effect=Effect.GENERATE_CHOICE,
    ),
    CardDef(
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
    CardDef(
        "蜘術士",
        "Spell Slinger",
        2,
        1,
        1,
        keywords=frozenset({"fearsome"}),
        effect=Effect.STUN,
    ),
    CardDef("蜘蛛哨兵", "Arachnoid Sentry", 3, 3, 2, effect=Effect.STUN),
    CardDef(
        "發狂疾行蛛",
        "Frenzied Skitterer",
        3,
        3,
        3,
        keywords=frozenset({"fearsome"}),
        effect=Effect.BUFF_ON_SUMMON,
        buff_attack=1,
    ),
    CardDef(
        "尖嘯蜘蛛",
        "Shrieking Spinner",
        4,
        2,
        4,
        effect=Effect.BUFF_ON_ATTACK,
        buff_attack=2,
    ),
    CardDef(
        "群蛛之主",
        "Arachnoid Host",
        5,
        5,
        3,
        effect=Effect.BUFF_PERMANENT,
        buff_attack=2,
    ),
    CardDef(
        "傾巢而出",
        "Brood Awakening",
        6,
        kind=CardKind.SPELL,
        effect=Effect.SUMMON_SPIDERLINGS,
        summons=3,
        buff_attack=1,
    ),
)

#: 游戏内是繁体中文，文档和测试里常写简体 —— 两种都认
_ALIASES: dict[str, str] = {
    "尖啸蜘蛛": "尖嘯蜘蛛",
    "伊莉丝": "伊莉絲",
    "蜘术士": "蜘術士",
    "发狂疾行蛛": "發狂疾行蛛",
    "倾巢而出": "傾巢而出",
    "暗影岛泰尔石": "闇影島泰爾石",
}

BY_NAME: dict[str, CardDef] = {c.name: c for c in SPIDER_AGGRO}
BY_NAME.update({alias: BY_NAME[target] for alias, target in _ALIASES.items()})


def lookup(name: str) -> CardDef | None:
    """按卡名查定义。查不到返回 None（感知层识别错字时不要崩）。"""
    return BY_NAME.get(name.strip())


def score(card: CardDef, *, spiders_on_board: int, enemy_max_attack: int) -> float:
    """这张牌现在打出去值多少。

    数值越大越优先。场上蜘蛛越多，buff 牌越值钱 —— 这是这套牌的核心。
    """
    base = float(card.attack + card.health)
    bonus = 0.0

    if card.effect is Effect.BUFF_PERMANENT:
        # 群蛛之主：每多喂一只就多赚 buff_attack 点永久攻击力
        bonus = card.buff_attack * max(0, spiders_on_board - 1)
    elif card.effect is Effect.BUFF_ON_ATTACK:
        # 尖嘯蜘蛛：本回合攻击前出，等于全体 +2
        bonus = card.buff_attack * spiders_on_board
    elif card.effect is Effect.BUFF_ON_SUMMON:
        # 發狂疾行蛛：+1|+0 给自己以外的蜘蛛，外加敌军 -1|-0 折 1 分
        bonus = card.buff_attack * spiders_on_board + 1
    elif card.effect is Effect.SUMMON_SPIDERLINGS:
        # 傾巢而出：3 只 1/1（每只折 2 分）+ 全体 +1
        bonus = card.summons * 2 + card.buff_attack * spiders_on_board
    elif card.effect is Effect.STUN:
        # 击晕只有在对面有大单位时才值钱
        bonus = 2 * max(0, enemy_max_attack - 3)
    elif card.effect is Effect.ATTACK_SUMMON:
        # 伊莉絲：攻击时白赚一只小蜘蛛
        bonus = card.summons * 2
    elif card.effect is Effect.GENERATE_CHOICE:
        # 泰爾石：1 费换一张 +2|+2，灵活度折 3 分
        bonus = 3.0

    return base + bonus - card.cost * 1.5


def rank_playable(state: GameState) -> list[tuple[CardInHand, CardDef, float]]:
    """当前能打出的牌，按「先 buff 后普通，再按评分」排好序。

    buff 牌先出是这套牌的确定性规则：所有 buff 都是给「其他蜘蛛」的，
    先出只会让后面的牌更值，不会更亏。
    查不到的牌（识别错字/新卡）按 0 费、0 分处理，排在最后但不会被丢掉。
    """
    playable: list[tuple[CardInHand, CardDef, float]] = []
    enemy_max_attack = max((u.attack for u in state.enemy_units), default=0)
    for card in state.hand:
        if not (0 <= card.cost <= state.mana):
            continue
        definition = lookup(card.name) or CardDef(card.name, card.name, card.cost)
        playable.append(
            (
                card,
                definition,
                score(
                    definition,
                    spiders_on_board=state.spider_count,
                    enemy_max_attack=enemy_max_attack,
                ),
            )
        )

    playable.sort(key=lambda item: (not item[1].is_buffer, -item[2]))
    return playable


def to_combatant(unit: Unit, *, challenger: bool = False) -> Combatant:
    """把感知层的 Unit 转成求解器的 Combatant。"""
    keywords = set(unit.keywords)
    if challenger:
        keywords.add("challenger")
    return Combatant(
        attack=unit.attack,
        health=unit.health,
        keywords=frozenset(Keyword(k) for k in keywords if k in set(Keyword)),
        name=unit.name,
        stunned=unit.stunned,
    )
