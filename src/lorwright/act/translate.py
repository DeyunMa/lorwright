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
        drag_ms: int = 600,
        drag_hold_ms: int = 300,
        drag_wait_ms: int = 600,
        tap_wait_ms: int = 400,
        expand_wait_ms: int = 500,
    ) -> None:
        self.layout = layout
        #: LoR 手机版只认慢拖，快 swipe 会被当成滑动取消
        self.drag_ms = drag_ms
        self.drag_hold_ms = drag_hold_ms
        self.drag_wait_ms = drag_wait_ms
        self.tap_wait_ms = tap_wait_ms
        #: 点手牌到展开动画结束的等待
        self.expand_wait_ms = expand_wait_ms

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
            # 收起态手牌斜叠、每张只露左边缘，**拖不动**（实测 hold 120/300/800ms
            # 全部无效，但 tap 能展开）。必须先 tap 展开，下一帧在展开态再拖。
            # 拆成两帧是有意的：展开后卡片位置全变，同一帧里算不出拖拽起点。
            if not state.hand_expanded:
                if self.layout.hand_region is None:
                    return None
                return ClickPlan(
                    points=[self.layout.hand_region.center], wait_ms=self.expand_wait_ms
                )

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
            # 实测（2026-11-04）：把单位拖到分隔线上方（y≈500）就声明攻击，
            # 单位吸附到攻击行；拖到敌方水晶反而无效。拖完按钮变「確認」，
            # 需要下一帧再发 CONFIRM——拖拽和确认不能挤在同一帧。
            target = self.layout.attack_row
            if target is None:
                return None
            wanted = action.raw.get("attackers") if action.raw else None
            if wanted:
                attackers = [state.my_units[i] for i in wanted if i < len(state.my_units)]
            else:
                attackers = [u for u in state.my_units if u.can_attack][:1]
            if not attackers:
                return None
            drags = tuple((u.rect.center, target.center) for u in attackers)
            return ClickPlan(
                points=[drags[0][0], drags[0][1]],
                wait_ms=self.drag_wait_ms,
                drag=True,
                drag_ms=self.drag_ms,
                drag_hold_ms=self.drag_hold_ms,
                drags=drags,
            )

        if action.type is ActionType.BLOCK:
            # 格挡 = 把单位拖到敌方攻击单位上，单位会吸附到它正下方；
            # 被挡住的攻击不再打水晶（伤害预览数字实时下降）。
            pairs = action.raw.get("pairs") if action.raw else None
            if not pairs:
                return None
            drags = []
            for blocker_index, attacker_index in pairs:
                if blocker_index >= len(state.my_units) or attacker_index >= len(state.enemy_units):
                    continue
                drags.append(
                    (
                        state.my_units[blocker_index].rect.center,
                        state.enemy_units[attacker_index].rect.center,
                    )
                )
            if not drags:
                return None
            return ClickPlan(
                points=[drags[0][0], drags[0][1]],
                wait_ms=self.drag_wait_ms,
                drag=True,
                drag_ms=self.drag_ms,
                drag_hold_ms=self.drag_hold_ms,
                drags=tuple(drags),
            )

        if action.type is ActionType.CONFIRM:
            if not self.layout.end_turn:
                return None
            return ClickPlan(points=[self.layout.end_turn.center], wait_ms=self.tap_wait_ms)

        return None
