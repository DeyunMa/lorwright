"""L1 规则层单测：纯 state → action，不依赖截图或设备。"""

from __future__ import annotations

import pytest

from lorwright.champions.elise import SpiderAggroPolicy
from lorwright.models import ActionType, CardInHand, GameState, Rect, UIState, Unit

# 单位矩形放在己方半场（y≈905）：policy 用 y<800 判断「已拖到攻击行」，
# 用 (0,0) 会被误判成已经声明过攻击
RECT = Rect(0, 900, 10, 10)


POLICY = SpiderAggroPolicy()


@pytest.fixture(autouse=True)
def _reset_policy() -> None:
    """policy 会记住「上一张没出成」，测试之间必须清空，否则互相污染。"""
    POLICY._pending_play = None
    POLICY._pending_cost = None
    POLICY._pending_hand = -1
    POLICY._unplayable.clear()
    POLICY._needs_target.clear()


def hand(index: int, name: str, cost: int) -> CardInHand:
    return CardInHand(index=index, name=name, cost=cost, rect=RECT)


def unit(name: str, attack: int, health: int, **kwargs) -> Unit:
    return Unit(name=name, attack=attack, health=health, rect=RECT, **kwargs)


def test_no_priority_returns_no_op_not_none():
    """没有优先权时答案唯一，必须返回 NO_OP。

    返回 None（弃权）会把请求送去 JEV，对手回合每一帧都白烧一次网络调用。
    """
    state = GameState(ui_state=UIState.ENEMY_TURN, hand=[hand(0, "小蜘蛛", 1)], mana=3)
    action = POLICY.decide(state)
    assert action is not None
    assert action.type is ActionType.NO_OP


def test_unknown_state_returns_no_op():
    """状态不明时绝不点击 —— 2026-11-02 盲点进设定菜单的教训。"""
    action = POLICY.decide(GameState(ui_state=UIState.UNKNOWN))
    assert action is not None
    assert action.type is ActionType.NO_OP


def test_plays_cheapest_when_only_one_playable():
    state = GameState(
        ui_state=UIState.MY_TURN_IDLE,
        mana=3,
        hand=[hand(0, "群蛛之主", 5), hand(1, "小蜘蛛", 1)],
    )
    action = POLICY.decide(state)
    assert action is not None
    assert action.type is ActionType.PLAY_CARD
    assert action.card_index == 1


def test_plays_plain_unit_before_summon_buff():
    """先铺场再召唤群蛛之主 —— 它的 buff 只覆盖召唤那一刻已在场的蜘蛛。"""
    state = GameState(
        ui_state=UIState.MY_TURN_IDLE,
        mana=10,
        hand=[hand(0, "蜘蛛哨兵", 3), hand(1, "群蛛之主", 5)],
        my_units=[unit("小蜘蛛", 1, 1), unit("小蜘蛛", 1, 1)],
        enemy_units=[unit("大块头", 10, 10)],
    )
    action = POLICY.decide(state)
    assert action is not None
    assert action.card_index == 0  # 蜘蛛哨兵


def test_attacks_when_board_is_empty_and_worth_it():
    state = GameState(
        ui_state=UIState.MY_TURN_IDLE,
        my_units=[unit("小蜘蛛", 2, 2)],
        enemy_units=[],
        has_attack_token=True,
    )
    action = POLICY.decide(state)
    assert action is not None
    assert action.type is ActionType.ATTACK
    assert action.raw["nexus_damage"] == 2


def test_does_not_attack_into_a_bad_trade():
    """拿 1/1 去喂 5/5 是白送，求解器应该拒绝。"""
    state = GameState(
        ui_state=UIState.MY_TURN_IDLE,
        my_units=[unit("小蜘蛛", 1, 1)],
        enemy_units=[unit("大块头", 5, 5)],
        has_attack_token=True,
    )
    action = POLICY.decide(state)
    assert action is not None
    assert action.type is ActionType.END_TURN


def test_attacks_with_challenger_when_elise_is_leveled():
    """伊莉丝升级后全体挑战者：可以挑软的打，不该被 5/5 换掉。"""
    state = GameState(
        ui_state=UIState.MY_TURN_IDLE,
        my_units=[unit("尖嘯蜘蛛", 4, 4)],
        enemy_units=[unit("小兵", 1, 1), unit("大块头", 5, 5)],
        has_attack_token=True,
        my_units_have_challenger=True,
    )
    action = POLICY.decide(state)
    assert action is not None
    assert action.type is ActionType.ATTACK


def test_ends_turn_when_nothing_playable_and_no_token():
    state = GameState(
        ui_state=UIState.MY_TURN_IDLE,
        mana=1,
        hand=[hand(0, "群蛛之主", 5)],
        my_units=[unit("小蜘蛛", 1, 1)],
        has_attack_token=False,
    )
    action = POLICY.decide(state)
    assert action is not None
    assert action.type is ActionType.END_TURN


def test_lethal_attack_is_taken():
    state = GameState(
        ui_state=UIState.MY_TURN_IDLE,
        my_units=[unit("尖嘯蜘蛛", 3, 4), unit("群蛛之主", 4, 3)],
        enemy_units=[],
        enemy_nexus_hp=7,
        has_attack_token=True,
    )
    action = POLICY.decide(state)
    assert action is not None
    assert action.type is ActionType.ATTACK
    assert action.raw["nexus_damage"] >= 7
    assert action.raw["attackers"] == [0, 1]


