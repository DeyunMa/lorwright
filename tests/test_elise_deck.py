"""牌组知识与出牌评分的单测。纯数据，不依赖截图或设备。"""

from __future__ import annotations

import pytest

from lorwright.champions.elise.deck import BY_NAME, SPIDER_AGGRO, Effect, lookup
from lorwright.champions.elise.policy import rank_playable, score
from lorwright.decide.combat import to_combatant
from lorwright.models import CardInHand, GameState, Rect, Unit

RECT = Rect(0, 0, 10, 10)


def hand(index: int, name: str, cost: int) -> CardInHand:
    return CardInHand(index=index, name=name, cost=cost, rect=RECT)


def unit(name: str, attack: int, health: int, **kwargs) -> Unit:
    return Unit(name=name, attack=attack, health=health, rect=RECT, **kwargs)


# ---------- 牌表 ----------


def test_deck_has_nine_unique_cards():
    assert len(SPIDER_AGGRO) == 9


def test_deck_cost_curve_matches_observed_hand():
    """实测手牌费用 4,2,6,5,2,3 与 4,1,6,5,3,1 必须都能从这套牌里抽出来。"""
    costs = sorted(c.cost for c in SPIDER_AGGRO)
    assert costs == [1, 1, 2, 2, 3, 3, 4, 5, 6]


def test_lookup_accepts_both_traditional_and_simplified():
    assert lookup("尖嘯蜘蛛") is lookup("尖啸蜘蛛")
    assert lookup("伊莉絲") is lookup("伊莉丝")
    assert lookup("傾巢而出") is lookup("倾巢而出")
    assert lookup("不存在的牌") is None


def test_card_names_match_game_screenshots():
    """截图里确认过的两张牌必须能在牌表里查到。"""
    assert BY_NAME["尖嘯蜘蛛"].cost == 4
    assert BY_NAME["群蛛之主"].cost == 5


# ---------- 评分 ----------


def test_permanent_buff_scales_with_board():
    """群蛛之主：场上蜘蛛越多越值 —— 这是这套牌的核心收益结构。"""
    card = BY_NAME["群蛛之主"]
    empty = score(card, spiders_on_board=0, enemy_max_attack=0)
    three = score(card, spiders_on_board=3, enemy_max_attack=0)
    assert three > empty


def test_buff_on_attack_scales_with_board():
    card = BY_NAME["尖嘯蜘蛛"]
    assert score(card, spiders_on_board=4, enemy_max_attack=0) > score(
        card, spiders_on_board=0, enemy_max_attack=0
    )


def test_stun_only_valuable_against_big_units():
    card = BY_NAME["蜘蛛哨兵"]
    assert score(card, spiders_on_board=0, enemy_max_attack=8) > score(
        card, spiders_on_board=0, enemy_max_attack=2
    )


def test_brood_awakening_counts_summoned_spiderlings():
    card = BY_NAME["傾巢而出"]
    assert card.effect is Effect.SUMMON_SPIDERLINGS
    assert card.summons == 3


# ---------- 出牌排序 ----------


def test_summon_buff_cards_are_played_after_plain_units():
    """「召喚此牌時」型 buff 要后出，不能先出。

    官方 7_10_0 文本：群蛛之主「召喚此牌時，賦予我方其他蜘蛛單位 +2|+0」，
    發狂疾行蛛「召喚此牌時，本回合給予我方其他蜘蛛單位 +1|+0」。
    两条都只影响**当时已在场**的蜘蛛 —— 先出它，后面铺上去的蜘蛛吃不到 buff。
    所以正确顺序是先把受益单位铺上去，再召唤这两张。

    之前这里锁的是反的结论（`is_buffer` 优先），依据是「先出只会让后面更值」，
    但那句话只对「给之后打出的牌加成」的效果成立，这套牌里没有这种效果。
    """
    state = GameState(
        mana=10,
        hand=[hand(0, "蜘蛛哨兵", 3), hand(1, "群蛛之主", 5)],
        my_units=[unit("小蜘蛛", 1, 1), unit("小蜘蛛", 1, 1)],
        enemy_units=[unit("大块头", 10, 10)],
    )
    ranked = rank_playable(state)
    assert ranked[0][1].name == "蜘蛛哨兵"
    assert ranked[-1][1].name == "群蛛之主"


def test_attack_trigger_buff_is_not_deferred():
    """「攻擊：」型 buff（尖嘯蜘蛛）不吃出牌顺序，不该被排到最后。

    它是在攻击时给全体蜘蛛 +2|+0，早出晚出效果一样；
    把它和「召喚時」型混在一起排到后面，只会白白让它少参与一次攻击。
    """
    from lorwright.champions.elise.deck import lookup

    spinner = lookup("尖嘯蜘蛛")
    host = lookup("群蛛之主")
    assert spinner is not None and host is not None
    assert not spinner.settles_last
    assert host.settles_last


def test_rank_playable_filters_by_mana():
    state = GameState(mana=3, hand=[hand(0, "群蛛之主", 5), hand(1, "蜘蛛哨兵", 3)])
    ranked = rank_playable(state)
    assert [item[1].name for item in ranked] == ["蜘蛛哨兵"]


def test_rank_playable_keeps_unknown_cards():
    """感知层识别出错字时不能崩，也不能把牌丢掉。"""
    state = GameState(mana=5, hand=[hand(0, "某张没见过的牌", 2)])
    ranked = rank_playable(state)
    assert len(ranked) == 1
    assert ranked[0][1].name == "某张没见过的牌"


# ---------- 单位转换 ----------


def test_to_combatant_maps_stun_and_challenger():
    plain = to_combatant(unit("小蜘蛛", 1, 1, stunned=True))
    assert plain.stunned

    champ = to_combatant(unit("伊莉絲", 2, 3), challenger=True)
    assert champ.has_challenger


def test_to_combatant_ignores_unknown_keywords():
    """感知层可能返回任意字符串，不能因为一个怪词就抛异常。"""
    combatant = to_combatant(unit("怪东西", 1, 1, keywords=frozenset({"不存在的关键词"})))
    assert combatant.keywords == frozenset()


@pytest.mark.parametrize("name", [c.name for c in SPIDER_AGGRO])
def test_every_deck_card_converts(name):
    card = BY_NAME[name]
    combatant = to_combatant(unit(name, card.attack, card.health))
    assert combatant.attack == card.attack
