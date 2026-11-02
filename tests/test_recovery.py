"""分级恢复：重试 → 重开对局 → 重启客户端 → 停止。"""

from lorwright.loop.recovery import RecoveryAction, RecoveryPolicy


def test_escalation_order() -> None:
    p = RecoveryPolicy(retry_limit=1, battle_limit=2, client_limit=2)
    seq = [p.next_action() for _ in range(6)]
    assert seq == [
        RecoveryAction.RETRY,
        RecoveryAction.RESTART_BATTLE,
        RecoveryAction.RESTART_BATTLE,
        RecoveryAction.RESTART_CLIENT,
        RecoveryAction.RESTART_CLIENT,
        RecoveryAction.STOP,
    ]


def test_reset_clears_counters() -> None:
    p = RecoveryPolicy()
    p.next_action()
    p.next_action()
    p.reset()
    assert p.next_action() is RecoveryAction.RETRY


def test_exhausted_flag() -> None:
    p = RecoveryPolicy(retry_limit=0, battle_limit=0, client_limit=0)
    assert p.next_action() is RecoveryAction.STOP
