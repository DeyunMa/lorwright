"""战斗求解器的单测：纯数值，不依赖截图或设备。"""

from __future__ import annotations

import time

from lorwright.decide.combat import (
    Combatant,
    Keyword,
    best_attack,
    best_blocking,
    can_block,
    is_lethal,
    max_nexus_damage,
    strike,
)


def unit(attack: int, health: int, *keywords: Keyword, name: str = "", stunned: bool = False) -> Combatant:
    return Combatant(
        attack=attack,
        health=health,
        keywords=frozenset(keywords),
        name=name,
        stunned=stunned,
    )


# ---------- 单次交锋 ----------


def test_unblocked_hits_nexus_for_full_attack():
    plan = best_blocking([unit(3, 2)], [])
    assert plan.nexus_damage == 3
    assert plan.pairs == ()


def test_plain_trade_kills_both():
    _, attacker_dies, blocker_dies = strike(unit(3, 2), unit(2, 2))
    assert attacker_dies and blocker_dies


def test_quick_attack_survives_kill():
    trample, attacker_dies, blocker_dies = strike(
        unit(3, 1, Keyword.QUICK_ATTACK), unit(2, 2)
    )
    assert blocker_dies
    assert not attacker_dies
    assert trample == 0


def test_tough_reduces_incoming_damage():
    _, _, blocker_dies = strike(unit(2, 2), unit(1, 4, Keyword.TOUGH))
    assert not blocker_dies  # 2 点伤害被减到 1，4 血挡得住


def test_overwhelm_tramples_excess_to_nexus():
    trample, _, blocker_dies = strike(unit(5, 5, Keyword.OVERWHELM), unit(2, 2))
    assert blocker_dies
    assert trample == 3


# ---------- 格挡合法性 ----------


def test_elusive_cannot_be_blocked_by_plain_unit():
    assert not can_block(unit(2, 2), unit(3, 2, Keyword.ELUSIVE))
    assert can_block(unit(2, 2, Keyword.ELUSIVE), unit(3, 2, Keyword.ELUSIVE))


def test_fearsome_needs_three_attack_to_block():
    assert not can_block(unit(2, 2), unit(4, 2, Keyword.FEARSOME))
    assert can_block(unit(3, 1), unit(4, 2, Keyword.FEARSOME))


def test_fearsome_attacker_goes_face_when_no_legal_blocker():
    plan = best_blocking([unit(4, 2, Keyword.FEARSOME)], [unit(2, 3)])
    assert plan.nexus_damage == 4
    assert plan.pairs == ()


# ---------- 守方最优格挡 ----------


def test_blocker_picks_cheapest_adequate_block():
    """5/5 打过来，1/1 和 2/2 都能挡死；守方该用损失最小的 1/1。"""
    plan = best_blocking([unit(5, 5)], [unit(1, 1), unit(2, 2)])
    assert plan.nexus_damage == 0
    assert plan.pairs == ((0, 0),)  # 用下标 1 的 1/1


def test_defender_prefers_trading_when_free():
    """能用 3/3 白吃 2/1 时应该挡，而不是放脸。"""
    plan = best_blocking([unit(2, 1)], [unit(3, 3)])
    assert plan.nexus_damage == 0
    assert plan.attacker_loss == 3
    assert plan.blocker_loss == 0


# ---------- 攻方声明与斩杀 ----------


def test_lethal_with_empty_board():
    mine = [unit(3, 2), unit(4, 3)]
    assert max_nexus_damage(mine, []) == 7
    assert is_lethal(mine, [], enemy_nexus_hp=7)


def test_not_lethal_when_blocker_absorbs():
    """对手只有一个 2/2：它宁可拿 2/2 换掉 3/2，只放 3 点脸伤过去，7 血杀不掉。"""
    mine = [unit(3, 2), unit(4, 3)]
    assert max_nexus_damage(mine, [unit(2, 2)]) == 3
    assert not is_lethal(mine, [unit(2, 2)], enemy_nexus_hp=7)


def test_attack_plan_holds_back_units_that_would_just_die():
    """对面两个 3/3：再派一个 1/1 只会白送，最优声明只派 4/4。"""
    plan = best_attack(
        [unit(4, 4), unit(1, 1)], [unit(3, 3), unit(3, 3)], nexus_weight=3.0
    )
    assert plan.attackers == (0,)


def test_attack_plan_sends_everyone_when_board_is_empty():
    plan = best_attack([unit(2, 1), unit(3, 2), unit(1, 1)], [])
    assert plan.attackers == (0, 1, 2)
    assert plan.nexus_damage == 6


# ---------- 击晕 ----------


def test_stunned_unit_cannot_block():
    """蜘術士/蜘蛛哨兵击晕的敌人本回合不能格挡，可以直接打脸。"""
    plan = best_blocking([unit(3, 2)], [unit(5, 5, stunned=True)])
    assert plan.nexus_damage == 3
    assert plan.pairs == ()


def test_stunned_unit_cannot_attack():
    assert not unit(5, 5, stunned=True).can_attack
    assert unit(5, 5).can_attack


# ---------- 挑战者 ----------


def test_challenger_lets_attacker_choose_the_trade():
    """伊莉丝升级后所有蜘蛛带挑战者：由攻方而不是守方决定谁挡谁。"""
    atk = unit(2, 2, Keyword.CHALLENGER)
    blockers = [unit(1, 1), unit(3, 3)]

    # 守方选：拿 3/3 换掉我的 2/2
    defender = best_blocking([atk], blockers, chooser="defender")
    assert defender.attacker_loss == 4

    # 攻方选（看重场面）：挑 1/1 打，自己活下来
    attacker = best_blocking([atk], blockers, chooser="attacker", nexus_weight=0.5)
    assert attacker.attacker_loss == 0
    assert attacker.blocker_loss == 2


# ---------- 规模 ----------


def test_full_board_search_stays_fast():
    """6 打 6 的精确搜索要在一次 tick 内跑完（tick 预算 200ms）。"""
    mine = [unit(2, 2) for _ in range(6)]
    theirs = [unit(2, 2) for _ in range(6)]
    t0 = time.perf_counter()
    best_blocking(mine, theirs)
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.2, f"6v6 格挡搜索耗时 {elapsed * 1000:.0f}ms，超出 tick 预算"
