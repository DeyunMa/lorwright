from copy import deepcopy
from dataclasses import replace

import pytest

from lorwright.core.champions.elise import SpiderAggroPolicy
from lorwright.core.decide.generic import AttackWhenTokenPolicy, BlockingPolicy
from lorwright.core.loop.readiness import ActionReadiness
from lorwright.core.models import (
    Action,
    ActionType,
    CardInHand,
    DiscardCandidates,
    GameState,
    MulliganCard,
    Rect,
    TargetedSpell,
    UIState,
    Unit,
)
from tools.test_data import fixtures_root


def state():
    return GameState(
        ui_state=UIState.MY_TURN_IDLE, hand_expanded=True,
        hand=[CardInHand(0, "known", 2, Rect(100, 800, 100, 150)),
              CardInHand(1, "", -1, Rect(300, 800, 100, 150))],
        my_units=[Unit("ally", 2, 3, Rect(400, 700, 90, 100))],
        enemy_units=[Unit("enemy", 3, 4, Rect(400, 200, 90, 100))],
        targeted_spell=TargetedSpell("spell", Rect(900, 500, 80, 80)),
        continue_button=Rect(1000, 800, 100, 50),
    )


def observed(before, after=None):
    gate = ActionReadiness()
    gate.observe(before)
    gate.observe(after if after is not None else before)
    return gate


PLAY = Action(ActionType.PLAY_CARD, card_index=0)
TARGET = Action(ActionType.SELECT_TARGET, raw={"enemy": True, "index": 0})
OPTION = Action(ActionType.SELECT_TARGET, raw={"option": 0})
ATTACK = Action(ActionType.ATTACK, raw={"attackers": [0]})


def test_spell_option_pick_requires_stable_option_rect():
    """变体选项证据 = 选项卡 rect 两帧一致；识别不出则不就绪。"""
    options = (Rect(645, 240, 280, 320), Rect(965, 240, 280, 320))
    before = replace(state(), ui_state=UIState.TARGETING,
                     targeted_spell=None, spell_options=options)
    assert observed(before).ready(OPTION)
    jittered = replace(before, spell_options=(
        replace(options[0], x=options[0].x + 30), options[1]))
    assert not observed(before, jittered).ready(OPTION)
    assert not observed(before, replace(before, spell_options=())).ready(OPTION)
BLOCK = Action(ActionType.BLOCK, raw={"pairs": [(0, 0)]})


def discard_state():
    return GameState(ui_state=UIState.DISCARD, discard_candidates=DiscardCandidates(
        cards=(Rect(100, 400, 200, 300), Rect(500, 400, 200, 300)),
        costs=(3, None), similarities=(),
    ))


def test_discard_checks_only_selected_slot_without_identity():
    before = discard_state()
    after = deepcopy(before)
    after.discard_candidates = replace(after.discard_candidates,
        cards=(Rect(112, 400, 200, 300), Rect(900, 400, 200, 300)),
        costs=(3, 8), similarities=((0.1,),))
    action = Action(ActionType.DISCARD_CARD, card_index=0)
    gate = ActionReadiness()
    gate.observe(before)
    assert not gate.ready(action)
    gate.observe(after)
    assert gate.ready(action)


@pytest.mark.parametrize("candidates", [
    None,
    DiscardCandidates(cards=(), costs=(), similarities=()),
    DiscardCandidates(cards=(Rect(100, 400, 200, 300),), costs=(), similarities=()),
    DiscardCandidates(cards=(Rect(100, 400, 200, 300),), costs=(None,), similarities=()),
    DiscardCandidates(cards=(Rect(113, 400, 200, 300),), costs=(3,), similarities=()),
    DiscardCandidates(cards=(Rect(100, 400, 200, 300),), costs=(4,), similarities=()),
    DiscardCandidates(cards=(Rect(100, 400, 0, 300),), costs=(3,), similarities=()),
])
def test_discard_missing_or_changing_selected_evidence_blocks(candidates):
    before = discard_state()
    after = deepcopy(before)
    after.discard_candidates = candidates
    assert not observed(before, after).ready(Action(ActionType.DISCARD_CARD, card_index=0))


@pytest.mark.parametrize("index", [None, -1, 2, True])
def test_discard_invalid_index_blocks(index):
    assert not observed(discard_state()).ready(Action(ActionType.DISCARD_CARD, card_index=index))


def test_no_op_needs_no_observation():
    assert ActionReadiness().ready(Action(ActionType.NO_OP))


