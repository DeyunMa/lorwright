"""分层路由：规则 → JEV → LLM，逐级升级。

设计要点：
  - 每层都能「弃权」（返回 None），弃权就交给下一层
  - 记录最终命中的层，用于统计各层覆盖率
  - 全部弃权时返回安全的默认动作（结束回合）
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lorwright.models import Action, ActionType, GameState, UIState
from lorwright.util.logger import logger


@dataclass
class RouteResult:
    action: Action
    layer: str
    candidates: list[str] = field(default_factory=list)


class Router:
    def __init__(self, layers: list) -> None:
        """layers: 按优先级排列的策略对象，需实现 decide(state)。"""
        self.layers = layers
        self.stats: dict[str, int] = {}

    def decide(self, state: GameState) -> RouteResult:
        for layer in self.layers:
            name = getattr(layer, "name", type(layer).__name__)
            try:
                action = layer.decide(state)
            except Exception as e:  # noqa: BLE001
                logger.exception("层 {} 决策异常，跳过: {}", name, e)
                continue

            if action is not None:
                self.stats[name] = self.stats.get(name, 0) + 1
                return RouteResult(action=action, layer=name)

        self.stats["fallback"] = self.stats.get("fallback", 0) + 1
        # 只在确认「轮到我方」时才盲目点结束回合；
        # 状态不明时宁可不动——否则会像 2026-11-02 那样点进设定菜单。
        if state.ui_state is UIState.MY_TURN_IDLE:
            return RouteResult(action=Action(type=ActionType.END_TURN), layer="fallback")
        return RouteResult(action=Action(type=ActionType.NO_OP), layer="fallback")

    def coverage(self) -> dict[str, float]:
        total = sum(self.stats.values()) or 1
        return {k: round(v / total, 3) for k, v in self.stats.items()}
