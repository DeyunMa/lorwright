"""卡死检测：连续 N 次动作后状态无变化 → 判定卡住。"""

from __future__ import annotations

from dataclasses import dataclass, field

from lorwright.models import GameState


@dataclass
class Watchdog:
    threshold: int = 3
    _last_sig: str = ""
    _repeat: int = 0
    _history: list[str] = field(default_factory=list)

    def observe(self, state: GameState) -> bool:
        """返回 True 表示检测到卡住。"""
        sig = state.summary()
        if sig == self._last_sig:
            self._repeat += 1
        else:
            self._repeat = 0
            self._last_sig = sig
        self._history.append(sig)
        return self._repeat >= self.threshold

    def reset(self) -> None:
        self._repeat = 0
        self._last_sig = ""
