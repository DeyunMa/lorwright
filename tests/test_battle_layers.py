"""对局内共用决策层的接线测试。

这组测试覆盖两个曾经会静默失效的接线点：
1. `run`/`adventure` 必须都装配 BlockingPolicy（曾出现 `PassBlockPolicy`
   这个不存在的名字，导致 `lorwright run` 在真正启动前 ImportError）；
2. 英雄包在 BLOCKING 时必须弃权，让通用格挡层接手；否则英雄包的
   简化配对会绕过恐惧/灵巧/硬派等资格规则。
"""

from __future__ import annotations

from lorwright.cli.app import _battle_layers, _jinx_policy_kwargs
from lorwright.core.champions import load
from lorwright.core.decide.router import Router
from lorwright.core.models import ActionType, CardInHand, GameState, Rect, UIState, Unit


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


def test_jinx_router_uses_cost_for_unnamed_cards():
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
    assert result.layer == "unknown_card"
    assert result.action.type is ActionType.NO_OP


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


def test_unknown_card_does_not_override_jinx_rocket_opening():
    router = Router(_battle_layers(load("jinx"), policy_kwargs={"jinx_summoned": True}))
    state = GameState(
        ui_state=UIState.MY_TURN_IDLE, mana=3, hand_expanded=True,
        hand=[CardInHand(i, "", 1, Rect(i * 100, 900, 8, 8)) for i in range(5)],
    )
    result = router.decide(state)
    assert result.layer == "jinx_opening"
    assert result.action.type is ActionType.NO_OP


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
