"""分层路由测试：弃权、命中、异常、兜底。"""

from lorwright.decide.router import Router
from lorwright.models import Action, ActionType, GameState, UIState


class _Abstain:
    name = "abstain"

    def decide(self, state):
        return None


class _Play:
    name = "play"

    def decide(self, state):
        return Action(type=ActionType.PLAY_CARD, card_index=0)


class _Boom:
    name = "boom"

    def decide(self, state):
        raise RuntimeError("boom")


def test_first_non_none_wins() -> None:
    router = Router([_Abstain(), _Play()])
    r = router.decide(GameState(ui_state=UIState.MY_TURN_IDLE))
    assert r.layer == "play"
    assert r.action.type is ActionType.PLAY_CARD


def test_fallback_when_all_abstain() -> None:
    router = Router([_Abstain(), _Abstain()])
    r = router.decide(GameState(ui_state=UIState.MY_TURN_IDLE))
    assert r.layer == "fallback"
    assert r.action.type is ActionType.END_TURN


def test_exception_is_skipped() -> None:
    router = Router([_Boom(), _Play()])
    r = router.decide(GameState())
    assert r.layer == "play"


def test_coverage_counts() -> None:
    router = Router([_Abstain(), _Play()])
    router.decide(GameState())
    router.decide(GameState())
    assert router.stats["play"] == 2
    assert router.coverage()["play"] == 1.0
def test_fallback_no_op_when_unknown() -> None:
    router = Router([])
    r = router.decide(GameState(ui_state=UIState.UNKNOWN))
    assert r.action.type is ActionType.NO_OP
    assert r.layer == "fallback"


def test_fallback_no_op_when_enemy_turn() -> None:
    router = Router([])
    r = router.decide(GameState(ui_state=UIState.ENEMY_TURN))
    assert r.action.type is ActionType.NO_OP


def test_fallback_end_turn_when_my_turn() -> None:
    router = Router([])
    r = router.decide(GameState(ui_state=UIState.MY_TURN_IDLE))
    assert r.action.type is ActionType.END_TURN
