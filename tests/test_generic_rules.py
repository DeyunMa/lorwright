from dataclasses import replace

from lorwright.core.champions import load
from lorwright.core.champions.elise import SpiderAggroPolicy
from lorwright.core.decide.generic import (
    AttackWhenTokenPolicy,
    BlockingPolicy,
    ExpandHandPolicy,
    HeroFirstPolicy,
    PlayUnitPolicy,
    TargetingPolicy,
    UnknownCardPolicy,
    plan_blocks,
)
from lorwright.core.decide.router import Router
from lorwright.core.models import Action, ActionType, CardInHand, GameState, Rect, UIState, Unit


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
    assert policy.decide(s) == Action(
        type=ActionType.PLAY_CARD, card_index=1, raw={"unit_card": True}
    )
    assert policy.decide(replace(s, mana=1)) is None
    assert policy.decide(replace(s, hand_expanded=False)) is None
    assert policy.decide(replace(s, ui_state=UIState.ENEMY_TURN)) is None


def test_hero_first_skips_unusable_candidates():
    policy = HeroFirstPolicy(frozenset({"吉茵珂絲"}))
    hero = card(0, "吉茵珂絲", 2)
    s = state(hand=[replace(hero, cost=-1), replace(hero, index=1, drag_point_valid=False),
                    replace(hero, index=2)])
    assert policy.decide(s).card_index == 2
    assert policy.decide(replace(s, hand=s.hand[:2])) is None
    assert policy.decide(replace(s, mana=-1)) is None
    assert policy.decide(replace(s, my_units=[unit_at(i, 900, 1, 1) for i in range(6)])) is None


def test_play_unit_requires_visual_evidence_for_unknown_card_and_skips_bad_drag():
    policy = PlayUnitPolicy(load("jinx").lookup)
    s = state(hand=[card(0, "", 0),
                    replace(card(1, "佐恩小乞丐", 1), drag_point_valid=False),
                    replace(card(2, "", 1), visible_playable_unit=True, drag_point_valid=False),
                    replace(card(3, "", 2), visible_playable_unit=True),
                    card(4, "汙水坑疏濬機器人", 3)])
    assert policy.decide(s).card_index == 3
    assert policy.decide(replace(s, mana=1)) is None
    assert policy.decide(replace(s, mana=-1)) is None
    assert policy.decide(replace(s, hand=[replace(s.hand[3], cost=-1)])) is None


def test_play_unit_orders_unknown_units_lowest_cost_first():
    """牌名未知但类型已确认的单位与已知名单位走同一费用优先排序。"""
    policy = PlayUnitPolicy(load("jinx").lookup)
    s = state(hand=[replace(card(0, "", 3), visible_playable_unit=True),
                    replace(card(1, "", 1), visible_playable_unit=True),
                    card(2, "佐恩小乞丐", 2)],
              mana=3)
    assert policy.decide(s) == Action(type=ActionType.PLAY_CARD, card_index=1,
                                     raw={"unit_card": True})
    assert policy.decide(replace(s, mana=0)) is None


def test_expand_hand_only_when_collapsed():
    policy = ExpandHandPolicy()
    s = state(hand=[card(0, "佐恩小乞丐", 1)], hand_expanded=False)
    assert policy.decide(s) == Action(type=ActionType.EXPAND_HAND)
    assert policy.decide(replace(s, hand_expanded=True)) is None


def test_play_unit_skips_spells_and_picks_cheapest_known_unit():
    policy = PlayUnitPolicy(load("jinx").lookup)
    s = state(
        hand=[card(0, "應急裝置", 1), card(1, "佐恩小乞丐", 1), card(2, "吉茵珂絲", 4)],
        mana=3,
    )
    assert policy.decide(s) == Action(type=ActionType.PLAY_CARD, card_index=1,
                                     raw={"unit_card": True})


def test_play_unit_stops_at_six_units():
    policy = PlayUnitPolicy(load("jinx").lookup)
    s = state(hand=[card(0, "佐恩小乞丐", 1)], my_units=[unit_at(i, 900, 1, 1) for i in range(6)])
    assert policy.decide(s) is None


def test_unknown_card_abstains_instead_of_blocking_other_actions():
    policy = UnknownCardPolicy()
    s = state(hand=[card(0, "", -1), card(1, "", 4), card(2, "", 0)])
    assert policy.decide(s) is None
    assert policy.decide(replace(s, hand_expanded=False)) is None
    assert policy.decide(replace(s, ui_state=UIState.MULLIGAN)) is None
    assert policy.decide(replace(s, hand=s.hand[:2])) is None


def test_targeting_does_not_guess_from_visible_objects():
    policy = TargetingPolicy()
    enemy = unit_at(0, 350, 1, 1)
    ally = unit_at(0, 900, 1, 1)
    for changes in (
        {"hand": [card(0, "", 1)], "enemy_units": [enemy], "my_units": [ally]},
        {"hand_expanded": False, "enemy_units": [enemy]},
        {"hand_expanded": False, "my_units": [ally]},
        {"hand_expanded": False, "enemy_nexus_hp": 20},
        {"hand_expanded": False, "enemy_nexus_hp": 0},
    ):
        assert policy.decide(state(ui_state=UIState.TARGETING, **changes)).type is ActionType.NO_OP


