"""输入前的局部稳定证据；每次新鲜观测计一次，输入后由调用者 reset。"""

from __future__ import annotations

from copy import deepcopy

from lorwright.core.decide.generic import (
    ATTACK_ROW_MAX_Y,
    _committed_blocks,
    same_unit,
    same_unit_identity,
    weakest_replace_index,
)
from lorwright.core.models import Action, ActionType, CardInHand, GameState, Rect, UIState, Unit


class ActionReadiness:
    """最近两帧必须支持当前动作；ready 查询本身不会积累观测。"""

    def __init__(self) -> None:
        self._previous: GameState | None = None
        self._current: GameState | None = None
        #: 每帧最终决策的动作类型；None 表示该帧未决策。
        self._previous_decision: ActionType | None = None
        self._current_decision: ActionType | None = None

    def observe(self, state: GameState | None) -> None:
        if state is None:
            self.reset()
            return
        self._previous = self._current
        self._current = deepcopy(state)
        self._previous_decision = self._current_decision
        self._current_decision = None

    def note_decision(self, action: Action) -> None:
        """记录本帧（最近一次 observe）最终决策出的动作。"""
        self._current_decision = action.type

    def reset(self) -> None:
        self._previous = self._current = None
        self._previous_decision = self._current_decision = None

    def _stable_indices(self, units_of) -> frozenset[int]:
        """_current 里在 _previous 同位置同数值出现过的单位下标。"""
        if self._previous is None or self._current is None:
            return frozenset()
        before, after = units_of(self._previous), units_of(self._current)
        return frozenset(
            i for i, unit in enumerate(after)
            if any(same_unit(unit, seen) for seen in before)
        )

    def stable_my_units(self) -> frozenset[int]:
        return self._stable_indices(lambda state: state.my_units)

    def stable_enemy_units(self) -> frozenset[int]:
        return self._stable_indices(
            lambda state: state.enemy_attackers or state.enemy_units)

    def my_units_floor(self, current: int) -> int:
        """场面数量下界：最近两帧较大值（帧抖只会少读不会多读）。"""
        if self._previous is None:
            return current
        return max(current, len(self._previous.my_units))

    def ready(self, action: Action) -> bool:
        if action.type is ActionType.NO_OP:
            return True
        if self._previous is None or self._current is None:
            return False
        if action.type in _HANDOFF:
            # 交回优先权是「各策略均无可执行动作」时的兜底，它的前提
            # 是该结论本身跨两帧成立：单位列表抖动让某一帧的攻击/出牌
            # 策略失去依据时，那一帧不能单独促成交回。决策稳定取代
            # 原先「整表单位位置稳定」的代理证据。
            if (self._previous_decision is not action.type
                    or self._current_decision is not action.type):
                return False
        # 选择具体单位的动作在紫色可选中/屏障辉光下整表证据永不
        # 稳定（my_units 逐帧增减）；这些动作只需要「所选单位跨两帧
        # 是同一个」，按目标身份比对，不要求整表稳定。
        identity_ready = _identity_ready(action, self._previous, self._current)
        if identity_ready is not None:
            return identity_ready
        before = _evidence(action, self._previous)
        after = _evidence(action, self._current)
        return before is not None and after is not None and _stable(before, after)


_HANDOFF = (ActionType.END_TURN, ActionType.PASS)


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


def _matched(unit: Unit, pool: list[Unit]) -> bool:
    return any(same_unit(unit, seen) for seen in pool)


def _identity_ready(
    action: Action, before: GameState, after: GameState,
) -> bool | None:
    """单位身份就绪证据：所选单位跨两帧同位置同数值即可，不看整表。

    返回 None 表示不接管（交给通用整表证据路径）。
    """
    kind = action.type
    if kind is ActionType.SELECT_TARGET and not (
            action.raw.get("enemy") or action.raw.get("hand")
            or action.raw.get("nexus")):
        return _friendly_target_ready(action, before, after)
    if kind is ActionType.BLOCK:
        return _block_ready(action, before, after)
    if kind is ActionType.ATTACK:
        return _attack_ready(action, before, after)
    if (kind is ActionType.CONFIRM and before.ui_state is UIState.BLOCKING
            and after.ui_state is UIState.BLOCKING):
        return _confirm_block_ready(before, after)
    if (kind is ActionType.CONFIRM and before.ui_state is UIState.MY_TURN_IDLE
            and after.ui_state is UIState.MY_TURN_IDLE
            and not before.action_prompt and not after.action_prompt
            and before.hand_expanded == after.hand_expanded):
        return _confirm_attack_ready(before, after)
    return None


