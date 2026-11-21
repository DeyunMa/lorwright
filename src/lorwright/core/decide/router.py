"""分层路由：英雄包 → 通用规则 → 安全兜底。

设计要点：
  - None 表示弃权，继续下一层；NO_OP 是明确等待，选中后终止路由
  - 局部未知牌或英雄偏好不可执行时弃权，不能用 NO_OP 阻塞后续层
  - 记录最终命中的层，用于统计各层覆盖率
  - 全部弃权时：确认轮到我方就结束回合，否则 NO_OP
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lorwright.core.models import Action, ActionType, GameState, UIState
from lorwright.core.util.logger import logger


@dataclass
class RouteResult:
    action: Action
    layer: str
    candidates: list[str] = field(default_factory=list)
    reason: str = ""


_LAYER_REASONS = {
    "jinx_opening": "Jinx 起手与生成牌优先",
    "elise_spider_aggro": "Elise 专属策略",
    "expand_hand": "展开手牌以识别可执行候选",
    "play_unit": "选择费用最低的可出单位，同费优先身材更强者",
    "hero_first": "优先打出可支付的英雄",
    "targeting": "目标类型尚未明确，等待识别",
    "attack_when_token": "有攻击令牌时进攻，已声明则确认",
    "optional_choice": "明确识别可选选牌界面，跳过候选后继续",
    "required_choice": "明确识别强制选牌界面，选取最左候选",
    "combat_confirm": "确认战斗结算",
    "blocking": "按格挡资格与损失选择格挡，声明后确认",
}


def _decision_reason(action: Action, layer: str, state: GameState) -> str:
    reason = action.raw.get("reason")
    if isinstance(reason, str) and reason.strip():
        return reason
    if action.type is ActionType.NO_OP:
        if state.ui_state is UIState.MULLIGAN:
            return "换牌信息尚未明确，等待识别"
        if state.ui_state is UIState.TARGETING:
            return "目标类型尚未明确，等待识别"
        return f"{_LAYER_REASONS.get(layer, layer)}：等待交互结果"
    if action.raw.get("jinx_rocket") is True:
        return "已识别且可支付的 Jinx 火箭优先"
    return _LAYER_REASONS.get(layer, f"策略 {layer} 选择动作 {action.type.value}")


class Router:
    def __init__(self, layers: list) -> None:
        """layers: 按优先级排列的策略对象，需实现 decide(state)。"""
        self.layers = layers
        self.stats: dict[str, int] = {}

    def decide(self, state: GameState, *, suppress_hand_expansion: bool = False) -> RouteResult:
        candidates = []
        for layer in self.layers:
            name = getattr(layer, "name", type(layer).__name__)
            candidates.append(name)
            try:
                action = layer.decide(state)
            except Exception as e:  # noqa: BLE001
                logger.exception("层 {} 决策异常，跳过: {}", name, e)
                continue

            if (suppress_hand_expansion and action is not None
                    and action.type is ActionType.EXPAND_HAND):
                continue
            if action is not None:
                self.stats[name] = self.stats.get(name, 0) + 1
                return RouteResult(action=action, layer=name, candidates=candidates,
                                   reason=_decision_reason(action, name, state))

        self.stats["fallback"] = self.stats.get("fallback", 0) + 1
        # 只有确认轮到我方且全部策略弃权时才结束回合；局部未知牌不全局阻塞。
        # 收手检查只抑制再次展开，不阻止检查完成后的结束回合。
        if state.ui_state is UIState.MY_TURN_IDLE:
            return RouteResult(action=Action(type=ActionType.END_TURN), layer="fallback",
                               candidates=candidates, reason="当前为我方回合，各策略均无可执行动作，结束回合")
        return RouteResult(action=Action(type=ActionType.NO_OP), layer="fallback",
                           candidates=candidates, reason="当前未确认我方可行动，等待状态更新")

    def coverage(self) -> dict[str, float]:
        total = sum(self.stats.values()) or 1
        return {k: round(v / total, 3) for k, v in self.stats.items()}
