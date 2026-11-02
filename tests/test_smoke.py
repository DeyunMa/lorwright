"""冒烟测试：不依赖游戏，只验证核心逻辑。"""

from lorwright.decide.rules import SpiderAggroPolicy
from lorwright.models import ActionType, CardInHand, GameState, Rect, UIState, Unit


def _card(idx: int, cost: int) -> CardInHand:
    return CardInHand(index=idx, name=f"c{idx}", cost=cost, rect=Rect(0, 0, 10, 10))


def test_import() -> None:
    import lorwright

    assert lorwright.__version__


def test_lethal_attack() -> None:
    policy = SpiderAggroPolicy()
    state = GameState(
        ui_state=UIState.MY_TURN_IDLE,
        enemy_nexus_hp=5,
        my_units=[Unit("spider", attack=6, health=2, rect=Rect(0, 0, 1, 1))],
    )
    action = policy.decide(state)
    assert action is not None
    assert action.type is ActionType.ATTACK


def test_play_cheapest_card() -> None:
    policy = SpiderAggroPolicy()
    state = GameState(
        ui_state=UIState.MY_TURN_IDLE,
        mana=3,
        hand=[_card(0, 3), _card(1, 1), _card(2, 2)],
    )
    action = policy.decide(state)
    assert action is not None
    assert action.type is ActionType.PLAY_CARD
    assert action.card_index == 1


def test_end_turn_when_empty_hand() -> None:
    policy = SpiderAggroPolicy()
    state = GameState(ui_state=UIState.MY_TURN_IDLE, hand=[])
    action = policy.decide(state)
    assert action is not None
    assert action.type is ActionType.END_TURN


def test_abstain_when_not_my_turn() -> None:
    policy = SpiderAggroPolicy()
    state = GameState(ui_state=UIState.ENEMY_TURN, hand=[_card(0, 1)], mana=5)
    assert policy.decide(state) is None
