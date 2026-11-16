"""对局内共用决策层的接线测试。

这组测试覆盖两个曾经会静默失效的接线点：
1. `run`/`adventure` 必须都装配 BlockingPolicy（曾出现 `PassBlockPolicy`
   这个不存在的名字，导致 `lorwright run` 在真正启动前 ImportError）；
2. 英雄包在 BLOCKING 时必须弃权，让通用格挡层接手；否则英雄包的
   简化配对会绕过恐惧/灵巧/硬派等资格规则。
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from lorwright.cli.app import _battle_layers, _jinx_policy_kwargs
from lorwright.core.champions import load
from lorwright.core.decide.router import Router, RouteResult
from lorwright.core.models import Action, ActionType, CardInHand, GameState, Rect, UIState, Unit


def test_battle_layers_include_blocking_policy():
    names = [layer.name for layer in _battle_layers(load("elise"))]
    assert names == [
        "elise_spider_aggro",
        "expand_hand",
        "play_unit",
        "hero_first",
        "targeting",
        "attack_when_token",
        "unknown_card",
        "combat_confirm",
        "blocking",
    ]


def test_jinx_layers_include_play_unit():
    names = [layer.name for layer in _battle_layers(load("jinx"))]
    assert names[:4] == ["jinx_opening", "expand_hand", "play_unit", "hero_first"]


def test_jinx_resume_count_reaches_router():
    pack = load("jinx")
    kwargs = _jinx_policy_kwargs(
        pack, spell_already_played=False, jinx_summoned=True, rockets_already_played=1,
    )
    router = Router(_battle_layers(pack, policy_kwargs=kwargs))
    state = GameState(
        ui_state=UIState.MY_TURN_IDLE, mana=2, hand_expanded=True,
        hand=[CardInHand(0, "超威能死亡火箭！", 1, Rect(0, 900, 8, 8))],
    )
    result = router.decide(state)
    assert result.layer == "jinx_opening"
    assert result.action.type is ActionType.PLAY_CARD
    assert result.action.raw == {"jinx_rocket": True}


def test_jinx_router_plays_cheapest_known_unit():
    router = Router(
        _battle_layers(load("jinx"), policy_kwargs={"spell_already_played": True})
    )
    state = GameState(
        ui_state=UIState.MY_TURN_IDLE,
        mana=3,
        hand_expanded=True,
        hand=[
            CardInHand(0, "應急裝置", 1, Rect(0, 900, 8, 8)),
            CardInHand(1, "佐恩小乞丐", 1, Rect(100, 900, 8, 8)),
        ],
    )
    result = router.decide(state)
    assert result.layer == "play_unit"
    assert result.action.type is ActionType.PLAY_CARD
    assert result.action.card_index == 1


def test_jinx_router_skips_unnamed_cards_without_unit_evidence():
    router = Router(_battle_layers(load("jinx")))
    state = GameState(
        ui_state=UIState.MY_TURN_IDLE, mana=3, hand_expanded=True,
        hand=[
            CardInHand(0, "", 3, Rect(0, 900, 8, 8)),
            CardInHand(1, "", 1, Rect(100, 900, 8, 8)),
            CardInHand(2, "", -1, Rect(200, 900, 8, 8)),
            CardInHand(3, "", 4, Rect(300, 900, 8, 8)),
        ],
    )
    result = router.decide(state)
    assert result.layer == "fallback"
    assert result.action.type is ActionType.END_TURN
    assert "unknown_card" in result.candidates
    assert "结束回合" in result.reason


def test_unknown_card_does_not_block_known_unit_or_attack():
    router = Router(_battle_layers(load("jinx"), policy_kwargs={
        "jinx_summoned": True, "rockets_already_played": 2,
    }))
    s = GameState(ui_state=UIState.MY_TURN_IDLE, mana=3, hand_expanded=True,
                  hand=[CardInHand(0, "", 1, Rect(0, 900, 8, 8)),
                        CardInHand(1, "汙水坑疏濬機器人", 3, Rect(100, 900, 8, 8))])
    assert router.decide(s).action.card_index == 1
    s.hand = s.hand[:1]
    s.my_units = [Unit("", 1, 1, Rect(0, 900, 10, 10))]
    s.has_attack_token = True
    assert router.decide(s).action.type is ActionType.ATTACK


def test_missing_jinx_rocket_does_not_block_fallback():
    router = Router(_battle_layers(load("jinx"), policy_kwargs={"jinx_summoned": True}))
    state = GameState(
        ui_state=UIState.MY_TURN_IDLE, mana=3, hand_expanded=True,
        hand=[CardInHand(i, "", 1, Rect(i * 100, 900, 8, 8)) for i in range(5)],
    )
    result = router.decide(state)
    assert result.layer == "fallback"
    assert result.action.type is ActionType.END_TURN


@pytest.mark.parametrize("policy_kwargs", [
    {}, {"spell_already_played": True}, {"jinx_summoned": True},
    {"jinx_summoned": True, "rockets_already_played": 2},
])
@pytest.mark.parametrize("next_action", ["unit", "visual_unit", "attack", "end_turn"])
def test_jinx_unavailable_preferences_do_not_block_other_actions(policy_kwargs, next_action):
    router = Router(_battle_layers(load("jinx"), policy_kwargs=policy_kwargs))
    hand = [CardInHand(0, "", 0, Rect(0, 900, 8, 8)),
            CardInHand(1, "應急裝置", 3, Rect(100, 900, 8, 8)),
            CardInHand(2, "吉茵珂絲", 4, Rect(200, 900, 8, 8)),
            CardInHand(3, "超威能死亡火箭！", 3, Rect(300, 900, 8, 8))]
    s = GameState(ui_state=UIState.MY_TURN_IDLE, hand_expanded=True, mana=2, hand=hand)
    if next_action in ("unit", "visual_unit"):
        s.hand.append(CardInHand(4, "佐恩小乞丐" if next_action == "unit" else "", 1,
                                 Rect(400, 900, 8, 8), visible_playable_unit=True))
        result = router.decide(s)
        assert result.layer == "play_unit"
        assert result.action.card_index == 4
    elif next_action == "attack":
        s.my_units = [Unit("", 1, 1, Rect(0, 900, 10, 10))]
        s.has_attack_token = True
        result = router.decide(s)
        assert result.action.type is ActionType.ATTACK
        assert result.layer == "attack_when_token"
    else:
        result = router.decide(s)
        assert result.action.type is ActionType.END_TURN
        assert result.layer == "fallback"
    assert result.reason


def test_jinx_unusable_rocket_does_not_preempt_known_unit():
    router = Router(_battle_layers(load("jinx"), policy_kwargs={"jinx_summoned": True}))
    rocket = CardInHand(0, "超威能死亡火箭！", 1, Rect(0, 900, 8, 8))
    s = GameState(ui_state=UIState.MY_TURN_IDLE, hand_expanded=True, mana=2,
                  hand=[rocket, CardInHand(1, "佐恩小乞丐", 1, Rect(100, 900, 8, 8))])
    for unavailable in (replace(rocket, drag_point_valid=False), replace(rocket, cost=-1)):
        assert router.decide(replace(s, hand=[unavailable, s.hand[1]])).action.card_index == 1
    result = router.decide(s)
    assert result.action.card_index == 0
    assert "火箭优先" in result.reason


@pytest.mark.parametrize("eligible", [False, True])
def test_jinx_delegated_attack_respects_unit_eligibility(eligible):
    router = Router(_battle_layers(load("jinx"), policy_kwargs={"jinx_summoned": True}))
    s = GameState(ui_state=UIState.MY_TURN_IDLE, hand_expanded=True, mana=2,
                  has_attack_token=True,
                  hand=[CardInHand(0, "", 1, Rect(0, 900, 8, 8))],
                  my_units=[Unit("", 1, 1, Rect(0, 900, 10, 10), can_attack=False),
                            Unit("", 2, 2, Rect(100, 900, 10, 10), can_attack=eligible)])
    result = router.decide(s)
    if eligible:
        assert result.action == Action(ActionType.ATTACK, raw={"attackers": (1,)})
        assert result.layer == "attack_when_token"
    else:
        assert result.action.type is ActionType.END_TURN
        assert result.layer == "fallback"


def test_board_inspection_can_finish_turn_without_reexpanding_hand():
    router = Router(_battle_layers(load("jinx"), policy_kwargs={"jinx_summoned": True}))
    s = GameState(ui_state=UIState.MY_TURN_IDLE, hand_expanded=False,
                  hand=[CardInHand(0, "", 1, Rect(0, 900, 8, 8))], mana=-1)
    result = router.decide(s, suppress_hand_expansion=True)
    assert result.action.type is ActionType.END_TURN
    assert result.layer == "fallback"
    assert "expand_hand" in result.candidates
    assert "结束回合" in result.reason


def test_jinx_pending_summon_still_stops_router_before_fallback():
    router = Router(_battle_layers(load("jinx")))
    before = GameState(ui_state=UIState.MY_TURN_IDLE, hand_expanded=True, mana=3,
                       hand=[CardInHand(0, "應急裝置", 1, Rect(0, 900, 8, 8)),
                             CardInHand(1, "吉茵珂絲", 2, Rect(100, 900, 8, 8))])
    chosen = router.decide(before)
    after = replace(before, mana=2, hand=before.hand[1:])
    router.layers[0].on_action_outcome(chosen.action, before, after)
    waiting = router.decide(after)
    assert waiting.action.type is ActionType.NO_OP
    assert waiting.candidates == ["jinx_opening"]
    assert "等待交互结果" in waiting.reason


def test_unknown_target_stops_router_with_readable_reason():
    router = Router(_battle_layers(load("jinx")))
    result = router.decide(GameState(ui_state=UIState.TARGETING))
    assert result.action.type is ActionType.NO_OP
    assert result.candidates == ["jinx_opening"]
    assert "目标类型尚未明确" in result.reason


@pytest.mark.parametrize("first_action", [None, Action(ActionType.NO_OP)])
def test_router_distinguishes_abstention_from_waiting(first_action):
    first = SimpleNamespace(name="first", decide=lambda state: first_action)
    second = SimpleNamespace(name="second", decide=lambda state: Action(ActionType.CONFIRM))
    result = Router([first, second]).decide(GameState())
    assert result.action.type is (ActionType.CONFIRM if first_action is None else ActionType.NO_OP)
    assert result.candidates == (["first", "second"] if first_action is None else ["first"])
    assert result.reason


def test_route_result_reason_preserves_constructor_and_explicit_explanations():
    action = Action(ActionType.NO_OP, raw={"reason": "等待召唤结果确认"})
    assert RouteResult(action, "synthetic", ["synthetic"]).reason == ""
    layer = SimpleNamespace(name="synthetic", decide=lambda state: action)
    result = Router([layer]).decide(GameState())
    assert result.reason == "等待召唤结果确认"
    for ui_state in (UIState.UNKNOWN, UIState.ENEMY_TURN):
        fallback = Router([]).decide(GameState(ui_state=ui_state))
        assert fallback.action.type is ActionType.NO_OP
        assert "等待" in fallback.reason


def test_elise_blocking_delegates_to_generic_policy():
    router = Router(_battle_layers(load("elise")))
    attacker = Unit("", -1, -1, Rect(0, 350, 10, 10))
    blocker = Unit("", 2, 2, Rect(0, 900, 10, 10))
    state = GameState(
        ui_state=UIState.BLOCKING,
        my_units=[blocker],
        enemy_units=[attacker],
        enemy_attackers=[attacker],
    )
    result = router.decide(state)
    assert result.layer == "blocking"
    assert result.action.type is ActionType.BLOCK
    assert result.action.raw["pairs"] == [(0, 0)]
