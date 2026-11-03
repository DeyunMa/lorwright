"""卡死检测：NO_OP 不计入，只有「做了动作但画面没变」才算卡住。"""

from lorwright.loop.watchdog import Watchdog
from lorwright.models import ActionType, GameState, UIState


def _state(ui: UIState = UIState.MY_TURN_IDLE) -> GameState:
    return GameState(ui_state=ui, mana=3, max_mana=3)


def test_repeated_no_op_is_not_stuck() -> None:
    """对手回合：连续 NO_OP 时状态摘要不变，但这不是卡死。"""
    wd = Watchdog(threshold=3)
    enemy = _state(UIState.ENEMY_TURN)
    results = [wd.observe(enemy, ActionType.NO_OP) for _ in range(10)]
    assert not any(results)


def test_real_action_without_change_is_stuck() -> None:
    wd = Watchdog(threshold=3)
    state = _state()
    seen = [wd.observe(state, ActionType.END_TURN) for _ in range(4)]
    # 第 1 帧是基线（progressed），之后连续 3 帧不变 → 卡住
    assert seen[:3] == [False, False, False]
    assert seen[3] is True


def test_state_change_resets_counter() -> None:
    wd = Watchdog(threshold=2)
    a = _state()
    b = GameState(ui_state=UIState.MY_TURN_IDLE, mana=2, max_mana=3)

    assert wd.observe(a, ActionType.PLAY_CARD) is False
    assert wd.observe(a, ActionType.PLAY_CARD) is False
    assert wd.observe(b, ActionType.PLAY_CARD) is False   # 变了 → 清零
    assert wd.observe(b, ActionType.PLAY_CARD) is False
    assert wd.observe(b, ActionType.PLAY_CARD) is True


def test_no_op_keeps_baseline_for_later_action() -> None:
    """NO_OP 之后的第一帧真实动作不该立刻被判卡住。"""
    wd = Watchdog(threshold=1)
    state = _state(UIState.ENEMY_TURN)
    wd.observe(state, ActionType.NO_OP)
    assert wd.observe(state, ActionType.END_TURN) is False


def test_progressed_flag() -> None:
    wd = Watchdog(threshold=3)
    a = _state()
    b = GameState(ui_state=UIState.MY_TURN_IDLE, mana=1, max_mana=3)

    wd.observe(a, ActionType.PLAY_CARD)
    assert wd.progressed is True
    wd.observe(a, ActionType.PLAY_CARD)
    assert wd.progressed is False
    wd.observe(b, ActionType.PLAY_CARD)
    assert wd.progressed is True
    wd.observe(b, ActionType.NO_OP)
    assert wd.progressed is False


def test_reset_restarts_count_but_keeps_baseline() -> None:
    wd = Watchdog(threshold=2)
    state = _state()
    wd.observe(state, ActionType.END_TURN)
    assert wd.observe(state, ActionType.END_TURN) is False
    wd.reset()
    # 基线保留：同一个状态 reset 后不会凭空算「有变化」
    assert wd.observe(state, ActionType.END_TURN) is False
    assert wd.observe(state, ActionType.END_TURN) is True
