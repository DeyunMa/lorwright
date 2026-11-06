from dataclasses import replace

from lorwright.decide.generic import (
    AttackWhenTokenPolicy,
    BlockingPolicy,
    HeroFirstPolicy,
    plan_blocks,
)
from lorwright.models import Action, ActionType, CardInHand, GameState, Rect, UIState, Unit


def card(index, name, cost):
    return CardInHand(index, name, cost, Rect(0, 0, 8, 8))


def state(**kwargs):
    defaults = dict(ui_state=UIState.MY_TURN_IDLE, hand_expanded=True, mana=3)
    defaults.update(kwargs)
    return GameState(**defaults)


def test_hero_first_plays_affordable_champion_only():
    policy = HeroFirstPolicy(frozenset({"吉茵珂絲"}))
    units = [Unit("", 1, 1, Rect(0, 0, 10, 10))]
    s = state(hand=[card(0, "其他牌", 1), card(1, "吉茵珂絲", 2)], my_units=units)
    assert policy.decide(s) == Action(type=ActionType.PLAY_CARD, card_index=1)
    assert policy.decide(replace(s, mana=1)) is None
    assert policy.decide(replace(s, hand_expanded=False)) is None
    assert policy.decide(replace(s, ui_state=UIState.ENEMY_TURN)) is None


def unit_at(x, y, attack, health):
    return Unit("", attack, health, Rect(x, y, 10, 10))


def test_blocking_prefers_survival_then_lowest_value_trade():
    policy = BlockingPolicy()
    blockers = [unit_at(0, 900, 2, 2), unit_at(1, 910, 1, 1)]
    attackers = [unit_at(0, 350, 3, 1)]
    s = state(
        ui_state=UIState.BLOCKING,
        my_units=blockers,
        enemy_units=attackers,
        enemy_attackers=attackers,
    )
    action = policy.decide(s)
    assert action.type is ActionType.BLOCK
    # 对面 3/1：1/1 攻 1 >= 血 1 能换掉它，穷举选 1/1（损失 2 < 4）
    assert action.raw["pairs"] == [(1, 0)]


def test_blocking_prefers_no_death_kill():
    policy = BlockingPolicy()
    blockers = [unit_at(0, 900, 3, 4)]
    attackers = [unit_at(0, 350, 2, 3)]
    s = state(
        ui_state=UIState.BLOCKING,
        my_units=blockers,
        enemy_units=attackers,
        enemy_attackers=attackers,
    )
    action = policy.decide(s)
    assert action.raw["pairs"] == [(0, 0)]


def test_blocking_skips_hopeless_and_passes():
    policy = BlockingPolicy()
    blockers = [unit_at(0, 900, 1, 1)]
    attackers = [unit_at(0, 350, 5, 5)]
    s = state(
        ui_state=UIState.BLOCKING,
        my_units=blockers,
        enemy_units=attackers,
        enemy_attackers=attackers,
    )
    assert policy.decide(s).type is ActionType.CONFIRM


def test_plan_blocks_covers_multiple_attackers():
    blockers = [unit_at(0, 900, 3, 3), unit_at(1, 910, 2, 2)]
    attackers = [unit_at(0, 350, 2, 2), unit_at(1, 360, 2, 2)]
    pairs = plan_blocks(blockers, attackers)
    # 两个 2/2 攻击者：3/3 无死换一个，2/2 互换另一个
    assert len(pairs) == 2


def test_blocking_confirms_once_declared():
    policy = BlockingPolicy()
    blockers = [unit_at(0, 900, 2, 2)]
    attackers = [unit_at(0, 350, 3, 1)]
    s = state(
        ui_state=UIState.BLOCKING,
        my_units=blockers,
        enemy_units=attackers,
        enemy_attackers=attackers,
    )
    first = policy.decide(s)
    assert first.type is ActionType.BLOCK
    assert policy.decide(s) == Action(type=ActionType.CONFIRM)
    policy.decide(state())
    assert policy.decide(s).type is ActionType.BLOCK


def unit(y):
    return Unit("", 1, 1, Rect(0, y, 10, 10))


