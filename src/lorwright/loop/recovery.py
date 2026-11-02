"""分级恢复：卡住后该做什么（issue #6 的决策逻辑）。

纯状态机，不碰鼠标键盘——具体动作由 engine 执行。

语义：按「累计尝试次数」分段，而不是每级各自计数。
这样不会出现「升级后计数器被重置 → 又回到重试」的死循环。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class RecoveryAction(StrEnum):
    RETRY = "retry"                    # 重试当前动作
    RESTART_BATTLE = "restart_battle"  # 退出对局重进
    RESTART_CLIENT = "restart_client"  # 重启游戏客户端
    STOP = "stop"                      # 停下并告警


@dataclass
class RecoveryPolicy:
    retry_limit: int = 1
    battle_limit: int = 2
    client_limit: int = 2

    _attempts: int = field(default=0, init=False)

    @property
    def total_limit(self) -> int:
        return self.retry_limit + self.battle_limit + self.client_limit

    def next_action(self) -> RecoveryAction:
        """按累计尝试次数返回下一步动作。"""
        self._attempts += 1
        n = self._attempts
        if n <= self.retry_limit:
            return RecoveryAction.RETRY
        if n <= self.retry_limit + self.battle_limit:
            return RecoveryAction.RESTART_BATTLE
        if n <= self.total_limit:
            return RecoveryAction.RESTART_CLIENT
        return RecoveryAction.STOP

    def reset(self) -> None:
        """状态恢复后清零。"""
        self._attempts = 0

    @property
    def exhausted(self) -> bool:
        return self._attempts > self.total_limit