def test_unplayable_card_is_skipped_on_retry() -> None:
    """拖不动的牌不能每 tick 重试：手牌没减少就换下一张。

    实机场景：伊莉絲上场后英雄牌变成英雄法术，要求「本回合有友方单位阵亡」，
    不满足时卡片根本拖不动，旧逻辑会一直重试同一张卡 10 个 tick。
    """
    policy = SpiderAggroPolicy()
    hand = [
        CardInHand(index=0, name="", cost=1, rect=RECT),
        CardInHand(index=1, name="", cost=3, rect=RECT),
    ]
    state = GameState(ui_state=UIState.MY_TURN_IDLE, mana=3, max_mana=3, hand=hand)

    first = policy.decide(state)
    assert first is not None and first.type is ActionType.PLAY_CARD
    # 手牌没变 = 上一张没出成 → 必须换一张，而不是重试
    second = policy.decide(state)
    assert second is not None and second.type is ActionType.PLAY_CARD
    assert second.card_index != first.card_index


def test_all_cards_unplayable_falls_through_to_end_turn() -> None:
    """全都拖不动时不能死循环，要落到结束回合。"""
    policy = SpiderAggroPolicy()
    hand = [CardInHand(index=0, name="", cost=1, rect=RECT)]
    state = GameState(ui_state=UIState.MY_TURN_IDLE, mana=3, max_mana=3, hand=hand)

    assert policy.decide(state).type is ActionType.PLAY_CARD
    assert policy.decide(state).type is ActionType.END_TURN


def test_targeting_state_cancels_instead_of_playing() -> None:
    """「選擇目標」时拖手牌没反应，必须先取消，不能继续出牌。

    实机场景：0 费冥血戰要求「擊殺1個友軍單位」，拖出去后进入选目标，
    旧逻辑当成 unknown → no_op，卡到引擎停。
    """
    state = GameState(
        ui_state=UIState.TARGETING,
        mana=6,
        max_mana=6,
        hand=[CardInHand(index=0, name="", cost=0, rect=RECT)],
    )
    action = POLICY.decide(state)
    assert action is not None
    assert action.type is ActionType.CANCEL


def test_card_that_opens_targeting_is_marked_unplayable() -> None:
    """取消后手牌没减少 → 那张牌记成不可用，下次换别的。"""
    policy = SpiderAggroPolicy()
    hand = [
        CardInHand(index=0, name="", cost=0, rect=RECT),
        CardInHand(index=1, name="", cost=3, rect=RECT),
    ]
    state = GameState(ui_state=UIState.MY_TURN_IDLE, mana=6, max_mana=6, hand=hand)
    first = policy.decide(state)
    assert first is not None and first.type is ActionType.PLAY_CARD

    # 取消回来，手牌一张没少
    policy.decide(GameState(ui_state=UIState.TARGETING, mana=6, max_mana=6, hand=hand))
    second = policy.decide(state)
    assert second is not None and second.type is ActionType.PLAY_CARD
    assert second.card_index != first.card_index


def test_needs_target_survives_hand_size_change() -> None:
    """「需要选目标」是牌本身的性质，手牌数量变了也不能忘。

    实机死循环：取消选目标后手牌从展开态 7 张收回扇形 6 张，数量一变就清空
    了失败记忆，于是又去试同一张 0 费牌，取消 → 重试 → 取消，无限转。
    """
    policy = SpiderAggroPolicy()
    hand = [
        CardInHand(index=0, name="", cost=0, rect=RECT),
        CardInHand(index=1, name="", cost=3, rect=RECT),
    ]
    state = GameState(ui_state=UIState.MY_TURN_IDLE, mana=6, max_mana=6, hand=hand)
    assert policy.decide(state).type is ActionType.PLAY_CARD
    policy.decide(GameState(ui_state=UIState.TARGETING, mana=6, max_mana=6, hand=hand))

    # 取消后手牌收起，少了一张（展开态平铺 7 张、收起态只露 6 张）
    shorter = GameState(
        ui_state=UIState.MY_TURN_IDLE,
        mana=6,
        max_mana=6,
        hand=[CardInHand(index=0, name="", cost=0, rect=RECT)],
    )
    assert policy.decide(shorter).type is ActionType.END_TURN


def test_combat_resolving_confirms() -> None:
    """「結算」按钮答案唯一：点一下就往下走。

    不处理会一直 no_op —— 实机在战斗结算界面卡了 13 个 tick，
    引擎按「状态不明不点击」空转，看起来像卡死。
    """
    action = POLICY.decide(GameState(ui_state=UIState.COMBAT_RESOLVING))
    assert action is not None
    assert action.type is ActionType.CONFIRM


def test_mulligan_confirms_without_swapping() -> None:
    """起手直接「確定」：蜘蛛快攻的起手都是低费单位，换牌收益不如赶紧开局。"""
    action = POLICY.decide(GameState(ui_state=UIState.MULLIGAN))
    assert action is not None
    assert action.type is ActionType.CONFIRM


def test_tellstones_rank_last_behind_units() -> None:
    """泰爾石要排在有身材的牌后面。

    实机连出两轮 0 费泰爾石、一个单位都没铺上去，就是因为它的评分
    （bonus 3.0、费用按 1 算）高于 1 费小蜘蛛。用户明确要求不要默认打它。
    """
    from lorwright.champions.elise.deck import lookup
    from lorwright.champions.elise.policy import score

    tellstones = lookup("闇影島泰爾石")
    spiderling = lookup("小蜘蛛")
    assert tellstones is not None and spiderling is not None
    kwargs = {"spiders_on_board": 0, "enemy_max_attack": 0}
    assert score(tellstones, **kwargs) < score(spiderling, **kwargs)