def test_single_frame_and_queries_do_not_accumulate():
    gate = ActionReadiness()
    gate.observe(state())
    for _ in range(4):
        assert not gate.ready(PLAY)
    gate.observe(state())
    assert gate.ready(PLAY)


@pytest.mark.parametrize("action", [PLAY, TARGET, ATTACK, BLOCK])
def test_local_unknown_and_unrelated_resources_do_not_block(action):
    before = state()
    after = deepcopy(before)
    after.hand[1] = replace(after.hand[1], name="unrelated", cost=8)
    after.nexus_hp = 1
    after.enemy_nexus_hp = 42
    after.mana = 0
    assert observed(before, after).ready(action)


@pytest.mark.parametrize("field,value", [
    ("ui_state", UIState.TARGETING), ("action_prompt", "action_confirm"),
    ("hand_expanded", False), ("ui_state", UIState.UNKNOWN),
])
def test_baseline_changes_interrupt_stability(field, value):
    before = state()
    after = deepcopy(before)
    setattr(after, field, value)
    assert not observed(before, after).ready(PLAY)


def test_flash_requires_two_frames_after_return():
    gate = observed(state())
    flash = state()
    flash.action_prompt = "action_confirm"
    gate.observe(flash)
    assert not gate.ready(PLAY)
    gate.observe(state())
    assert not gate.ready(PLAY)
    gate.observe(state())
    assert gate.ready(PLAY)


@pytest.mark.parametrize("change", [
    {"cost": 3}, {"drag_point_valid": False},
    {"rect": Rect(150, 800, 100, 150)}, {"drag_point": (900, 900)},
    {"rect": Rect(100, 800, 0, 150)},
])
def test_play_checks_selected_card(change):
    before = state()
    after = deepcopy(before)
    after.hand[0] = replace(after.hand[0], **change)
    assert not observed(before, after).ready(PLAY)


@pytest.mark.parametrize("name", ["", "other", "尖嘯蜘蛛"])
def test_play_name_ocr_flicker_does_not_block(name):
    # 实机 20261121T140226：卡名识别在已知↔未知间抖动但牌位未动，
    # 拖拽证据不含名字，仍须两帧稳定后放行。
    before = state()
    after = deepcopy(before)
    after.hand[0] = replace(after.hand[0], name=name)
    assert observed(before, after).ready(PLAY)


@pytest.mark.parametrize("distance,expected", [(12, True), (13, False)])
def test_card_position_tolerance(distance, expected):
    before = state()
    after = deepcopy(before)
    after.hand[0] = replace(after.hand[0], rect=Rect(100 + distance, 800, 100, 150))
    assert observed(before, after).ready(PLAY) is expected


def test_collapsed_hand_only_readies_expansion_without_card_identity():
    before = state()
    before.hand_expanded = False
    after = deepcopy(before)
    after.hand[0] = replace(after.hand[0], name="", cost=-1, drag_point_valid=False,
                            rect=Rect(900, 800, 0, 0))
    gate = observed(before, after)
    assert gate.ready(Action(ActionType.EXPAND_HAND))
    assert not gate.ready(PLAY)
    assert not observed(before).ready(Action(ActionType.PLAY_CARD, card_index=9))


@pytest.mark.parametrize("action", [TARGET, ATTACK, BLOCK])
def test_selected_unit_movement_blocks(action):
    before = state()
    after = deepcopy(before)
    after.my_units[0] = replace(after.my_units[0], rect=Rect(600, 700, 90, 100))
    after.enemy_units[0] = replace(after.enemy_units[0], rect=Rect(600, 200, 90, 100))
    assert not observed(before, after).ready(action)


@pytest.mark.parametrize("spell", [None, TargetedSpell("different", Rect(900, 500, 80, 80))])
def test_target_requires_stable_spell_identity(spell):
    before = state()
    after = deepcopy(before)
    after.targeted_spell = spell
    assert not observed(before, after).ready(TARGET)


def test_target_checks_only_chosen_side_and_slot():
    before = state()
    after = deepcopy(before)
    after.my_units.clear()
    assert observed(before, after).ready(TARGET)
    after.enemy_units[0] = replace(after.enemy_units[0], name="new target")
    assert not observed(before, after).ready(TARGET)


