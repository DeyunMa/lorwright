"""满场替换提示：六位数值修复 + 「選擇1個單位或地標進行替換」处理。"""

from dataclasses import replace

import cv2
import pytest

from lorwright.cli.app import _battle_layers
from lorwright.core.act.translate import ActionTranslator
from lorwright.core.champions import load
from lorwright.core.config import load_settings
from lorwright.core.decide.generic import ReplacePromptPolicy
from lorwright.core.decide.router import Router
from lorwright.core.loop.outcome import ActionOutcome, OutcomeStatus
from lorwright.core.loop.readiness import ActionReadiness
from lorwright.core.models import (
    Action,
    ActionType,
    GameState,
    Rect,
    TargetedSpell,
    UIState,
    Unit,
)
from lorwright.core.perceive.replace_prompt import replace_unit_prompt
from lorwright.core.perceive.state import StateParser
from lorwright.core.perceive.ui_state import UIStateDetector
from tools.test_data import fixtures_root

FRAME = "screens/f1-board-full-replace-20261121.png"


def _image():
    image = cv2.imread(str(fixtures_root() / FRAME))
    assert image is not None
    return image


def _parse(image):
    layout = load_settings().layout.to_layout()
    parser = StateParser(layout, UIStateDetector(action_button=layout.end_turn))
    parser.load()
    return parser.parse(image)


def test_full_board_reads_all_six_friendly_units():
    state = _parse(_image())
    assert state.ui_state is UIState.TARGETING
    assert [(u.attack, u.health) for u in state.my_units] == [
        (1, 1), (1, 1), (10, 8), (3, 2), (1, 1), (1, 1),
    ]


def test_replace_prompt_detected_on_real_frame():
    state = _parse(_image())
    assert state.replace_prompt is True


@pytest.mark.parametrize("name", [
    "1080p_targeting.png", "1080p_battle_turn2.png", "1080p_block_phase.png",
    "1080p_mulligan.png", "f1-discard-spurious-anchor-20261121.png",
    "f1-required-choice-20261121.png", "f1-optional-choice-20261116.png",
])
def test_replace_prompt_not_detected_on_other_frames(name):
    image = cv2.imread(str(fixtures_root() / f"screens/{name}"))
    assert image is not None
    assert replace_unit_prompt(image) is False


def test_masked_prompt_is_not_detected():
    image = _image()
    image[519:573, 160:830] = 0
    assert replace_unit_prompt(image) is False
    assert _parse(image).replace_prompt is False


@pytest.mark.parametrize("champion", ["jinx", "elise"])
def test_replace_prompt_routes_to_weakest_friendly(champion):
    state = _parse(_image())
    routed = Router(_battle_layers(load(champion))).decide(state)
    assert routed.action.type is ActionType.SELECT_TARGET
    assert routed.action.raw == {"enemy": False, "index": 0}
    assert routed.layer == "replace_prompt"
    plan = ActionTranslator(load_settings().layout.to_layout()).translate(
        routed.action, state)
    # 点击落在最左 1/1 单位的拖拽点内。
    target = state.my_units[0].rect
    assert plan is not None
    assert plan.points == [target.center]


def test_weakest_pick_skips_named_champion_and_unreadable():
    state = GameState(
        ui_state=UIState.TARGETING, replace_prompt=True,
        my_units=[
            Unit("吉茵珂絲", 4, 3, Rect(0, 0, 8, 8)),
            Unit("", -1, -1, Rect(100, 0, 8, 8)),
            Unit("", 1, 1, Rect(200, 0, 8, 8)),
            Unit("", 1, 1, Rect(300, 0, 8, 8)),
        ],
    )
    routed = Router(_battle_layers(load("jinx"))).decide(state)
    assert routed.layer == "replace_prompt"
    assert routed.action.raw["index"] == 2  # 最左的无名 1/1


def test_replace_select_is_ready_without_targeted_spell():
    state = _parse(_image())
    assert state.targeted_spell is None
    action = Action(ActionType.SELECT_TARGET, raw={"enemy": False, "index": 0})
    gate = ActionReadiness()
    gate.observe(state)
    gate.observe(replace(state))
    assert gate.ready(action)


def test_replace_select_succeeds_when_targeting_closes():
    before = GameState(ui_state=UIState.TARGETING, replace_prompt=True,
                       my_units=[Unit("", 1, 1, Rect(0, 0, 8, 8))])
    action = Action(ActionType.SELECT_TARGET, raw={"enemy": False, "index": 0})
    after = replace(before, ui_state=UIState.MY_TURN_IDLE)
    assert ActionOutcome(action, before, 8).observe(after, 1).status is OutcomeStatus.SUCCEEDED
    stayed = replace(before)
    assert ActionOutcome(action, before, 8).observe(stayed, 8).status is OutcomeStatus.TIMED_OUT


def test_play_card_into_replace_prompt_still_needs_input():
    before = GameState(ui_state=UIState.MY_TURN_IDLE, hand_expanded=True)
    after = replace(before, ui_state=UIState.TARGETING, replace_prompt=True)
    outcome = ActionOutcome(Action(ActionType.PLAY_CARD, card_index=0), before, 8).observe(after, 1)
    assert outcome.status is OutcomeStatus.NEEDS_INPUT
    assert outcome.reason == "target_selection_required"


CONFIRM_FRAME = "screens/f1-replace-confirm-20261121.png"