def _friendly_target_ready(
    action: Action, before: GameState, after: GameState,
) -> bool | None:
    """友军 select_target：所选单位跨帧同一 + 上下文证据稳定。"""
    if not (before.ui_state is UIState.TARGETING
            and after.ui_state is UIState.TARGETING):
        return None
    index = action.raw.get("index", 0)
    if not _index(index, len(after.my_units)):
        return False
    chosen = after.my_units[index]
    # 替换提示：目标必须是跨帧最弱稳定单位（与策略同一规则）。
    if (before.replace_prompt and after.replace_prompt
            and before.targeted_spell is None and after.targeted_spell is None):
        matched = [i for i, unit in enumerate(after.my_units)
                   if _matched(unit, before.my_units)]
        if not matched:
            return False
        return same_unit(chosen, after.my_units[
            weakest_replace_index(after.my_units, matched)])
    # 法术点友军：法术身份两帧稳定且所选单位跨帧同一。
    spell_before, spell_after = _spell(before), _spell(after)
    if spell_before is not None and spell_after is not None:
        return (_stable(spell_before, spell_after)
                and _matched(chosen, before.my_units))
    return None


def _block_ready(action: Action, before: GameState, after: GameState) -> bool:
    """BLOCK：每个声明的格挡者与攻击者跨两帧都是同一单位。"""
    if before.ui_state is not after.ui_state:
        return False
    pairs = action.raw.get("pairs")
    enemies = after.enemy_attackers or after.enemy_units
    seen_enemies = before.enemy_attackers or before.enemy_units
    if not isinstance(pairs, (list, tuple)) or not pairs:
        return False
    for pair in pairs:
        if (not isinstance(pair, (list, tuple)) or len(pair) != 2
                or not _index(pair[0], len(after.my_units))
                or not _index(pair[1], len(enemies))):
            return False
        if (not _matched(after.my_units[pair[0]], before.my_units)
                or not _matched(enemies[pair[1]], seen_enemies)):
            return False
    return True


def _attack_ready(action: Action, before: GameState, after: GameState) -> bool:
    """ATTACK：每个声明的攻击者跨两帧同一单位且当前仍可攻击。"""
    if before.ui_state is not after.ui_state:
        return False
    wanted = action.raw.get("attackers")
    if wanted:
        if not isinstance(wanted, (list, tuple)) or any(
            not _index(i, len(after.my_units)) for i in wanted
        ):
            return False
        units = [after.my_units[i] for i in wanted]
    else:
        units = [u for u in after.my_units if u.can_attack][:1]
    if not units or any(not u.can_attack or u.stunned for u in units):
        return False
    return all(_matched(unit, before.my_units) for unit in units)


def _confirm_block_ready(before: GameState, after: GameState) -> bool:
    """BLOCKING 下的 CONFIRM：确认的是当前可见指派。

    敌方攻击者必须全部跨帧同一；当前可见的行内（已锁定）格挡者
    也必须跨帧同一——行内单位少读一帧不代表指派变了。后排单位
    增减不影响确认语义，不参与证据。
    """
    enemies = after.enemy_attackers or after.enemy_units
    seen_enemies = before.enemy_attackers or before.enemy_units
    if not enemies or any(not _matched(unit, seen_enemies) for unit in enemies):
        return False
    lane = _committed_blocks(after.my_units, enemies)
    if any(not _matched(after.my_units[blocker], before.my_units)
           for _, blocker in lane):
        return False
    # 帧抖只会少读/多读，不会让同一单位换位置：前后帧都未匹配
    # 的单位若身份相同，说明是真实移动而非漏读，继续等待。
    before_rest = [u for u in before.my_units
                   if not _matched(u, after.my_units)]
    after_rest = [u for u in after.my_units
                  if not _matched(u, before.my_units)]
    return not any(same_unit_identity(b, a)
                   for b in before_rest for a in after_rest)


def _in_row(units: list[Unit]) -> list[Unit]:
    return [u for u in units
            if _rect(u.rect) is not None and u.rect.center[1] < ATTACK_ROW_MAX_Y]


def _confirm_attack_ready(before: GameState, after: GameState) -> bool:
    """MY_TURN_IDLE 下的 CONFIRM：确认的是当前已声明的攻击行。

    只按位置核验：本帧攻击行内每个单位上一帧都在同一位置（数值在
    辉光下可能读不出，不作证据）。后排单位（常被展开手牌遮挡、带
    辉光抖动）不参与；上一帧行内单位本帧少读一帧也不改变已声明的
    攻击，真实移动会在本帧出现未匹配的新位置而继续等待。
    """
    lane = _in_row(after.my_units)
    seen = [u.rect for u in _in_row(before.my_units)]
    return bool(lane) and all(
        any(_stable(unit.rect, rect) for rect in seen) for unit in lane)