def test_target_prompt_pick_requires_stable_chosen_enemy():
    """必选「選擇目標」提示：所选敌方单位跨帧同位同数值即就绪。"""
    before = replace(state(), ui_state=UIState.TARGETING,
                     targeted_spell=None, action_prompt="action_target")
    assert observed(before).ready(TARGET)
    moved = replace(before, enemy_units=[
        replace(before.enemy_units[0], rect=Rect(420, 200, 90, 100)),
        *before.enemy_units[1:]])
    assert not observed(before, moved).ready(TARGET)
    # 提示读不出时没有身份证据，不就绪。
    no_prompt = replace(before, action_prompt=None)
    assert not observed(no_prompt).ready(TARGET)


def test_hand_target_and_nexus_raw_formats():
    gate = observed(state())
    assert gate.ready(Action(ActionType.SELECT_TARGET, raw={"hand": True, "index": 0}))
    assert gate.ready(Action(ActionType.SELECT_TARGET, raw={"nexus": True}))


def test_block_uses_attacker_list():
    before = state()
    before.enemy_attackers = [Unit("attacker", 4, 5, Rect(800, 300, 90, 100))]
    after = deepcopy(before)
    after.enemy_units.clear()
    assert observed(before, after).ready(BLOCK)
    after.enemy_attackers.clear()
    assert not observed(before, after).ready(BLOCK)


@pytest.mark.parametrize("action", [
    Action(ActionType.PLAY_CARD, card_index=-1),
    Action(ActionType.PLAY_CARD),
    Action(ActionType.SELECT_TARGET, raw={"enemy": True, "index": -1}),
    Action(ActionType.SELECT_TARGET, raw={"hand": True, "index": 99}),
    Action(ActionType.ATTACK, raw={"attackers": [-1]}),
    Action(ActionType.ATTACK, raw={"attackers": [0, 99]}),
    Action(ActionType.BLOCK, raw={"pairs": [(0, -1)]}),
    Action(ActionType.BLOCK, raw={"pairs": [(0, 99)]}),
])
def test_invalid_indices_are_conservative(action):
    assert not observed(state()).ready(action)


def mulligan():
    return GameState(ui_state=UIState.MULLIGAN,
                     mulligan_selected=(False, False, False, False),
                     mulligan_cards=[MulliganCard(0, False, Rect(430, 810, 16, 20))])


REPLACE = Action(ActionType.MULLIGAN_REPLACE, raw={
    "points": [(438, 820)], "mulligan_index": 0, "selected": True,
})


def test_mulligan_replace_checks_actual_selected_slot():
    before = mulligan()
    assert observed(before).ready(REPLACE)
    after = deepcopy(before)
    after.mulligan_selected = (True, False, False, False)
    assert not observed(before, after).ready(REPLACE)
    after.mulligan_selected = (False, None, False, False)
    assert observed(before, after).ready(REPLACE)
    after.mulligan_selected = (None, False, False, False)
    assert not observed(before, after).ready(REPLACE)


def test_mulligan_confirm_requires_all_selections_stable():
    action = Action(ActionType.CONFIRM)
    before = mulligan()
    assert observed(before).ready(action)
    after = deepcopy(before)
    after.mulligan_selected = (False, True, False, False)
    assert not observed(before, after).ready(action)
    after.mulligan_selected = (False, None, False, False)
    assert not observed(after).ready(action)


def test_combat_confirm_depends_on_prompt_not_unrelated_hand():
    before = state()
    before.action_prompt = "action_confirm"
    after = deepcopy(before)
    after.hand.clear()
    assert observed(before, after).ready(Action(ActionType.CONFIRM))
    after.action_prompt = "action_commit"
    assert not observed(before, after).ready(Action(ActionType.CONFIRM))
    idle = state()
    idle.my_units[0] = replace(idle.my_units[0], rect=Rect(400, 900, 90, 100))
    assert not observed(idle).ready(Action(ActionType.CONFIRM))


@pytest.mark.parametrize("policy_type", [AttackWhenTokenPolicy, SpiderAggroPolicy])
def test_attack_confirmation_from_existing_consumers_uses_row_geometry(policy_type):
    before = state()
    action = policy_type().decide(before)
    assert action == Action(ActionType.CONFIRM)
    gate = ActionReadiness()
    gate.observe(before)
    assert not gate.ready(action)
    after = deepcopy(before)
    after.my_units[0] = replace(after.my_units[0], attack=-1, health=-1)
    after.hand.clear()
    gate.observe(after)
    assert gate.ready(action)
    after.my_units[0] = replace(after.my_units[0], rect=Rect(600, 700, 90, 100))
    gate.observe(after)
    assert not gate.ready(action)


