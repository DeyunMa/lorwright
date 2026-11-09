"""候选动作生成：把局面变成「可选动作列表」。

规则层直接选；候选集用于调试/复盘和未来的有界决策。
"""

from __future__ import annotations

from lorwright.models import Action, ActionType, GameState


def generate(state: GameState) -> list[Action]:
    """生成当前局面的合法候选动作（语义层，不含坐标）。"""
    out: list[Action] = []

    # 出牌：每张付得起的牌都是一个候选
    for card in state.hand:
        if 0 <= card.cost <= state.mana:
            out.append(Action(type=ActionType.PLAY_CARD, card_index=card.index))

    # 攻击：有可攻击单位就可以打脸
    if any(u.can_attack for u in state.my_units):
        out.append(Action(type=ActionType.ATTACK, target="nexus"))

    # 永远可以结束回合
    out.append(Action(type=ActionType.END_TURN))

    return out


def describe(action: Action, state: GameState) -> str:
    """把动作翻译成人类可读字符串（日志/复盘用）。"""
    if action.type is ActionType.PLAY_CARD and action.card_index is not None:
        card = next((c for c in state.hand if c.index == action.card_index), None)
        if card:
            return f"打出 {card.name}（{card.cost} 费）"
        return f"打出第 {action.card_index} 张牌"
    if action.type is ActionType.ATTACK:
        return f"攻击 {action.target}"
    if action.type is ActionType.END_TURN:
        return "结束回合"
    return str(action.type.value)
