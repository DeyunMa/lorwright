"""输入前的局部稳定证据；每次新鲜观测计一次，输入后由调用者 reset。"""

from __future__ import annotations

from copy import deepcopy

from lorwright.core.decide.generic import ATTACK_ROW_MAX_Y
from lorwright.core.models import Action, ActionType, CardInHand, GameState, Rect, UIState, Unit


class ActionReadiness:
    """最近两帧必须支持当前动作；ready 查询本身不会积累观测。"""

    def __init__(self) -> None:
        self._previous: GameState | None = None
        self._current: GameState | None = None

    def observe(self, state: GameState | None) -> None:
        if state is None:
            self.reset()
            return
        self._previous = self._current
        self._current = deepcopy(state)

    def reset(self) -> None:
        self._previous = self._current = None

    def ready(self, action: Action) -> bool:
        if action.type is ActionType.NO_OP:
            return True
        if self._previous is None or self._current is None:
            return False
        before = _evidence(action, self._previous)
        after = _evidence(action, self._current)
        return before is not None and after is not None and _stable(before, after)


def _stable(before: object, after: object) -> bool:
    if isinstance(before, Rect) and isinstance(after, Rect):
        return all(abs(a - b) <= 12 for a, b in zip(
            (before.x, before.y, before.w, before.h),
            (after.x, after.y, after.w, after.h), strict=True,
        ))
    if isinstance(before, tuple) and isinstance(after, tuple):
        return len(before) == len(after) and all(
            _stable(a, b) for a, b in zip(before, after, strict=True)
        )
    return before == after


def _index(value: object, length: int) -> bool:
    return type(value) is int and 0 <= value < length


def _rect(rect: Rect | None) -> Rect | None:
    return rect if rect is not None and rect.w > 0 and rect.h > 0 else None


def _card(card: CardInHand, *, drag: bool = False) -> tuple | None:
    if _rect(card.rect) is None or (drag and card.cost < 0):
        return None
    point = card.drag_point or card.rect.center
    if drag and (not card.drag_point_valid or len(point) != 2):
        return None
    return (card.index, card.name, card.cost, card.rect, card.visible_playable_unit,
            Rect(*point, 1, 1) if drag else None)


def _unit(unit: Unit) -> tuple | None:
    if _rect(unit.rect) is None:
        return None
    return (unit.name, unit.attack, unit.health, unit.can_attack, unit.keywords,
            unit.stunned, unit.rect)


def _spell(state: GameState) -> tuple | None:
    spell = state.targeted_spell
    if spell is None or not spell.name or _rect(spell.rect) is None:
        return None
    return (spell.name, spell.rect)