@pytest.mark.parametrize("has_blocker", [False, True])
def test_blocking_confirmation_from_existing_consumer_uses_board_geometry(has_blocker):
    before = state()
    before.ui_state = UIState.BLOCKING
    before.enemy_attackers = list(before.enemy_units)
    before.my_units = ([Unit("blocker", 4, 5, Rect(400, 900, 90, 100))]
                       if has_blocker else [])
    policy = BlockingPolicy()
    first = policy.decide(before)
    assert first.type is (ActionType.BLOCK if has_blocker else ActionType.CONFIRM)
    if has_blocker:
        landed = replace(before, my_units=[
            replace(before.my_units[0], rect=Rect(400, 600, 90, 100))])
        policy.on_action_outcome(first, before, landed)
    action = policy.decide(before)
    assert action == Action(ActionType.CONFIRM)
    assert observed(before).ready(action)
    after = deepcopy(before)
    if has_blocker:
        after.my_units[0] = replace(after.my_units[0], rect=Rect(600, 700, 90, 100))
    else:
        after.enemy_attackers[0] = replace(after.enemy_attackers[0], rect=Rect(600, 200, 90, 100))
    assert not observed(before, after).ready(action)


@pytest.mark.parametrize("ui", [UIState.MY_TURN_IDLE, UIState.BLOCKING])
def test_confirmation_without_prompt_or_relevant_positions_blocks(ui):
    before = GameState(ui_state=ui)
    assert not observed(before).ready(Action(ActionType.CONFIRM))


def test_idle_unit_crossing_attack_row_boundary_blocks_confirmation():
    before = state()
    before.my_units[0] = replace(before.my_units[0], rect=Rect(400, 745, 90, 100))
    after = deepcopy(before)
    after.my_units[0] = replace(after.my_units[0], rect=Rect(400, 755, 90, 100))
    assert not observed(before, after).ready(Action(ActionType.CONFIRM))


def handoff_gate(before, after=None, kind=ActionType.END_TURN, decisions=None):
    """交回优先权：两帧都要由决策选出同一交回动作。"""
    gate = ActionReadiness()
    first, second = decisions or (kind, kind)
    gate.observe(before)
    if first is not None:
        gate.note_decision(Action(first))
    gate.observe(after if after is not None else before)
    if second is not None:
        gate.note_decision(Action(second))
    return gate


@pytest.mark.parametrize("kind", [ActionType.END_TURN, ActionType.PASS])
def test_handoff_waits_for_hand(kind):
    before = state()
    before.hand.pop()  # 此例只检查已知手牌的移动。
    assert handoff_gate(before, kind=kind).ready(Action(kind))
    after = deepcopy(before)
    after.hand.clear()
    assert not handoff_gate(before, after, kind).ready(Action(kind))


@pytest.mark.parametrize("kind", [ActionType.END_TURN, ActionType.PASS])
@pytest.mark.parametrize("collection", ["my_units", "enemy_units", "enemy_attackers"])
def test_handoff_ignores_flickering_board_lists(kind, collection):
    """实机 20261121T085539：展开手牌遮挡+紫色屏障辉光下 my_units
    逐帧 3→3→2→2→2 抖动（不同子集），整表位置证据永不稳定，
    「略過」超时。交回优先权按固定按钮点击，不需要单位列表。"""
    before = state()
    before.hand.pop()
    before.enemy_attackers = list(before.enemy_units)
    before.my_units = [Unit("a", 2, 2, Rect(520, 900, 90, 100)),
                       Unit("b", 1, 2, Rect(680, 900, 90, 100)),
                       Unit("c", 2, 1, Rect(1330, 900, 90, 100))]
    after = deepcopy(before)
    if collection == "my_units":
        del after.my_units[1]
        after.my_units[0] = replace(after.my_units[0], rect=Rect(560, 900, 90, 100))
    else:
        getattr(after, collection).clear()
    assert handoff_gate(before, after, kind).ready(Action(kind))


@pytest.mark.parametrize("decisions", [
    (ActionType.ATTACK, ActionType.END_TURN),
    (ActionType.PLAY_CARD, ActionType.END_TURN),
    (ActionType.NO_OP, ActionType.END_TURN),
    (None, ActionType.END_TURN),
])
def test_handoff_requires_handoff_decided_on_both_frames(decisions):
    """单位抖动让一帧的其他策略失去依据时，不能借这一帧交回优先权。"""
    gate = handoff_gate(state(), decisions=decisions)
    assert not gate.ready(Action(ActionType.END_TURN))


