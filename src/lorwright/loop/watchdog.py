"""卡死检测：连续 N 次动作后状态无变化 → 判定卡住。

`NO_OP` 不算动作。没有动作时状态本来就不会变，把它计入卡死会在对手回合
每 N 帧刷一次快照并触发恢复流程（`docs/handoff.md` §4.4）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lorwright.models import ActionType, GameState


@dataclass
class Watchdog:
    threshold: int = 3
    _last_sig: str = ""
    _repeat: int = 0
    _history: list[str] = field(default_factory=list)
    _progressed: bool = field(default=False, init=False)

    @property
    def progressed(self) -> bool:
        """上一次 `observe` 是否看到状态变化（用于复位恢复策略）。"""
        return self._progressed

    def observe(self, state: GameState, action: ActionType | None = None) -> bool:
        """返回 True 表示检测到卡住。

        `action` 是本帧要执行的动作。传 `NO_OP` 表示什么都没做，
        这种情况不计数——否则「对手回合」会被误判成卡死。
        """
        sig = state.summary()
        self._history.append(sig)

        if action is ActionType.NO_OP:
            # 没有动作 → 不更新基线，也不计数。
            self._progressed = False
            return False

        self._progressed = sig != self._last_sig
        if self._progressed:
            self._repeat = 0
            self._last_sig = sig
        else:
            self._repeat += 1
        return self._repeat >= self.threshold

    def reset(self) -> None:
        """重新开一个观察窗口：清计数，但保留基线。

        保留基线很重要——否则 reset 后的第一帧永远算「有变化」，
        恢复策略会被误清零，卡死后无法升级到重启。
        """
        self._repeat = 0
        self._progressed = False
