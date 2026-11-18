"""冒烟测试：不依赖游戏，只验证核心逻辑不会崩。"""

import pytest

from lorwright.core.champions import load
from lorwright.core.models import CardInHand, GameState, Rect, UIState, Unit


def _card(idx: int, cost: int) -> CardInHand:
    return CardInHand(index=idx, name=f"c{idx}", cost=cost, rect=Rect(0, 0, 10, 10))


def test_import() -> None:
    import lorwright

    assert lorwright.__version__


@pytest.mark.parametrize("ui_state", list(UIState))
def test_default_policy_yields_to_shared_interactions(ui_state: UIState) -> None:
    """格挡、弃牌及可选选牌由共享流程处理。"""
    state = GameState(
        ui_state=ui_state,
        mana=3,
        hand=[_card(0, 1), _card(1, 2)],
        my_units=[Unit("spider", attack=2, health=2, rect=Rect(0, 0, 1, 1))],
        has_attack_token=True,
    )
    action = load().make_policy().decide(state)
    if ui_state in (UIState.BLOCKING, UIState.DISCARD, UIState.OPTIONAL_CHOICE):
        assert action is None
    else:
        assert action is not None
