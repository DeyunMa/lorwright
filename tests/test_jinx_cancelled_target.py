from dataclasses import replace

from lorwright.core.champions.jinx.policy import JinxOpeningPolicy
from lorwright.core.decide.generic import AttackWhenTokenPolicy
from lorwright.core.decide.router import Router
from lorwright.core.models import (
    ActionType,
    CardInHand,
    GameState,
    Reading,
    Rect,
    TargetedSpell,
    UIState,
    Unit,
)


def test_cancelled_pow_pow_yields_until_new_turn_evidence():
    policy = JinxOpeningPolicy(jinx_summoned=True)
    before = GameState(
        ui_state=UIState.MY_TURN_IDLE, hand_expanded=True, mana=3,
        hand=[CardInHand(0, "砰砰", 1, Rect(500, 880, 8, 8))],
        enemy_units=[Unit("", 5, 3, Rect(880, 180, 60, 60))],
        my_units=[Unit("", 8, 9, Rect(850, 900, 60, 60))],
        has_attack_token=True, readings={"mana": Reading(3, 0)},
    )
    assert policy.decide(before).type is ActionType.PLAY_CARD
    targeting = replace(before, ui_state=UIState.TARGETING, enemy_units=[],
                        targeted_spell=TargetedSpell("砰砰", Rect(900, 400, 50, 50)))
    cancel = policy.decide(targeting)
    assert cancel.type is ActionType.CANCEL
    policy.on_action_outcome(cancel, targeting, before)
    # 同一场面漏检后恢复一个单位，不足以重试同一法术。
    assert policy.decide(before) is None
    assert Router([policy, AttackWhenTokenPolicy()]).decide(before).action.type is ActionType.ATTACK
    assert policy.decide(replace(before, mana=4, readings={"mana": Reading(4, 1)})) is None
    assert policy.decide(replace(before, mana=4, readings={"mana": Reading(4, 0)})).type is ActionType.PLAY_CARD


def test_cancelled_pow_pow_can_retry_after_observed_opponent_priority():
    policy = JinxOpeningPolicy(jinx_summoned=True)
    target = GameState(ui_state=UIState.TARGETING, mana=3,
                       targeted_spell=TargetedSpell("砰砰", Rect(900, 400, 50, 50)),
                       readings={"mana": Reading(3, 0)})
    cancel = policy.decide(target)
    idle = replace(target, ui_state=UIState.MY_TURN_IDLE, targeted_spell=None,
                   hand_expanded=True, hand=[CardInHand(0, "砰砰", 1, Rect(500, 880, 8, 8))],
                   enemy_units=[Unit("", 5, 3, Rect(880, 180, 60, 60))])
    policy.on_action_outcome(cancel, target, idle)
    assert policy.decide(idle) is None
    policy.decide(replace(idle, ui_state=UIState.ENEMY_TURN))
    assert policy.decide(idle).type is ActionType.PLAY_CARD