def test_handoff_decision_is_not_carried_over_undecided_frames():
    gate = handoff_gate(state())
    assert gate.ready(Action(ActionType.END_TURN))
    gate.observe(state())  # 本帧未决策（例如等待动作结果）
    assert not gate.ready(Action(ActionType.END_TURN))
    gate.note_decision(Action(ActionType.END_TURN))
    assert gate.ready(Action(ActionType.END_TURN))


@pytest.mark.parametrize("kind", [ActionType.END_TURN, ActionType.PASS])
def test_real_handoff_frames_ignore_nonpositional_recognition_jitter(kind):
    import cv2
    import numpy as np

    from lorwright.core.champions.jinx import PACK
    from lorwright.core.config import load_settings
    from lorwright.core.decide.router import Router
    from lorwright.core.loop.engine import Engine

    engine = Engine(load_settings(), Router([]), None,
                    card_recognizer=PACK.recognize_hand,
                    my_unit_recognizer=PACK.recognize_my_units)
    engine.parser.load()
    gate = ActionReadiness()
    states = []
    for name in ("stop", "observed"):
        image = np.zeros((1080, 1920, 3), np.uint8)
        image[:, 320:] = cv2.imread(
            str(fixtures_root() / f"screens/f1-handoff-readiness-{name}-20261117.png"),
        )
        parsed = engine.parser.parse(image)
        assert parsed.ui_state is UIState.MY_TURN_IDLE
        gate.observe(parsed)
        gate.note_decision(Action(kind))
        states.append(parsed)
    assert len(states[0].hand) == len(states[1].hand) == 6
    assert [unit.health for unit in states[0].enemy_units] != [
        unit.health for unit in states[1].enemy_units
    ]
    assert gate.ready(Action(kind))


def test_real_purple_highlight_phases_keep_attack_readiness():
    import cv2
    import numpy as np

    from lorwright.core.champions.jinx import PACK
    from lorwright.core.config import load_settings
    from lorwright.core.decide.router import Router
    from lorwright.core.loop.engine import Engine

    engine = Engine(load_settings(), Router([]), None,
                    card_recognizer=PACK.recognize_hand,
                    my_unit_recognizer=PACK.recognize_my_units)
    engine.parser.load()
    gate = ActionReadiness()
    action = Action(ActionType.ATTACK, raw={"attackers": [0, 1, 2, 3]})
    for name in ("stop", "current"):
        image = np.zeros((1080, 1920, 3), np.uint8)
        image[:, 320:] = cv2.imread(str(fixtures_root() / f"screens/f1-squirrel-highlighted-{name}-20261118.png"))
        parsed = engine.parser.parse(image)
        assert len(parsed.my_units) == 4
        assert parsed.my_units[-1].name == "吉茵珂絲"
        gate.observe(parsed)
        if name == "stop":
            assert not gate.ready(action)
    assert gate.ready(action)


@pytest.mark.parametrize("kind", [ActionType.END_TURN, ActionType.PASS])
@pytest.mark.parametrize("change", ["card", "unit"])
def test_handoff_ignores_values_not_used_by_its_input(kind, change):
    before = state()
    after = deepcopy(before)
    if change == "card":
        after.hand[0] = replace(after.hand[0], name="", cost=-1, visible_playable_unit=True)
    else:
        after.enemy_units[0] = replace(after.enemy_units[0], attack=-1, health=-1,
                                       name="", keywords=frozenset({"Overwhelm"}))
    assert handoff_gate(before, after, kind).ready(Action(kind))


@pytest.mark.parametrize("kind", [ActionType.END_TURN, ActionType.PASS])
def test_stable_unknown_card_does_not_prevent_handoff(kind):
    assert handoff_gate(state(), kind=kind).ready(Action(kind))


@pytest.mark.parametrize("action", [PLAY, TARGET, ATTACK, BLOCK])
def test_missing_selected_position_blocks(action):
    before = state()
    before.hand[0] = replace(before.hand[0], rect=Rect(100, 800, 0, 0))
    before.my_units[0] = replace(before.my_units[0], rect=Rect(400, 700, 0, 0))
    before.enemy_units[0] = replace(before.enemy_units[0], rect=Rect(400, 200, 0, 0))
    assert not observed(before).ready(action)