def test_optional_skip_target_selects_enemy_or_skips():
    policy = TargetingPolicy()
    enemy = unit_at(0, 350, 1, 1)
    pick = policy.decide(state(ui_state=UIState.TARGETING,
                               action_prompt="action_skip",
                               enemy_units=[enemy]))
    assert pick is not None and pick.type is ActionType.SELECT_TARGET
    assert pick.raw == {"enemy": True, "index": 0}
    skip = policy.decide(state(ui_state=UIState.TARGETING,
                               action_prompt="action_skip"))
    assert skip is not None and skip.type is ActionType.END_TURN
    # 必选「選擇目標」提示默认选首个跨帧稳定敌方；无敌方可选时弃权。
    pick = policy.decide(state(ui_state=UIState.TARGETING,
                               action_prompt="action_target",
                               enemy_units=[enemy]))
    assert pick is not None and pick.type is ActionType.SELECT_TARGET
    assert pick.raw == {"enemy": True, "index": 0}
    stable_pick = policy.decide(state(ui_state=UIState.TARGETING,
                                      action_prompt="action_target",
                                      enemy_units=[enemy, unit_at(0, 480, 1, 1)],
                                      enemy_units_stable=frozenset({1})))
    assert stable_pick is not None and stable_pick.raw == {"enemy": True, "index": 1}
    assert policy.decide(state(ui_state=UIState.TARGETING,
                               action_prompt="action_target")).type is ActionType.NO_OP


def test_spell_variant_options_pick_left_card():
    """实机 20261121T140928「希格斯 彈跳炸彈」二选一：固定选左。"""
    policy = TargetingPolicy()
    options = (Rect(645, 240, 280, 320), Rect(965, 240, 280, 320))
    pick = policy.decide(state(ui_state=UIState.TARGETING,
                               spell_options=options))
    assert pick is not None and pick.type is ActionType.SELECT_TARGET
    assert pick.raw == {"option": 0}


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
    monkeypatch.setattr("lorwright.core.decide.generic.MAX_ASSIGNMENT_COMBINATIONS", 0)
    blockers = [unit_at(0, 900, 1, 1), unit_at(1, 910, 1, 4)]
    attacker = replace(unit_at(0, 350, 5, 1), keywords=frozenset({"Overwhelm"}))
    assert plan_blocks(blockers, [attacker]) == [(1, 0)]
    assert plan_blocks(blockers, [replace(attacker, keywords=frozenset())]) == [(0, 0)]


def test_challenger_pulled_blocker_is_already_committed():
    """实机 20261121T071021：挑战者把 4|3 拉进格挡行锁定指派；
    再穷举会让 10|11 去挡同一攻击者，重发拖拽被对局忽略 → action_timeout。"""
    policy = BlockingPolicy()
    my_units = [
        unit_at(700, 928, 1, 1), unit_at(880, 928, 2, 2),
        unit_at(960, 718, 4, 3),   # 格挡行（拉拽锁定）
        unit_at(1060, 928, 10, 11), unit_at(1220, 928, 2, 1),
    ]
    attackers = [unit_at(928, 414, 4, 1)]
    s = state(ui_state=UIState.BLOCKING, my_units=my_units,
              enemy_units=attackers, enemy_attackers=attackers)
    assert policy.decide(s).type is ActionType.CONFIRM


def test_committed_lane_blocker_frees_only_its_attacker():
    """行内锁定指派只覆盖正对的攻击者，其余攻击者仍正常穷举。"""
    policy = BlockingPolicy()
    my_units = [
        unit_at(700, 928, 3, 3),
        unit_at(960, 718, 4, 3),   # 格挡行（锁定去挡攻击者 0）
        unit_at(1060, 928, 10, 11), unit_at(1300, 928, 2, 2),
    ]
    attackers = [unit_at(928, 414, 4, 1), unit_at(1400, 420, 3, 2)]
    s = state(ui_state=UIState.BLOCKING, my_units=my_units,
              enemy_units=attackers, enemy_attackers=attackers)
    action = policy.decide(s)
    assert action.type is ActionType.BLOCK
    assert action.raw["pairs"] == [(2, 1)]   # 10|11 无死换第二个攻击者


def test_lane_unit_without_aligned_attacker_stays_uncommitted():
    """行内单位找不到正对攻击者（识别缺口）不锁定，仍可参与规划。"""
    policy = BlockingPolicy()
    my_units = [unit_at(960, 718, 4, 3), unit_at(1300, 928, 2, 2)]
    attackers = [unit_at(400, 414, 4, 1)]   # 正对不到行内单位
    s = state(ui_state=UIState.BLOCKING, my_units=my_units,
              enemy_units=attackers, enemy_attackers=attackers)
    assert policy.decide(s).type is ActionType.BLOCK


