from lorwright.act.translate import ActionTranslator, Layout
from lorwright.models import (
    Action,
    ActionType,
    CardInHand,
    GameState,
    Rect,
    Unit,
)

LAYOUT = Layout(
    end_turn=Rect(1700, 900, 100, 60),
    enemy_nexus=Rect(900, 200, 120, 120),
    play_area=Rect(900, 500, 200, 200),
    attack_row=Rect(700, 470, 520, 70),
    hand_region=Rect(1420, 855, 500, 225),
)


def test_end_turn_click() -> None:
    t = ActionTranslator(LAYOUT)
    plan = t.translate(Action(type=ActionType.END_TURN), GameState())
    assert plan is not None
    assert plan.points == [(1750, 930)]


def test_play_card_drags_from_expanded_hand() -> None:
    """展开态卡片平铺，直接拖到场上。"""
    state = GameState(
        hand=[CardInHand(0, "蜘蛛", 1, Rect(100, 1000, 80, 120))],
        hand_expanded=True,
    )
    t = ActionTranslator(LAYOUT)
    plan = t.translate(Action(type=ActionType.PLAY_CARD, card_index=0), state)
    assert plan is not None
    assert plan.drag
    assert plan.points[0] == (140, 1060)
    assert plan.points[1] == (1000, 600)


def test_play_card_expands_collapsed_hand_first() -> None:
    """收起态拖不动（实测 hold 120/300/800ms 全部无效），必须先 tap 展开。

    展开后卡片位置全变，所以出牌拆成两帧：这一帧只展开，下一帧再拖。
    """
    state = GameState(hand=[CardInHand(0, "蜘蛛", 1, Rect(100, 1000, 80, 120))])
    t = ActionTranslator(LAYOUT)
    plan = t.translate(Action(type=ActionType.PLAY_CARD, card_index=0), state)
    assert plan is not None
    assert not plan.drag
    assert plan.points == [(1670, 967)]


def test_select_target_hand_card_uses_hand_position() -> None:
    state = GameState(
        hand=[CardInHand(0, "砰砰", 1, Rect(100, 1000, 80, 120))],
        hand_expanded=True,
    )
    plan = ActionTranslator(LAYOUT).translate(
        Action(type=ActionType.SELECT_TARGET, raw={"hand": True, "index": 0}), state
    )
    assert plan is not None
    assert plan.points == [(140, 1060)]


def test_select_target_enemy_nexus() -> None:
    plan = ActionTranslator(LAYOUT).translate(
        Action(type=ActionType.SELECT_TARGET, raw={"nexus": True}), GameState()
    )
    assert plan is not None
    assert plan.points == [(960, 260)]


def test_mulligan_replace_taps_each_replace_point() -> None:
    plan = ActionTranslator(LAYOUT).translate(
        Action(type=ActionType.MULLIGAN_REPLACE, raw={"points": [(10, 20), (30, 40)]}),
        GameState(),
    )
    assert plan is not None
    assert plan.points == [(10, 20), (30, 40)]


def test_attack_uses_first_available_unit() -> None:
    state = GameState(my_units=[Unit("s", 2, 2, Rect(400, 890, 80, 80))])
    t = ActionTranslator(LAYOUT)
    plan = t.translate(Action(type=ActionType.ATTACK, target="nexus"), state)
    assert plan is not None
    # 起点是单位卡身，落点是攻击行（分隔线上方），不是敌方水晶
    assert plan.points[0] == (440, 930)
    assert plan.points[1] == (960, 505)
    assert plan.drag


def test_block_targets_enemy_attackers_not_idle_enemies() -> None:
    decoy = Unit("decoy", 2, 2, Rect(100, 100, 80, 80))
    attacker = Unit("attacker", 2, 2, Rect(500, 300, 80, 80))
    blocker = Unit("blocker", 2, 2, Rect(700, 900, 80, 80))
    state = GameState(
        my_units=[blocker],
        enemy_units=[decoy, attacker],
        enemy_attackers=[attacker],
    )
    plan = ActionTranslator(LAYOUT).translate(
        Action(type=ActionType.BLOCK, raw={"pairs": [(0, 0)]}), state
    )
    assert plan is not None
    assert plan.points[1] == attacker.rect.center


def test_missing_layout_returns_none() -> None:
    t = ActionTranslator(Layout())
    assert t.translate(Action(type=ActionType.END_TURN), GameState()) is None