def _evidence(action: Action, state: GameState) -> tuple | None:
    if state.ui_state is UIState.UNKNOWN:
        return None
    baseline = (state.ui_state, state.action_prompt, state.hand_expanded)
    kind, raw = action.type, action.raw
    detail: tuple | Rect | None
    if kind is ActionType.PLAY_CARD:
        if type(action.card_index) is not int or action.card_index < 0:
            return None
        cards = [c for c in state.hand if c.index == action.card_index]
        if len(cards) != 1:
            return None
        detail = _card(cards[0], drag=True) if state.hand_expanded else None
    elif kind is ActionType.EXPAND_HAND:
        detail = ((True,) if state.ui_state is UIState.MY_TURN_IDLE
                  and not state.hand_expanded and state.hand else None)
    elif kind is ActionType.DISCARD_CARD:
        candidates = state.discard_candidates
        index = action.card_index
        if (candidates is None or not _index(index, len(candidates.cards))
                or not _index(index, len(candidates.costs))
                or _rect(candidates.cards[index]) is None
                or candidates.costs[index] is None):
            return None
        detail = (candidates.cards[index], candidates.costs[index])
    elif kind is ActionType.SELECT_TARGET:
        spell = _spell(state)
        if spell is None:
            return None
        if raw.get("nexus") and not raw.get("hand"):
            detail = (spell, "nexus")  # 固定 layout 坐标由 translator 校验。
        else:
            items = (state.hand if raw.get("hand") else
                     state.enemy_units if raw.get("enemy") else state.my_units)
            index = raw.get("index", 0)
            if not _index(index, len(items)):
                return None
            selected = (_card(items[index]) if raw.get("hand") else _unit(items[index]))
            detail = (spell, selected) if selected is not None else None
    elif kind is ActionType.ATTACK:
        wanted = raw.get("attackers")
        if wanted:
            if not isinstance(wanted, (list, tuple)) or any(
                not _index(i, len(state.my_units)) for i in wanted
            ):
                return None
            units = [state.my_units[i] for i in wanted]
        else:
            units = [u for u in state.my_units if u.can_attack][:1]
        if not units or any(not u.can_attack or u.stunned for u in units):
            return None
        detail = tuple(_unit(u) for u in units)
    elif kind is ActionType.BLOCK:
        pairs = raw.get("pairs")
        enemies = state.enemy_attackers or state.enemy_units
        if not isinstance(pairs, (list, tuple)) or not pairs:
            return None
        chosen = []
        for pair in pairs:
            if (not isinstance(pair, (list, tuple)) or len(pair) != 2
                    or not _index(pair[0], len(state.my_units))
                    or not _index(pair[1], len(enemies))):
                return None
            chosen.extend((_unit(state.my_units[pair[0]]), _unit(enemies[pair[1]])))
        detail = tuple(chosen)
    elif kind is ActionType.MULLIGAN_REPLACE:
        index = raw.get("mulligan_index")
        if (state.ui_state is not UIState.MULLIGAN
                or not _index(index, len(state.mulligan_selected))
                or type(raw.get("selected")) is not bool
                or type(state.mulligan_selected[index]) is not bool
                or state.mulligan_selected[index] == raw["selected"]):
            return None
        cards = [c for c in state.mulligan_cards if c.index == index]
        if len(cards) != 1 or _rect(cards[0].rect) is None:
            return None
        points = raw.get("points")
        if (not isinstance(points, (list, tuple)) or len(points) != 1
                or not isinstance(points[0], (list, tuple)) or len(points[0]) != 2
                or any(type(value) is not int for value in points[0])
                or not _stable(Rect(*points[0], 1, 1), Rect(*cards[0].rect.center, 1, 1))):
            return None
        detail = (state.mulligan_selected[index], cards[0].matches_target, cards[0].rect)
    elif kind is ActionType.CONFIRM:
        if state.ui_state is UIState.MULLIGAN:
            if len(state.mulligan_selected) != 4 or any(
                type(value) is not bool for value in state.mulligan_selected
            ):
                return None
            detail = state.mulligan_selected
        elif state.action_prompt:
            detail = (state.action_prompt,)
        elif state.ui_state is UIState.BLOCKING:
            # 也允许没有格挡者的直接确认；敌方攻击者必须有可见位置。
            attackers = state.enemy_attackers or state.enemy_units
            positions = tuple(_rect(u.rect) for u in (*state.my_units, *attackers))
            if not attackers or any(rect is None for rect in positions):
                return None
            detail = (tuple(u.rect for u in state.my_units), tuple(u.rect for u in attackers))
        elif state.ui_state is UIState.MY_TURN_IDLE:
            if any(_rect(u.rect) is None for u in state.my_units):
                return None
            in_row = tuple(u.rect for u in state.my_units
                           if u.rect.center[1] < ATTACK_ROW_MAX_Y)
            detail = (in_row,) if in_row else None
        else:
            detail = None
    elif kind in (ActionType.END_TURN, ActionType.PASS):
        # 交回优先权不使用卡名、费用或单位数值；路由器逐帧重新判断可执行动作。
        # 仍等待手牌与场面的位置/数量稳定，不在布局变化时点击固定按钮。
        positions = tuple(tuple(_rect(item.rect) for item in collection) for collection in (
            state.hand, state.my_units, state.enemy_units, state.enemy_attackers,
        ))
        if any(rect is None for collection in positions for rect in collection):
            return None
        detail = (*positions, state.hand_empty_confirmed, state.has_attack_token)
    elif kind is ActionType.CONTINUE:
        detail = _rect(state.continue_button)
    elif kind is ActionType.CANCEL:
        detail = _spell(state) if raw.get("return_to_hand") else (True,)
    elif kind is ActionType.COLLAPSE_HAND:
        detail = (True,) if state.ui_state is UIState.MY_TURN_IDLE and state.hand_expanded else None
    elif kind is ActionType.SKIP_CHOICE:
        detail = (True,) if state.ui_state is UIState.OPTIONAL_CHOICE else None
    else:
        return None
    if detail is None or (isinstance(detail, tuple) and any(x is None for x in detail)):
        # 卡片签名中可选拖拽点为 None；这里只检查动作层的缺失项。
        return None
    return (baseline, detail)
