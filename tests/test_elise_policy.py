"""L1 规则层单测：纯 state → action，不依赖截图或设备。"""

from __future__ import annotations

from lorwright.champions.elise import SpiderAggroPolicy
from lorwright.models import ActionType, CardInHand, GameState, Rect, UIState, Unit

RECT = Rect(0, 0, 10, 10)
POLICY = SpiderAggroPolicy()


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


def test_plays_buff_before_plain_unit():
    state = GameState(
        ui_state=UIState.MY_TURN_IDLE,
        mana=10,
        hand=[hand(0, "蜘蛛哨兵", 3), hand(1, "群蛛之主", 5)],
        my_units=[unit("小蜘蛛", 1, 1), unit("小蜘蛛", 1, 1)],
        enemy_units=[unit("大块头", 10, 10)],
    )
    action = POLICY.decide(state)
    assert action is not None
    assert action.card_index == 1  # 群蛛之主


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
