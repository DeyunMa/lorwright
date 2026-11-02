"""动作翻译：语义动作 → 具体点击坐标。

决策层只说「打第 2 张牌」「结束回合」，
这里负责把它变成鼠标操作。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lorwright.models import Action, ActionType, GameState, Rect


@dataclass
class Layout:
    """当前界面上各区域的坐标（由感知层提供）。"""

    end_turn: Rect | None = None
    enemy_nexus: Rect | None = None
    play_area: Rect | None = None      # 出牌落点（棋盘中央）
    hand_region: Rect | None = None
    extras: dict[str, Rect] = field(default_factory=dict)


@dataclass(frozen=True)
class ClickPlan:
    """一次动作需要执行的点击序列。"""

    points: list[tuple[int, int]]
    wait_ms: int = 400


class ActionTranslator:
    def __init__(self, layout: Layout) -> None:
        self.layout = layout

    def translate(self, action: Action, state: GameState) -> ClickPlan | None:
        if action.type is ActionType.END_TURN:
            if not self.layout.end_turn:
                return None
            return ClickPlan(points=[self.layout.end_turn.center], wait_ms=600)

        if action.type is ActionType.PLAY_CARD and action.card_index is not None:
            card = next((c for c in state.hand if c.index == action.card_index), None)
            if card is None or self.layout.play_area is None:
                return None
            return ClickPlan(
                points=[card.rect.center, self.layout.play_area.center],
                wait_ms=500,
            )

        if action.type is ActionType.ATTACK:
            target = self.layout.enemy_nexus
            if target is None:
                return None
            attacker = next((u for u in state.my_units if u.can_attack), None)
            if attacker is None:
                return None
            return ClickPlan(points=[attacker.rect.center, target.center], wait_ms=500)

        return None