def test_attack_declares_all_then_confirms():
    policy = AttackWhenTokenPolicy()
    bench = state(my_units=[unit(930), unit(940)], has_attack_token=True)
    assert policy.decide(bench) == Action(
        type=ActionType.ATTACK, raw={"attackers": (0, 1)}
    )
    declared = state(my_units=[unit(700), unit(940)], has_attack_token=True)
    assert policy.decide(declared) == Action(type=ActionType.CONFIRM)
    no_token = state(my_units=[unit(930)], has_attack_token=False)
    assert policy.decide(no_token) is None
    assert policy.decide(state(my_units=[], has_attack_token=True)) is None



def test_blocking_respects_fearsome_threshold():
    # 恐惧攻击者：攻击力 ≤3 的单位挡不住（原生规则组件验证，门槛=3）。
    # 4/1 才能互换 4/3 恐惧单位（损失 5 < 挨 4 点脸折 8）；1/1 不许挡。
    policy = BlockingPolicy()
    blockers = [unit_at(0, 900, 1, 1), unit_at(1, 910, 4, 1)]
    attackers = [Unit("", 4, 3, Rect(0, 350, 10, 10), keywords=frozenset({"Fearsome"}))]
    s = state(
        ui_state=UIState.BLOCKING,
        my_units=blockers,
        enemy_units=attackers,
        enemy_attackers=attackers,
    )
    action = policy.decide(s)
    assert action.type is ActionType.BLOCK
    assert action.raw["pairs"] == [(1, 0)]


def test_fearsome_leaves_no_eligible_blocker_passes():
    # 全员攻击力 ≤3：恐惧攻击者无人能挡 → 无指派 → 直接确认
    policy = BlockingPolicy()
    blockers = [unit_at(0, 900, 3, 3), unit_at(1, 910, 2, 2)]
    attackers = [Unit("", 5, 5, Rect(0, 350, 10, 10), keywords=frozenset({"Fearsome"}))]
    s = state(
        ui_state=UIState.BLOCKING,
        my_units=blockers,
        enemy_units=attackers,
        enemy_attackers=attackers,
    )
    action = policy.decide(s)
    assert action.type is ActionType.CONFIRM


def test_exhaustive_path_skips_stunned_blockers():
    # 击晕单位不能格挡（StatePreventsBlock）：大价值击晕单位不许被指派
    policy = BlockingPolicy()
    stunned_big = Unit("", 5, 5, Rect(0, 900, 10, 10), stunned=True)
    blockers = [stunned_big, unit_at(1, 910, 2, 2)]
    attackers = [unit_at(0, 350, 3, 2)]
    s = state(
        ui_state=UIState.BLOCKING,
        my_units=blockers,
        enemy_units=attackers,
        enemy_attackers=attackers,
    )
    action = policy.decide(s)
    assert action.type is ActionType.BLOCK
    assert action.raw["pairs"] == [(1, 0)]


def test_immobile_keyword_blocker_ineligible():
    # Immobile 关键词同样禁止格挡（StatePreventsBlock 组件）
    policy = BlockingPolicy()
    immobile = Unit("", 5, 5, Rect(0, 900, 10, 10), keywords=frozenset({"Immobile"}))
    blockers = [immobile, unit_at(1, 910, 2, 2)]
    attackers = [unit_at(0, 350, 3, 2)]
    s = state(
        ui_state=UIState.BLOCKING,
        my_units=blockers,
        enemy_units=attackers,
        enemy_attackers=attackers,
    )
    action = policy.decide(s)
    assert action.raw["pairs"] == [(1, 0)]


def test_fearsome_unknown_attack_still_blocks():
    # blocker 攻击力未识别（-1）时按「能挡就挡」处理（用户规则 1）
    policy = BlockingPolicy()
    blockers = [unit_at(0, 900, -1, 3)]
    attackers = [Unit("", 2, 3, Rect(0, 350, 10, 10), keywords=frozenset({"Fearsome"}))]
    s = state(
        ui_state=UIState.BLOCKING,
        my_units=blockers,
        enemy_units=attackers,
        enemy_attackers=attackers,
    )
    action = policy.decide(s)
    assert action.type is ActionType.BLOCK


def test_greedy_fallback_respects_fearsome():
    # 超限走贪心时恐惧资格同样生效：1/1 永远不被指派给恐惧攻击者
    blockers = [unit_at(i, 900, 1, 1) for i in range(9)]
    attackers = [
        Unit("", 3, 3, Rect(i * 10, 350, 10, 10), keywords=frozenset({"Fearsome"}))
        for i in range(8)
    ]
    pairs = plan_blocks(blockers, attackers)
    assert pairs == []  # 全是 1/1，没人能挡恐惧
