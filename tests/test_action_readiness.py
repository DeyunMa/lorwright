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
ATTACK = Action(ActionType.ATTACK, raw={"attackers": [0]})
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
    {"name": "other"}, {"cost": 3}, {"drag_point_valid": False},
    {"rect": Rect(150, 800, 100, 150)}, {"drag_point": (900, 900)},
    {"rect": Rect(100, 800, 0, 150)},
])
def test_play_checks_selected_card(change):
    before = state()
    after = deepcopy(before)
    after.hand[0] = replace(after.hand[0], **change)
    assert not observed(before, after).ready(PLAY)


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
        policy.on_action_outcome(first, before, before)
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


@pytest.mark.parametrize("kind", [ActionType.END_TURN, ActionType.PASS])
@pytest.mark.parametrize("collection", ["hand", "my_units", "enemy_units", "enemy_attackers"])
def test_handoff_waits_for_hand_and_board(kind, collection):
    before = state()
    before.hand.pop()  # 此例只检查已知手牌的移动。
    before.enemy_attackers = list(before.enemy_units)
    assert observed(before).ready(Action(kind))
    after = deepcopy(before)
    getattr(after, collection).clear()
    assert not observed(before, after).ready(Action(kind))


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
            f"tests/fixtures/screens/f1-handoff-readiness-{name}-20261117.png",
        )
        parsed = engine.parser.parse(image)
        assert parsed.ui_state is UIState.MY_TURN_IDLE
        gate.observe(parsed)
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
        image[:, 320:] = cv2.imread(f"tests/fixtures/screens/f1-squirrel-highlighted-{name}-20261118.png")
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
    assert observed(before, after).ready(Action(kind))


@pytest.mark.parametrize("kind", [ActionType.END_TURN, ActionType.PASS])
def test_stable_unknown_card_does_not_prevent_handoff(kind):
    assert observed(state()).ready(Action(kind))


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
    current.hand[0] = replace(current.hand[0], name="changed")
    gate.observe(current)
    assert not gate.ready(PLAY)
    gate.observe(current)
    assert gate.ready(PLAY)