def test_attack_default_uses_first_eligible_unit():
    before = state()
    before.my_units.insert(0, replace(before.my_units[0], can_attack=False))
    after = deepcopy(before)
    after.my_units[0] = replace(after.my_units[0], name="unrelated")
    assert observed(before, after).ready(Action(ActionType.ATTACK))
    after.my_units[0] = replace(after.my_units[0], can_attack=True)
    assert not observed(before, after).ready(Action(ActionType.ATTACK))


@pytest.mark.parametrize("kind", [ActionType.COLLAPSE_HAND, ActionType.CANCEL])
def test_fixed_layout_action_still_requires_two_stable_baselines(kind):
    current = state()
    gate = ActionReadiness()
    gate.observe(current)
    assert not gate.ready(Action(kind))
    gate.observe(current)
    assert gate.ready(Action(kind))


def test_skip_choice_requires_corresponding_ui():
    current = state()
    action = Action(ActionType.SKIP_CHOICE)
    assert not observed(current).ready(action)
    current.ui_state = UIState.OPTIONAL_CHOICE
    assert observed(current).ready(action)


def test_mulligan_replacement_allows_button_jitter():
    before = mulligan()
    after = deepcopy(before)
    after.mulligan_cards[0] = replace(after.mulligan_cards[0], rect=Rect(438, 810, 16, 20))
    assert observed(before, after).ready(REPLACE)


def test_continue_button_must_exist_and_stay_in_place():
    before = state()
    action = Action(ActionType.CONTINUE)
    assert observed(before).ready(action)
    after = deepcopy(before)
    after.continue_button = None
    assert not observed(before, after).ready(action)
    after.continue_button = Rect(1400, 800, 100, 50)
    assert not observed(before, after).ready(action)


@pytest.mark.parametrize("interrupt", ["stale", "reset"])
def test_interrupt_requires_two_new_frames(interrupt):
    gate = observed(state())
    assert gate.ready(PLAY)
    if interrupt == "stale":
        gate.observe(None)
    else:
        gate.reset()
    assert not gate.ready(PLAY)
    gate.observe(state())
    assert not gate.ready(PLAY)
    gate.observe(state())
    assert gate.ready(PLAY)


def test_snapshots_survive_mutation_before_and_after_next_observation():
    first = state()
    gate = ActionReadiness()
    gate.observe(first)
    first.hand.clear()
    first.action_prompt = "changed"
    second = state()
    gate.observe(second)
    second.hand.clear()
    second.ui_state = UIState.UNKNOWN
    assert gate.ready(PLAY)


def test_reusing_mutable_state_preserves_previous_observation():
    current = state()
    gate = ActionReadiness()
    gate.observe(current)
    current.hand[0] = replace(current.hand[0], rect=Rect(200, 800, 100, 150))
    gate.observe(current)
    assert not gate.ready(PLAY)
    gate.observe(current)
    assert gate.ready(PLAY)


def _u(attack, health, x, y=900, name="", can_attack=True):
    return Unit(name, attack, health, Rect(x, y, 90, 100), can_attack=can_attack)


def _blocking(my, attackers):
    return GameState(ui_state=UIState.BLOCKING, my_units=list(my),
                     enemy_attackers=list(attackers))


# 会话 20261121T082646-f1ba8045411e：6 个友军带脉冲屏障/紫色辉光，
# my_units 实机 3→5→6→5→4 抖动，blocking 决策在 block/confirm 间
# 翻转、就绪两帧整表证据永不稳定而超时。

def test_block_ready_when_chosen_blocker_and_attacker_are_stable():
    attacker = _u(4, 1, 500, 300)
    blocker = _u(2, 3, 400)
    before = _blocking([_u(9, 9, 100), blocker], [attacker])
    after = _blocking([blocker, _u(8, 8, 800)], [attacker])
    action = Action(ActionType.BLOCK, raw={"pairs": [(0, 0)]})
    assert observed(before, after).ready(action)


def test_block_abstains_when_chosen_blocker_is_not_stable():
    attacker = _u(4, 1, 500, 300)
    before = _blocking([_u(2, 3, 400)], [attacker])
    after = _blocking([_u(2, 3, 560)], [attacker])
    action = Action(ActionType.BLOCK, raw={"pairs": [(0, 0)]})
    assert not observed(before, after).ready(action)