def _confirm_image():
    image = cv2.imread(str(fixtures_root() / CONFIRM_FRAME))
    assert image is not None
    return image


def test_replace_confirm_button_reads_as_combat_resolving():
    """「替換」按钮：满场替换后的确认文字，与「結算」同走确认路径。"""
    state = _parse(_confirm_image())
    assert state.ui_state is UIState.COMBAT_RESOLVING
    assert state.action_prompt == "action_replace"


def test_replace_confirm_routes_to_confirm_clicking_action_button():
    state = _parse(_confirm_image())
    routed = Router(_battle_layers(load("jinx"))).decide(state)
    assert routed.action.type is ActionType.CONFIRM
    assert routed.layer == "combat_confirm"
    layout = load_settings().layout.to_layout()
    plan = ActionTranslator(layout).translate(routed.action, state)
    assert plan is not None and plan.points == [layout.end_turn.center]


def test_confirm_succeeds_on_known_successor_after_replace():
    before = _parse(_confirm_image())
    action = Action(ActionType.CONFIRM)
    after = replace(before, ui_state=UIState.MY_TURN_IDLE, action_prompt=None)
    outcome = ActionOutcome(action, before, 8).observe(after, 1)
    assert outcome.status is OutcomeStatus.SUCCEEDED
    assert outcome.reason == "ui_transition"


def _flicker_state(*units):
    return GameState(ui_state=UIState.TARGETING, replace_prompt=True,
                     my_units=list(units))


def _flicker_unit(attack, health, x, name=""):
    return Unit(name, attack, health, Rect(x, 900, 80, 90))


def test_replace_target_ready_when_only_the_target_is_stable():
    # 会话 20261121T081430-122ba723c656：紫色替换辉光下 my_units 在
    # 3→4→3→6→4 间抖动，按整表证据两帧永不稳定而超时；替换动作只需要
    # 「所选目标跨两帧是同一单位」。
    weakest = _flicker_unit(1, 1, 400)
    strong = _flicker_unit(4, 3, 600)
    first = _flicker_state(_flicker_unit(2, 2, 100), weakest, strong)
    second = _flicker_state(weakest, strong, _flicker_unit(1, 2, 800))
    policy = ReplacePromptPolicy()
    gate = ActionReadiness()
    gate.observe(first)
    assert policy.decide(first) is not None
    gate.observe(second)
    action = policy.decide(second)
    # 跨帧稳定集合 {weakest, strong}，策略选中其中最弱者（index 0）。
    assert action.raw == {"enemy": False, "index": 0}
    assert gate.ready(action)


def test_replace_target_abstains_when_no_unit_is_stable():
    first = _flicker_state(_flicker_unit(1, 1, 400), _flicker_unit(4, 3, 600))
    second = _flicker_state(_flicker_unit(1, 1, 480), _flicker_unit(4, 3, 700))
    gate = ActionReadiness()
    gate.observe(first)
    gate.observe(second)
    action = Action(ActionType.SELECT_TARGET, raw={"enemy": False, "index": 0})
    assert not gate.ready(action)


def test_replace_target_abstains_when_action_targets_unstable_unit():
    # 稳定集合只有 4|3；动作指向只在本帧出现的 1|1，不能放行。
    strong = _flicker_unit(4, 3, 600)
    first = _flicker_state(strong)
    second = _flicker_state(_flicker_unit(1, 1, 400), strong, _flicker_unit(9, 9, 800))
    gate = ActionReadiness()
    gate.observe(first)
    gate.observe(second)
    action = Action(ActionType.SELECT_TARGET, raw={"enemy": False, "index": 0})
    assert not gate.ready(action)


def test_replace_target_moved_unit_is_not_the_same_unit():
    weakest = _flicker_unit(1, 1, 400)
    strong = _flicker_unit(4, 3, 600)
    first = _flicker_state(weakest, strong)
    # 1|1 同数值但位置移到 560（超出 12px 容差）→ 跨帧不匹配，弃权。
    second = _flicker_state(strong, _flicker_unit(1, 1, 560))
    gate = ActionReadiness()
    gate.observe(first)
    gate.observe(second)
    action = Action(ActionType.SELECT_TARGET, raw={"enemy": False, "index": 1})
    assert not gate.ready(action)


def test_replace_select_other_states_still_use_full_evidence():
    # 非替换场景（有 targeted_spell）不进入目标身份路径，维持原有
    # 整表证据要求：my_units 增减时必须不稳定。
    targeted = GameState(
        ui_state=UIState.TARGETING,
        targeted_spell=TargetedSpell("spell", Rect(900, 500, 80, 80)),
        my_units=[_flicker_unit(1, 1, 400)],
    )
    grown = replace(targeted, my_units=[_flicker_unit(1, 1, 400),
                                        _flicker_unit(2, 2, 600)])
    gate = ActionReadiness()
    gate.observe(targeted)
    gate.observe(grown)
    # 法术目标动作不受本修复影响：索引 0 在两帧同单位时仍可稳定。
    assert gate.ready(Action(ActionType.SELECT_TARGET,
                             raw={"enemy": False, "index": 0}))
    moved = replace(grown, my_units=[_flicker_unit(1, 1, 700),
                                     _flicker_unit(2, 2, 600)])
    gate = ActionReadiness()
    gate.observe(grown)
    gate.observe(moved)
    assert not gate.ready(Action(ActionType.SELECT_TARGET,
                                 raw={"enemy": False, "index": 0}))
