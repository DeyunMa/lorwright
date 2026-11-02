"""L1 规则层：蜘蛛快攻。

设计原则：优先做「确定性判断」，覆盖 70-80% 的回合。
规则按优先级从高到低执行，第一条命中的直接返回。
"""

from __future__ import annotations

from lorwright.decide.base import Policy
from lorwright.models import Action, ActionType, GameState, UIState


class SpiderAggroPolicy(Policy):
    name = "spider_aggro"
    version = "0.1.0"

    def decide(self, state: GameState) -> Action | None:
        # 不是我的回合 → 不做决策
        if state.ui_state != UIState.MY_TURN_IDLE:
            return None

        # R1：能斩杀 → 全力打脸
        if self._can_lethal(state):
            return Action(type=ActionType.ATTACK, target="nexus")

        # R2：手牌有 0-1 费牌且法力够 → 优先打出
        cheap = self._cheapest_playable(state)
        if cheap is not None:
            return Action(type=ActionType.PLAY_CARD, card_index=cheap)

        # R3：没牌可出 → 结束回合
        if not state.hand:
            return Action(type=ActionType.END_TURN)

        # 其余情况弃权，交给 JEV / LLM
        return None

    def _can_lethal(self, state: GameState) -> bool:
        total = sum(u.attack for u in state.my_units if u.can_attack)
        return total >= state.enemy_nexus_hp

    def _cheapest_playable(self, state: GameState) -> int | None:
        candidates = [
            c for c in state.hand if 0 <= c.cost <= state.mana
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda c: c.cost).index