def test_block_abstains_when_attacker_is_not_stable():
    blocker = _u(2, 3, 400)
    before = _blocking([blocker], [_u(4, 1, 500, 300)])
    after = _blocking([blocker], [_u(4, 1, 660, 300)])
    action = Action(ActionType.BLOCK, raw={"pairs": [(0, 0)]})
    assert not observed(before, after).ready(action)


def test_blocking_confirm_ready_under_bench_flicker():
    attacker = _u(4, 1, 520, 300)
    lane = _u(4, 3, 500, 650)  # 行内已锁定指派
    bench = [_u(1, 1, 700), _u(2, 2, 850)]
    before = _blocking([lane, *bench, _u(3, 3, 1000)], [attacker])
    after = _blocking([lane, *bench], [attacker])
    assert observed(before, after).ready(Action(ActionType.CONFIRM))


def test_blocking_confirm_abstains_when_unit_moved():
    attacker = _u(4, 1, 520, 300)
    before = _blocking([_u(4, 3, 500, 650), _u(2, 3, 400)], [attacker])
    # 后排单位同数值换位置：是真实移动而非漏读，继续等待。
    after = _blocking([_u(4, 3, 500, 650), _u(2, 3, 560)], [attacker])
    assert not observed(before, after).ready(Action(ActionType.CONFIRM))


def test_blocking_confirm_ready_when_attacker_stats_flicker():
    # 会话 20261121T154222：紫色格挡辉光下維克特数值读不稳，
    # 攻击者已锁定行内，位置即身份，数值抖动不应阻断确认。
    lane = _u(4, 3, 500, 650)
    before = _blocking([lane, _u(1, 1, 700)], [_u(10, 8, 520, 300)])
    after = _blocking([lane, _u(1, 1, 700)], [_u(0, 0, 520, 300)])
    assert observed(before, after).ready(Action(ActionType.CONFIRM))


def test_blocking_confirm_ready_when_attackers_drop_out_entirely():
    # 会话 20261121T155018 停止帧 enemy_units_visible=null：辉光下
    # 攻击者整单位读不出 = 本帧不可验证而非指派变化，跳过该通道。
    before = _blocking([_u(6, 3, 400)], [_u(10, 8, 520, 300)])
    after = _blocking([_u(6, 3, 400)], [])
    assert observed(before, after).ready(Action(ActionType.CONFIRM))


def test_blocking_confirm_ready_when_committed_blocker_stats_flicker():
    # 行内格挡者同理：数值在辉光下抖动不改已锁定指派。
    before = _blocking([_u(4, 3, 500, 650), _u(1, 1, 700)], [_u(4, 1, 520, 300)])
    after = _blocking([_u(0, 0, 500, 650), _u(1, 1, 700)], [_u(4, 1, 520, 300)])
    assert observed(before, after).ready(Action(ActionType.CONFIRM))


def test_blocking_confirm_abstains_when_attacker_unstable():
    lane = _u(4, 3, 500, 650)
    before = _blocking([lane, _u(1, 1, 700)], [_u(4, 1, 520, 300)])
    after = _blocking([lane, _u(1, 1, 700)], [_u(4, 1, 680, 300)])
    assert not observed(before, after).ready(Action(ActionType.CONFIRM))


def test_repeatedly_swallowed_block_falls_through_to_confirm():
    # 会话 20261121T155018：攻击者被不可见格挡者覆盖时每次拖拽
    # 都是无效落点，同一计划连吞三次后确认收尾而非无限重拖。
    policy = BlockingPolicy()
    attacker = _u(10, 8, 500, 300)
    blocker = _u(10, 3, 400)  # 攻击≥敌方生命，能互换，必有计划
    state = _blocking([blocker], [attacker])
    for _ in range(3):
        action = policy.decide(state)
        assert action.type is ActionType.BLOCK
        # 拖拽被吞：后态与先态一致，无单位上移。
        policy.on_action_outcome(action, state, state)
    assert policy.decide(state).type is ActionType.CONFIRM


def test_swallowed_count_resets_when_block_lands():
    # 落位一次即清零：前两次被吞、第三次落位后仍回到 BLOCK→CONFIRM 常态。
    policy = BlockingPolicy()
    attacker = _u(10, 8, 500, 300)
    blocker = _u(10, 3, 400)
    lane = _u(10, 3, 400, 650)   # 格挡行位（中心 y=700 < 后排 950-120）
    state = _blocking([blocker], [attacker])
    landed = _blocking([lane], [attacker])
    for _ in range(2):
        action = policy.decide(state)
        policy.on_action_outcome(action, state, state)
    action = policy.decide(state)
    policy.on_action_outcome(action, state, landed)
    assert policy.decide(state).type is ActionType.CONFIRM  # _declared 已置位