def _rect(rect: Rect | None) -> Rect | None:
    return rect if rect is not None and rect.w > 0 and rect.h > 0 else None


def _card(card: CardInHand, *, drag: bool = False) -> tuple | None:
    if _rect(card.rect) is None or (drag and card.cost < 0):
        return None
    point = card.drag_point or card.rect.center
    if drag and (not card.drag_point_valid or len(point) != 2):
        return None
    # 拖拽只依赖起点物理位置稳定：卡名 OCR 在已知↔未知间抖动不会改变
    # 牌位，纳入证据会让就绪永远不过两帧（实机 20261121T140226 尖嘯蜘蛛
    # index 2 卡名抖动停 action_readiness_unverified）。rect/cost 变化
    # 仍按原判据阻断。
    if drag:
        return (card.index, card.cost, card.rect, card.visible_playable_unit,
                Rect(*point, 1, 1))
    return (card.index, card.name, card.cost, card.rect,
            card.visible_playable_unit, None)


def _unit(unit: Unit) -> tuple | None:
    if _rect(unit.rect) is None:
        return None
    return (unit.name, unit.attack, unit.health, unit.can_attack, unit.keywords,
            unit.stunned, unit.rect)


def _unit_identity(unit: Unit) -> tuple | None:
    """选中单位的身份证据：位置+名字/数值，不含辉光下抖动的图标。"""
    if _rect(unit.rect) is None:
        return None
    return (unit.name, unit.attack, unit.health, unit.rect)


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
        # 替换提示选友军时没有待选法术图标；提示条本身就是身份证据。
        replace = (state.replace_prompt and not raw.get("enemy")
                   and not raw.get("hand") and not raw.get("nexus"))
        # 可选「跳過」提示：敌方单位跨帧稳定即为身份证据。
        skip_prompt = (state.action_prompt == "action_skip"
                       and bool(raw.get("enemy"))
                       and not raw.get("hand") and not raw.get("nexus"))
        # 法术变体选项：选项卡 rect 跨帧稳定即身份证据，无需法术图标。
        option = raw.get("option")
        if spell is None and not replace and not skip_prompt and option is None:
            return None
        key = (spell if spell is not None else
               ("replace_prompt",) if replace else ("action_skip",))
        if option is not None:
            index = option
            detail = (("spell_option", state.spell_options[index])
                      if (_index(index, len(state.spell_options))
                          and _rect(state.spell_options[index]) is not None)
                      else None)
        elif raw.get("nexus") and not raw.get("hand"):
            detail = (key, "nexus")  # 固定 layout 坐标由 translator 校验。
        else:
            items = (state.hand if raw.get("hand") else
                     state.enemy_units if raw.get("enemy") else state.my_units)
            index = raw.get("index", 0)
            if not _index(index, len(items)):
                return None
            selected = (_card(items[index]) if raw.get("hand")
                        else _unit_identity(items[index]))
            detail = (key, selected) if selected is not None else None
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
        else:
            # MY_TURN_IDLE 无提示的攻击确认由 _confirm_attack_ready 按身份核验。
            detail = None
    elif kind in _HANDOFF:
        # 交回优先权点固定按钮，不使用卡名、费用或单位数值，也不使用
        # 单位列表：展开手牌遮挡后排、紫色辉光让 my_units/enemy_units
        # 逐帧增减，整表证据永不稳定（实机 20261121T085539）。「没有
        # 其他可执行动作」由 ready() 要求两帧都决策为交回来保证；这里
        # 只等手牌布局与攻击令牌稳定，不在抽牌/出牌动画中点按钮。
        positions = tuple(_rect(card.rect) for card in state.hand)
        if any(rect is None for rect in positions):
            return None
        detail = (positions, state.hand_empty_confirmed, state.has_attack_token)
    elif kind is ActionType.CONTINUE:
        detail = _rect(state.continue_button)
    elif kind is ActionType.CANCEL:
        detail = _spell(state) if raw.get("return_to_hand") else (True,)
    elif kind is ActionType.COLLAPSE_HAND:
        detail = (True,) if state.ui_state is UIState.MY_TURN_IDLE and state.hand_expanded else None
    elif kind is ActionType.SKIP_CHOICE:
        detail = (True,) if state.ui_state is UIState.OPTIONAL_CHOICE else None
    elif kind is ActionType.PICK_CHOICE:
        detail = (True,) if state.ui_state is UIState.REQUIRED_CHOICE else None
    else:
        return None
    if detail is None or (isinstance(detail, tuple) and any(x is None for x in detail)):
        # 卡片签名中可选拖拽点为 None；这里只检查动作层的缺失项。
        return None
    return (baseline, detail)
