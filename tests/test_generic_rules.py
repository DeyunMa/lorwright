from dataclasses import replace

from lorwright.champions import load
from lorwright.decide.generic import (
    AttackWhenTokenPolicy,
    BlockingPolicy,
    ExpandHandPolicy,
    HeroFirstPolicy,
    PlayUnitPolicy,
    TargetingPolicy,
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


def test_expand_hand_only_when_collapsed():
    policy = ExpandHandPolicy()
    s = state(hand=[card(0, "佐恩小乞丐", 1)], hand_expanded=False)
    assert policy.decide(s) == Action(type=ActionType.PLAY_CARD, card_index=0)
    assert policy.decide(replace(s, hand_expanded=True)) is None


def test_play_unit_skips_spells_and_picks_cheapest_known_unit():
    policy = PlayUnitPolicy(load("jinx").lookup)
    s = state(
        hand=[card(0, "應急裝置", 1), card(1, "佐恩小乞丐", 1), card(2, "吉茵珂絲", 4)],
        mana=3,
    )
    assert policy.decide(s) == Action(type=ActionType.PLAY_CARD, card_index=1)


def test_play_unit_stops_at_six_units():
    policy = PlayUnitPolicy(load("jinx").lookup)
    s = state(hand=[card(0, "佐恩小乞丐", 1)], my_units=[unit_at(i, 900, 1, 1) for i in range(6)])
    assert policy.decide(s) is None


def test_targeting_hand_then_enemy_then_ally_then_nexus_then_cancel():
    policy = TargetingPolicy()
    enemy = unit_at(0, 350, 1, 1)
    ally = unit_at(0, 900, 1, 1)
    # 弃牌提示：手牌展开时先点手牌。
    with_hand = state(
        ui_state=UIState.TARGETING, hand=[card(0, "砰砰", 1)],
        enemy_units=[enemy], my_units=[ally],
    )
    assert policy.decide(with_hand) == Action(
        type=ActionType.SELECT_TARGET, raw={"hand": True, "index": 0}
    )
    # 单位目标：手牌收起时先敌方，再我方。
    with_enemy = state(
        ui_state=UIState.TARGETING, hand_expanded=False,
        enemy_units=[enemy], my_units=[ally],
    )
    assert policy.decide(with_enemy) == Action(
        type=ActionType.SELECT_TARGET, raw={"enemy": True, "index": 0}
    )
    ally_only = state(
        ui_state=UIState.TARGETING, hand_expanded=False, my_units=[ally],
    )
    assert policy.decide(ally_only) == Action(
        type=ActionType.SELECT_TARGET, raw={"enemy": False, "index": 0}
    )
    # 没有单位时，法术可以指向敌方水晶。
    nexus_only = state(ui_state=UIState.TARGETING, hand_expanded=False)
    assert policy.decide(nexus_only) == Action(
        type=ActionType.SELECT_TARGET, raw={"nexus": True}
    )
    no_target = state(
        ui_state=UIState.TARGETING, hand_expanded=False, enemy_nexus_hp=0,
    )
    assert policy.decide(no_target).type is ActionType.CANCEL


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


def test_overwhelm_blocking_accounts_for_damage_to_nexus():
    blockers = [unit_at(0, 900, 1, 1), unit_at(1, 910, 1, 4)]
    attacker = unit_at(0, 350, 5, 1)
    overwhelm = replace(attacker, keywords=frozenset({"Overwhelm"}))
    # 两个都能换掉攻击者，但 1/4 只让 1 点伤害溢出，1/1 则溢出 4 点。
    assert plan_blocks(blockers, [overwhelm]) == [(1, 0)]
    # 没有蛮力时没有溢出，按既有规则用更便宜的 1/1。
    assert plan_blocks(blockers, [attacker]) == [(0, 0)]


def test_overwhelm_greedy_fallback_accounts_for_damage_to_nexus(monkeypatch):
    monkeypatch.setattr("lorwright.decide.generic.MAX_ASSIGNMENT_COMBINATIONS", 0)
    blockers = [unit_at(0, 900, 1, 1), unit_at(1, 910, 1, 4)]
    attacker = replace(unit_at(0, 350, 5, 1), keywords=frozenset({"Overwhelm"}))
    assert plan_blocks(blockers, [attacker]) == [(1, 0)]
    assert plan_blocks(blockers, [replace(attacker, keywords=frozenset())]) == [(0, 0)]


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
    # 恐惧攻击者：攻击力 <3 的单位挡不住（原生规则组件验证，门槛=3）。
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


def test_fearsome_attack_three_is_eligible():
    # 原生 CanBeBlockedByCard：blocker 攻击 3 不小于门槛 3，允许格挡。
    policy = BlockingPolicy()
    blockers = [unit_at(0, 900, 3, 1)]
    attackers = [Unit("", 4, 3, Rect(0, 350, 10, 10), keywords=frozenset({"Fearsome"}))]
    s = state(
        ui_state=UIState.BLOCKING,
        my_units=blockers,
        enemy_units=attackers,
        enemy_attackers=attackers,
    )
    action = policy.decide(s)
    assert action.type is ActionType.BLOCK
    assert action.raw["pairs"] == [(0, 0)]


def test_elusive_needs_elusive_or_block_elusive():
    # 原生 NoStealthBlock：灵巧攻击者只能被灵巧或 BlockElusive 格挡。
    attacker = Unit("", 3, 2, Rect(0, 350, 10, 10), keywords=frozenset({"Elusive"}))
    plain = Unit("", 3, 3, Rect(0, 900, 10, 10))
    elusive = Unit("", 3, 3, Rect(0, 900, 10, 10), keywords=frozenset({"Elusive"}))
    block_elusive = Unit(
        "", 3, 3, Rect(0, 900, 10, 10), keywords=frozenset({"BlockElusive"})
    )
    assert plan_blocks([plain], [attacker]) == []
    assert plan_blocks([elusive], [attacker]) == [(0, 0)]
    assert plan_blocks([block_elusive], [attacker]) == [(0, 0)]


def test_brash_needs_three_health_to_block():
    # 官方关键词文本：Brash 只能被生命 >=3 的单位格挡。
    attacker = Unit("", 3, 3, Rect(0, 350, 10, 10), keywords=frozenset({"Brash"}))
    low = Unit("", 3, 2, Rect(0, 900, 10, 10))
    high = Unit("", 3, 3, Rect(0, 900, 10, 10))
    assert plan_blocks([low], [attacker]) == []
    assert plan_blocks([high], [attacker]) == [(0, 0)]


def test_fearsome_leaves_no_eligible_blocker_passes():
    # 3/3 能过恐惧门槛，但挡 5/5 必死且杀不死（白死禁止）；2/2 攻击不足。
    # 没有合法配对 → 直接确认。
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


def test_unknown_attacker_stats_still_block():
    # 感知层当前只给位置（攻击/生命 = -1）。不能因为读不出数值就整轮放行，
    # 否则真实对局里 BlockingPolicy 永远返回 CONFIRM。
    policy = BlockingPolicy()
    blockers = [unit_at(0, 900, 2, 2)]
    attackers = [Unit("", -1, -1, Rect(0, 350, 10, 10))]
    s = state(
        ui_state=UIState.BLOCKING,
        my_units=blockers,
        enemy_units=attackers,
        enemy_attackers=attackers,
    )
    action = policy.decide(s)
    assert action.type is ActionType.BLOCK
    assert action.raw["pairs"] == [(0, 0)]


def test_unknown_health_uses_greedy_without_negative_loss():
    # 只读到攻击、生命还没读到时，不能把 -1 代进阵亡价值公式。
    blockers = [unit_at(0, 900, 2, -1)]
    attackers = [unit_at(0, 350, 3, -1)]
    assert plan_blocks(blockers, attackers) == [(0, 0)]


def test_greedy_unknown_blocker_attack_still_pairs():
    # 己方攻击 -1、生命也未识别时，不能把 -1 当成“打不过”而跳过全部候选。
    blockers = [unit_at(0, 900, -1, -1)]
    attackers = [unit_at(0, 350, 3, 6)]
    assert plan_blocks(blockers, attackers) == [(0, 0)]


def test_greedy_fallback_respects_fearsome():
    # 超限走贪心时恐惧资格同样生效：1/1 永远不被指派给恐惧攻击者
    blockers = [unit_at(i, 900, 1, 1) for i in range(9)]
    attackers = [
        Unit("", 3, 3, Rect(i * 10, 350, 10, 10), keywords=frozenset({"Fearsome"}))
        for i in range(8)
    ]
    pairs = plan_blocks(blockers, attackers)
    assert pairs == []  # 全是 1/1，没人能挡恐惧