def test_blocking_policy_plans_only_over_stable_units():
    stable_blocker = _u(2, 3, 400)
    attacker = _u(4, 1, 500, 300)
    state = GameState(
        ui_state=UIState.BLOCKING,
        my_units=[stable_blocker, _u(1, 1, 800)],
        enemy_attackers=[attacker],
        my_units_stable=frozenset({0}),
        enemy_units_stable=frozenset({0}),
    )
    action = BlockingPolicy().decide(state)
    assert action.type is ActionType.BLOCK
    assert action.raw["pairs"] == [(0, 0)]


def test_attack_ready_when_chosen_attacker_is_stable():
    attacker = _u(3, 3, 400)
    before = GameState(ui_state=UIState.MY_TURN_IDLE,
                       my_units=[_u(9, 9, 100), attacker])
    after = GameState(ui_state=UIState.MY_TURN_IDLE,
                      my_units=[attacker, _u(8, 8, 800)])
    action = Action(ActionType.ATTACK, raw={"attackers": [0]})
    assert observed(before, after).ready(action)


def test_attack_abstains_when_chosen_attacker_is_not_stable():
    before = GameState(ui_state=UIState.MY_TURN_IDLE,
                       my_units=[_u(3, 3, 400)])
    after = GameState(ui_state=UIState.MY_TURN_IDLE,
                      my_units=[_u(3, 3, 560)])
    action = Action(ActionType.ATTACK, raw={"attackers": [0]})
    assert not observed(before, after).ready(action)


def test_attack_policy_skips_unstable_attackers():
    state = GameState(
        ui_state=UIState.MY_TURN_IDLE, has_attack_token=True,
        my_units=[_u(3, 3, 400), _u(2, 2, 600)],
        my_units_stable=frozenset({1}),
    )
    action = AttackWhenTokenPolicy().decide(state)
    assert action.type is ActionType.ATTACK
    assert action.raw["attackers"] == (1,)


def test_enemy_target_ignores_glow_icon_jitter_on_chosen_unit():
    """可选中紫色辉光下图标证据（可攻击/关键词/眩晕）逐帧抖动，
    选敌只需所选单位跨帧同一（位置+名字/数值）。"""
    before = state()
    after = deepcopy(before)
    after.enemy_units[0] = replace(after.enemy_units[0], can_attack=True,
                                   keywords=frozenset({"Barrier"}), stunned=True)
    after.my_units.append(Unit("flicker", 1, 1, Rect(900, 900, 90, 100)))
    assert observed(before, after).ready(TARGET)
    after.enemy_units[0] = replace(after.enemy_units[0], health=1)
    assert not observed(before, after).ready(TARGET)


def attack_declared():
    s = state()
    s.my_units = [Unit("lane", 2, 2, Rect(500, 600, 90, 100)),
                  Unit("bench", 1, 2, Rect(700, 900, 90, 100)),
                  Unit("bench2", 2, 1, Rect(900, 900, 90, 100))]
    return s


def test_attack_confirm_ignores_back_row_flicker():
    before = attack_declared()
    after = deepcopy(before)
    del after.my_units[1]
    after.my_units.append(Unit("hidden", 3, 3, Rect(1100, 900, 0, 0)))
    assert observed(before, after).ready(Action(ActionType.CONFIRM))


def test_attack_confirm_tolerates_lane_unit_missing_one_frame():
    before = attack_declared()
    before.my_units.insert(1, Unit("lane2", 3, 1, Rect(700, 600, 90, 100)))
    after = attack_declared()
    assert observed(before, after).ready(Action(ActionType.CONFIRM))


@pytest.mark.parametrize("change", ["new_lane_unit", "moved", "empty_lane"])
def test_attack_confirm_waits_when_declared_lane_changes(change):
    before = attack_declared()
    after = deepcopy(before)
    if change == "new_lane_unit":
        after.my_units.append(Unit("late", 3, 1, Rect(900, 600, 90, 100)))
    elif change == "moved":
        # 后排单位真实走进攻击行：前一帧在后排、本帧在行内，同一身份。
        after.my_units[1] = replace(after.my_units[1], rect=Rect(700, 600, 90, 100))
    else:
        after.my_units = after.my_units[1:]
    assert not observed(before, after).ready(Action(ActionType.CONFIRM))
