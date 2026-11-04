"""动作翻译：语义动作 → 具体点击坐标。

决策层只说「打第 2 张牌」「结束回合」，
这里负责把它变成鼠标操作。
"""

from __future__ import annotations

from lorwright.models import Action, ActionType, ClickPlan, GameState, Layout

__all__ = ["ActionTranslator", "ClickPlan", "Layout"]


class ActionTranslator:
    def __init__(
        self,
        layout: Layout,
        drag_ms: int = 800,
        drag_hold_ms: int = 300,
        drag_wait_ms: int = 600,
        tap_wait_ms: int = 400,
    ) -> None:
        self.layout = layout
        #: LoR 手机版只认慢拖，快 swipe 会被当成滑动取消
        self.drag_ms = drag_ms
        self.drag_hold_ms = drag_hold_ms
        self.drag_wait_ms = drag_wait_ms
        self.tap_wait_ms = tap_wait_ms

    def translate(self, action: Action, state: GameState) -> ClickPlan | None:
        if action.type is ActionType.NO_OP:
            return None

        if action.type is ActionType.END_TURN:
            if not self.layout.end_turn:
                return None
            return ClickPlan(
                points=[self.layout.end_turn.center], wait_ms=self.tap_wait_ms
            )

        if action.type is ActionType.PLAY_CARD and action.card_index is not None:
            card = next((c for c in state.hand if c.index == action.card_index), None)
            if card is None or self.layout.play_area is None:
                return None
            # 手机版只支持拖拽出牌，用一次慢拖完成
            return ClickPlan(
                points=[card.rect.center, self.layout.play_area.center],
                wait_ms=self.drag_wait_ms,
                drag=True,
                drag_ms=self.drag_ms,
                drag_hold_ms=self.drag_hold_ms,
            )

        if action.type is ActionType.ATTACK:
            target = self.layout.enemy_nexus
            if target is None:
                return None
            wanted = action.raw.get("attackers") if action.raw else None
            if wanted:
                attackers = [state.my_units[i] for i in wanted if i < len(state.my_units)]
            else:
                attackers = [u for u in state.my_units if u.can_attack][:1]
            if not attackers:
                return None
            # LoR 手机版：把每个单位拖到敌方水晶就是声明攻击
            drags = tuple((u.rect.center, target.center) for u in attackers)
            return ClickPlan(
                points=[drags[0][0], drags[0][1]],
                wait_ms=self.drag_wait_ms,
                drag=True,
                drag_ms=self.drag_ms,
                drag_hold_ms=self.drag_hold_ms,
                drags=drags,
            )

        return None
