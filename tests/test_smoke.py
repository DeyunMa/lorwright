"""冒烟测试：不依赖游戏，只验证核心逻辑不会崩。"""

import pytest

from lorwright.champions import load
from lorwright.models import CardInHand, GameState, Rect, UIState, Unit


def _card(idx: int, cost: int) -> CardInHand:
    return CardInHand(index=idx, name=f"c{idx}", cost=cost, rect=Rect(0, 0, 10, 10))


def test_import() -> None:
    import lorwright

    assert lorwright.__version__


@pytest.mark.parametrize("ui_state", list(UIState))
def test_policy_never_crashes_and_never_returns_none(ui_state: UIState) -> None:
    """任何界面状态下都必须返回一个动作 —— None（弃权）会让路由白跑一层 JEV。"""
    state = GameState(
        ui_state=ui_state,
        mana=3,
        hand=[_card(0, 1), _card(1, 2)],
        my_units=[Unit("spider", attack=2, health=2, rect=Rect(0, 0, 1, 1))],
        has_attack_token=True,
    )
    action = load().make_policy().decide(state)
    assert action is not None