def test_challenger_pull_real_frame_confirms():
    """实机停止帧：行内 4|3 已锁定，策略直接确认而不是重发拖拽。"""
    import cv2

    from lorwright.core.config import load_settings
    from lorwright.core.perceive.digits import DigitReader
    from lorwright.core.perceive.state import StateParser
    from lorwright.core.perceive.ui_state import UIStateDetector
    from tools.test_data import fixtures_root

    settings = load_settings()
    layout = settings.layout.to_layout()
    parser = StateParser(
        layout,
        UIStateDetector(threshold=settings.perception.match_threshold,
                        action_button=layout.end_turn),
        DigitReader(), threshold=settings.perception.match_threshold,
    )
    parser.load()
    image = cv2.imread(str(fixtures_root()
                           / "screens/f1-blocking-challenger-pull-20261121.png"))
    assert image is not None
    parsed = parser.parse(image)
    assert parsed.ui_state is UIState.BLOCKING
    assert parsed.my_units[2].rect.center[1] < 850   # 行内单位实检
    assert BlockingPolicy().decide(parsed).type is ActionType.CONFIRM


def test_blocking_candidate_does_not_advance_before_success():
    policy = BlockingPolicy()
    attackers = [unit_at(0, 350, 3, 1)]
    s = state(
        ui_state=UIState.BLOCKING,
        my_units=[unit_at(0, 900, 2, 2)],
        enemy_units=attackers,
        enemy_attackers=attackers,
    )
    first = policy.decide(s)
    assert first.type is ActionType.BLOCK
    assert policy.decide(s) == first
    assert policy.decide(replace(s)) == first


def test_unrelated_success_does_not_declare_blocking():
    policy = BlockingPolicy()
    attackers = [unit_at(0, 350, 3, 1)]
    s = state(
        ui_state=UIState.BLOCKING,
        my_units=[unit_at(0, 900, 2, 2)],
        enemy_units=attackers,
        enemy_attackers=attackers,
    )
    candidate = policy.decide(s)
    policy.on_action_outcome(Action(ActionType.CONFIRM), s, s)
    assert policy.decide(s) == candidate
    policy.on_action_outcome(candidate, state(), s)
    assert policy.decide(s) == candidate
    policy.on_action_outcome(candidate, s, state())
    assert policy.decide(s) == candidate


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
    # 声明落地（格挡者上移到格挡行）→ 置位，下一决策确认。
    landed = replace(s, my_units=[unit_at(0, 550, 2, 2)])
    policy.on_action_outcome(first, s, landed)
    assert policy.decide(landed) == Action(type=ActionType.CONFIRM)
    policy.decide(state())
    assert policy.decide(s).type is ActionType.BLOCK


def test_blocking_replans_when_declaration_never_landed():
    """实机 20261121T143406：格挡拖拽被吞单位停备战行；
    声明未落地时直接 CONFIRM 会点「略過格擋」，必须重规划。"""
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
    # 后态单位仍在备战行 → 不置位，重路由时重新规划重拖。
    policy.on_action_outcome(first, s, s)
    assert policy.decide(s) == first


def test_blocking_starts_new_declaration_after_confirmed_round_through_router():
    policy = BlockingPolicy()
    router = Router([SpiderAggroPolicy(), policy])
    attackers = [unit_at(0, 350, 3, 1)]
    blocking = state(
        ui_state=UIState.BLOCKING,
        my_units=[unit_at(0, 900, 2, 2)],
        enemy_units=attackers,
        enemy_attackers=attackers,
    )
    first = router.decide(blocking).action
    assert first.type is ActionType.BLOCK
    # 声明落地的后态才置位；未落地时重决策仍重规划。
    landed = replace(blocking, my_units=[unit_at(0, 550, 2, 2)])
    policy.on_action_outcome(first, blocking, landed)
    confirm = router.decide(landed).action
    assert confirm.type is ActionType.CONFIRM
    # 后继状态均被英雄层接管，Blocking.decide 没有机会观察离开格挡。
    enemy_turn = state(ui_state=UIState.ENEMY_TURN)
    policy.on_action_outcome(confirm, blocking, enemy_turn)
    assert router.decide(enemy_turn).layer == "elise_spider_aggro"
    assert router.decide(state()).layer == "elise_spider_aggro"
    assert router.decide(blocking).action == first


def unit(y):
    return Unit("", 1, 1, Rect(0, y, 10, 10))


def test_attack_only_declares_eligible_units_and_abstains_without_them():
    policy = AttackWhenTokenPolicy()
    unavailable = replace(unit(930), can_attack=False)
    s = state(my_units=[unavailable, unit(940), unavailable], has_attack_token=True)
    assert policy.decide(s) == Action(ActionType.ATTACK, raw={"attackers": (1,)})
    assert policy.decide(replace(s, my_units=[unavailable, unavailable])) is None
    # 已进入攻击行仍应确认，不能把确认动作当作新的攻击声明过滤掉。
    declared = replace(s, my_units=[replace(unavailable, rect=Rect(0, 700, 10, 10))])
    assert policy.decide(declared) == Action(ActionType.CONFIRM)


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
