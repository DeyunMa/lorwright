"""合成状态序列驱动真实 Engine，验证输入等待与安全停机。不是实机操作录像。"""

import time
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
import pytest

from lorwright.core.config import Settings
from lorwright.core.decide.router import RouteResult
from lorwright.core.device.base import Frame
from lorwright.core.loop.engine import Engine
from lorwright.core.models import (
    Action,
    ActionType,
    CardInHand,
    GameState,
    Layout,
    Reading,
    Rect,
    UIState,
    Unit,
)


class Device:
    name = "synthetic"

    def __init__(self):
        self.taps = []
        self.drags = []
        self.closed = False
        self.frames = 0

    def size(self):
        return (1920, 1080)

    def screencap(self):
        self.frames += 1
        return Frame(image=np.zeros((1080, 1920, 3), np.uint8))

    def tap(self, *point):
        self.taps.append(point)

    def drag(self, *args):
        self.drags.append(args)

    def close(self):
        self.closed = True


class Router:
    layers = []

    def __init__(self, actions):
        self.actions = iter(actions)
        self.calls = 0

    def decide(self, state):
        self.calls += 1
        return RouteResult(next(self.actions), "synthetic")

    def coverage(self):
        return {}


def test_jinx_rebuild_uses_special_window_and_advances_once(monkeypatch):
    from lorwright.core.champions.jinx.policy import JinxOpeningPolicy

    cards = [CardInHand(i, "吉茵珂絲" if i == 2 else "", 2 if i == 2 else 1,
                        Rect(400 + i * 80, 800, 50, 50)) for i in range(6)]
    before = ready(hand=cards, hand_expanded=True)
    after = ready(hand=[replace(cards[0], index=i) for i in range(7)],
                  mana=1, readings={"mana": Reading(1, 0)},
                  my_units=[Unit("", 6, 7, Rect(1000, 850, 100, 150))])
    animation = replace(after, ui_state=UIState.UNKNOWN, hand=after.hand[:4])
    engine, device, router, events, snapshots = engine_for(
        monkeypatch, [before, animation, after],
        [Action(ActionType.PLAY_CARD, card_index=2), Action(ActionType.NO_OP)], timeout=8,
    )
    policy = JinxOpeningPolicy()
    policy._board_before = 10
    router.layers = [policy]
    monkeypatch.setattr("lorwright.core.loop.engine.time.monotonic", lambda: device.frames * 6.0)
    engine.run(max_ticks=3)
    outcomes = [e for e in events if e.get("event") == "action_outcome"]
    assert [e["status"] for e in outcomes] == ["waiting", "succeeded"]
    assert outcomes[-1]["reason"] == "jinx_hand_rebuilt_and_summoned"
    assert policy.step == 2
    assert len(device.drags) == 1
    assert router.calls == 2
    assert snapshots == []


def test_inspect_board_collapses_once_then_attacks(monkeypatch):
    from lorwright.core.decide.generic import AttackWhenTokenPolicy, ExpandHandPolicy
    from lorwright.core.decide.router import Router as RealRouter

    card = CardInHand(0, "spell", 3, Rect(400, 800, 80, 100))
    expanded = ready(hand=[card], hand_expanded=True, has_attack_token=True)
    unit = Unit("unit", 1, 1, Rect(500, 850, 50, 50))
    collapsed = ready(hand=[card], has_attack_token=True, my_units=[unit])
    engine, device, _, _, _ = engine_for(monkeypatch, [expanded, collapsed], [])
    engine.layout.collapse_hand_point = Rect(499, 619, 2, 2)
    engine.layout.attack_row = Rect(700, 470, 520, 70)
    engine.router = RealRouter([ExpandHandPolicy(), AttackWhenTokenPolicy()])
    engine.run(max_ticks=2)
    assert device.taps == [(500, 620)]
    assert len(device.drags) == 1


@pytest.mark.parametrize("ui,action", [
    (UIState.UNKNOWN, Action(ActionType.NO_OP, raw={"inspect_board": True})),
    (UIState.TARGETING, Action(ActionType.NO_OP)),
    (UIState.MY_TURN_IDLE, Action(ActionType.NO_OP)),
])
def test_board_inspection_never_overrides_unrelated_wait(monkeypatch, ui, action):
    state = ready(ui_state=ui, hand_expanded=True, has_attack_token=True)
    engine, device, _, _, _ = engine_for(monkeypatch, [state], [action])
    engine.layout.collapse_hand_point = Rect(499, 619, 2, 2)
    engine.run(max_ticks=1)
    assert device.taps == []


@pytest.mark.parametrize("transition", [True, False])
def test_reward_timeout_clicks_once_and_requires_known_transition(monkeypatch, transition):
    fixtures = Path(__file__).parent / "fixtures/reward_timeout"
    timeout = cv2.imread(str(fixtures / "f1.png"))
    home = cv2.imread(str(fixtures / "f1-after-home.png"))
    engine, device, router, _, snapshots = engine_for(
        monkeypatch, [GameState(ui_state=UIState.UNKNOWN)], [],
    )
    images = iter([timeout] + ([timeout, home] if transition else [timeout] * 6))
    monkeypatch.setattr(device, "screencap", lambda: Frame(image=next(images)))
    monkeypatch.setattr(engine, "_wait", lambda seconds: None)
    result = engine.run(max_ticks=1)
    assert device.taps == [(960, 757)]
    assert router.calls == 0
    assert result.reason == ("reward_timeout_transition" if transition
                             else "reward_timeout_transition_unverified")
    assert bool(snapshots) is not transition


def ready(**kwargs):
    values = dict(
        ui_state=UIState.MY_TURN_IDLE, mana=3,
        readings={"mana": Reading(3, 0), "nexus_hp": Reading(20, 0),
                  "enemy_nexus_hp": Reading(20, 0)},
    )
    values.update(kwargs)
    return GameState(**values)


def engine_for(monkeypatch, states, actions, timeout=8):
    settings = Settings()
    settings.loop.tick_ms = 0
    settings.loop.action_timeout_s = timeout
    settings.act.tap_wait_ms = settings.act.expand_wait_ms = settings.act.drag_wait_ms = 0
    device = Device()
    router = Router(actions)
    layout = Layout(end_turn=Rect(10, 10, 20, 20), hand_region=Rect(100, 800, 300, 200),
                    play_area=Rect(500, 500, 100, 100))
    engine = Engine(settings, router, device, layout=layout)
    sequence = iter(states)
    monkeypatch.setattr(engine.parser, "load", lambda: None)
    monkeypatch.setattr(engine, "_build_state", lambda image: next(sequence))
    events, snapshots = [], []
    monkeypatch.setattr("lorwright.core.loop.engine.emit", lambda **event: events.append(event))
    monkeypatch.setattr("lorwright.core.loop.engine.save_snapshot", lambda *args, **kw: snapshots.append(kw))
    return engine, device, router, events, snapshots


@pytest.mark.parametrize("action_type", [ActionType.ATTACK, ActionType.END_TURN])
def test_unrelated_missing_readings_do_not_block_attack_or_end_turn(monkeypatch, action_type):
    state = ready(
        hand=[CardInHand(0, "", 1, Rect(200, 900, 8, 8))],
        has_attack_token=True, my_units=[Unit("unit", 1, 1, Rect(200, 700, 50, 50))],
        readings={"mana": Reading(10, 1), "nexus_hp": Reading(20, 1)},
    )
    engine, device, router, _, _ = engine_for(monkeypatch, [state], [Action(action_type)])
    engine.layout.attack_row = Rect(500, 400, 100, 50)
    engine.run(max_ticks=1)
    assert router.calls == 1
    assert bool(device.drags) is (action_type is ActionType.ATTACK)
    assert bool(device.taps) is (action_type is ActionType.END_TURN)


@pytest.mark.parametrize("change", [
    {"has_attack_token": False},
    {"my_units": []},
    {"my_units": [Unit("unit", 1, 1, Rect(200, 700, 50, 50), can_attack=False)]},
])
def test_attack_still_requires_priority_and_an_eligible_unit(monkeypatch, change):
    values = dict(has_attack_token=True, my_units=[Unit("unit", 1, 1, Rect(200, 700, 50, 50))],
                  readings={})
    values.update(change)
    engine, device, _, events, _ = engine_for(
        monkeypatch, [ready(**values)], [Action(ActionType.ATTACK)],
    )
    engine.run(max_ticks=1)
    assert not device.drags and not device.taps
    assert events[-1]["missing_readings"] == ["attack_priority"]


@pytest.mark.parametrize("action,spell_reading,cost,expected", [
    (Action(ActionType.PLAY_CARD, card_index=0, raw={"spell_mana_only": True}), Reading(3, 0), 1, True),
    (Action(ActionType.PLAY_CARD, card_index=0), Reading(3, 0), 1, False),
    (Action(ActionType.END_TURN), Reading(3, 0), 1, False),
    (Action(ActionType.PLAY_CARD, card_index=0, raw={"spell_mana_only": True}), Reading(3, 1), 1, False),
    (Action(ActionType.PLAY_CARD, card_index=0, raw={"spell_mana_only": True}), Reading(3, 0), 4, False),
])
def test_paid_spell_requires_fresh_resources_but_does_not_block_end_turn(
    monkeypatch, action, spell_reading, cost, expected
):
    s = ready(hand_expanded=True, hand=[CardInHand(0, "砰砰", cost, Rect(200, 900, 8, 8))],
              enemy_units=[Unit("", 2, 1, Rect(500, 200, 20, 20))], spell_mana=3,
              readings={"mana": Reading(None, None), "spell_mana": spell_reading,
                        "nexus_hp": Reading(20, 0)})
    engine, device, _, _, _ = engine_for(monkeypatch, [s], [action])
    engine.run(max_ticks=1)
    assert bool(device.drags) is expected
    assert bool(device.taps) is (action.type is ActionType.END_TURN)


def test_manual_empty_hand_allows_attack_with_unreadable_mana(monkeypatch):
    state = ready(has_attack_token=True,
                  my_units=[Unit("unit", 1, 1, Rect(200, 700, 50, 50))],
                  readings={"mana": Reading(10, 1), "nexus_hp": Reading(20, 0)})
    engine, device, _, _, _ = engine_for(monkeypatch, [state], [Action(ActionType.ATTACK)])
    engine.layout.attack_row = Rect(500, 400, 100, 50)
    engine._confirm_empty_hand_once = True
    engine.run(max_ticks=1)
    assert device.drags and not device.taps


def test_manual_empty_hand_allows_only_one_frame_to_attack(monkeypatch):
    state = ready(has_attack_token=True,
                  my_units=[Unit("unit", 1, 1, Rect(200, 700, 50, 50))],
                  readings={"mana": Reading(10, 1), "nexus_hp": Reading(20, 0)})
    later = replace(state)
    engine, device, router, _, _ = engine_for(
        monkeypatch, [state, later], [Action(ActionType.NO_OP), Action(ActionType.END_TURN)],
    )
    engine._confirm_empty_hand_once = True
    engine.run(max_ticks=2)
    assert router.calls == 2
    assert state.hand_empty_confirmed and not later.hand_empty_confirmed
    assert not device.drags and device.taps == [(20, 20)]


@pytest.mark.parametrize("action_type", [ActionType.PLAY_CARD, ActionType.END_TURN, ActionType.CONFIRM])
def test_manual_empty_hand_only_permits_attack_even_with_fresh_mana(monkeypatch, action_type):
    state = ready(has_attack_token=True, my_units=[Unit("unit", 1, 1, Rect(200, 700, 50, 50))])
    engine, device, _, _, _ = engine_for(monkeypatch, [state], [Action(action_type)])
    engine._confirm_empty_hand_once = True
    engine.run(max_ticks=1)
    assert not device.drags and not device.taps


def test_manual_empty_hand_conflicting_card_consumes_confirmation(monkeypatch):
    card = CardInHand(0, "", 1, Rect(300, 800, 50, 50))
    state = ready(hand=[card])
    later = ready(readings={"mana": Reading(10, 1), "nexus_hp": Reading(20, 0)},
                  has_attack_token=True, my_units=[Unit("unit", 1, 1, Rect(200, 700, 50, 50))])
    engine, device, router, _, _ = engine_for(
        monkeypatch, [state, later], [Action(ActionType.END_TURN)],
    )
    engine._confirm_empty_hand_once = True
    engine.run(max_ticks=2)
    assert router.calls == 1
    assert not later.hand_empty_confirmed
    assert not device.drags and device.taps == [(20, 20)]


def test_expand_then_drag_waits_for_result_without_repeating_input(monkeypatch):
    card = CardInHand(0, "", 1, Rect(300, 800, 50, 50))
    collapsed = ready(hand=[card])
    expanded = replace(collapsed, hand_expanded=True)
    paid = replace(expanded, hand=[], mana=2, readings={**expanded.readings, "mana": Reading(2, 0)})
    engine, device, router, events, _ = engine_for(
        monkeypatch, [collapsed, expanded, expanded, paid],
        [Action(ActionType.PLAY_CARD, 0), Action(ActionType.PLAY_CARD, 0), Action(ActionType.NO_OP)],
    )
    engine.run(max_ticks=4)
    assert len(device.taps) == 1
    assert len(device.drags) == 1
    attempts = [e for e in events if e.get("event") == "play_card_attempt"]
    assert len(attempts) == 2
    assert attempts[1]["card_index"] == 0
    assert attempts[1]["card"]["cost"] == 1
    assert attempts[1]["hand_expanded"] is True
    assert attempts[1]["plan"]["points"][0] == (325, 825)
    assert router.calls == 3
    assert [e["status"] for e in events if e.get("event") == "action_outcome"] == [
        "succeeded", "waiting", "succeeded",
    ]
    assert device.closed


def test_unrecognized_target_stops_without_input(monkeypatch):
    s = ready(ui_state=UIState.TARGETING)
    engine, device, _, _, snapshots = engine_for(
        monkeypatch, [s, s], [Action(ActionType.NO_OP)], timeout=0,
    )
    result = engine.run(max_ticks=2)
    assert result.reason == "unknown_target"
    assert snapshots[-1]["tag"] == "unknown_target"
    assert not device.drags and not device.taps


def test_target_wait_deadline_survives_unknown_frame(monkeypatch):
    targeting = ready(ui_state=UIState.TARGETING)
    unknown = ready(ui_state=UIState.UNKNOWN)
    engine, device, _, _, _ = engine_for(
        monkeypatch, [targeting, unknown], [Action(ActionType.NO_OP)], timeout=0,
    )
    assert engine.run(max_ticks=2).reason == "unknown_target"
    assert not device.drags and not device.taps


def test_successful_outcome_is_delivered_to_policy_once(monkeypatch):
    card = CardInHand(0, "牌", 1, Rect(300, 800, 50, 50))
    before = ready(hand=[card], hand_expanded=True)
    after = replace(before, hand=[], mana=2, readings={**before.readings, "mana": Reading(2, 0)})
    action = Action(ActionType.PLAY_CARD, 0)
    engine, _, router, _, _ = engine_for(
        monkeypatch, [before, before, after], [action, Action(ActionType.NO_OP)],
    )

    class Observer:
        def __init__(self):
            self.outcomes = []

        def on_action_outcome(self, action, before, after):
            self.outcomes.append((action, before, after))

    observer = Observer()
    router.layers = [observer]
    engine.run(max_ticks=3)
    assert observer.outcomes == [(action, before, after)]


def test_staged_spell_is_confirmed_before_notifying_policy(monkeypatch):
    card = CardInHand(0, "火箭", 1, Rect(300, 800, 50, 50))
    before = ready(hand=[card], hand_expanded=True)
    staged = replace(before, ui_state=UIState.COMBAT_RESOLVING)
    after = replace(staged, ui_state=UIState.ENEMY_TURN, hand=[], mana=2,
                    readings={**staged.readings, "mana": Reading(2, 0)})
    play = Action(ActionType.PLAY_CARD, 0)
    confirm = Action(ActionType.CONFIRM)
    engine, device, router, events, _ = engine_for(
        monkeypatch, [before, staged, after], [play, confirm, Action(ActionType.NO_OP)],
    )

    class Observer:
        def __init__(self):
            self.outcomes = []

        def on_action_outcome(self, action, old, new):
            self.outcomes.append((action, old, new))

    observer = Observer()
    router.layers = [observer]
    engine.run(max_ticks=3)
    assert len(device.drags) == 1
    assert device.taps == [(20, 20)]
    assert (play, before, after) in observer.outcomes
    assert any(event.get("reason") == "confirmation_required" for event in events)


def test_unknown_animation_waits_for_spell_confirmation(monkeypatch):
    card = CardInHand(0, "火箭", 1, Rect(300, 800, 50, 50))
    before = ready(hand=[card], hand_expanded=True)
    units = [Unit("", -1, -1, Rect(x, 900, 8, 8)) for x in (700, 850)]
    animation = replace(before, ui_state=UIState.UNKNOWN, hand=[], my_units=units,
                        readings={**before.readings, "mana": Reading(3, 1)})
    staged = replace(animation, ui_state=UIState.COMBAT_RESOLVING)
    after = replace(staged, ui_state=UIState.ENEMY_TURN, mana=2,
                    readings={**staged.readings, "mana": Reading(2, 0)})
    play = Action(ActionType.PLAY_CARD, 0)
    engine, device, router, events, _ = engine_for(
        monkeypatch, [before, animation, staged, after],
        [play, Action(ActionType.CONFIRM), Action(ActionType.NO_OP)],
    )
    engine.run(max_ticks=4)
    assert len(device.drags) == 1
    assert device.taps == [(20, 20)]
    assert router.calls == 3
    assert [event["status"] for event in events if event.get("event") == "action_outcome"] == [
        "waiting", "needs_input", "succeeded",
    ]


def test_staged_spell_is_not_reported_as_played_when_confirm_times_out(monkeypatch):
    card = CardInHand(0, "火箭", 1, Rect(300, 800, 50, 50))
    before = ready(hand=[card], hand_expanded=True)
    staged = replace(before, ui_state=UIState.COMBAT_RESOLVING)
    engine, device, router, _, snapshots = engine_for(
        monkeypatch, [before, staged, staged],
        [Action(ActionType.PLAY_CARD, 0), Action(ActionType.CONFIRM)],
    )
    monkeypatch.setattr(
        "lorwright.core.loop.engine.time.monotonic", lambda: 20.0 if device.frames >= 3 else 0.0,
    )

    class Observer:
        def __init__(self):
            self.outcomes = []

        def on_action_outcome(self, action, old, new):
            self.outcomes.append(action.type)

    observer = Observer()
    router.layers = [observer]
    engine.run(max_ticks=3)
    assert len(device.drags) == 1 and device.taps == [(20, 20)]
    assert ActionType.PLAY_CARD not in observer.outcomes
    assert snapshots == [{"tag": "action_timeout"}]


def test_two_rockets_each_wait_for_confirmation_and_verified_payment(monkeypatch):
    from lorwright.core.champions.jinx.policy import JinxOpeningPolicy
    from lorwright.core.decide.generic import CombatConfirmPolicy
    from lorwright.core.decide.router import Router as RealRouter

    def rocket(index):
        return CardInHand(index, "超威能死亡火箭！", 1, Rect(300 + index * 100, 800, 50, 50))

    readings = {"mana": Reading(0, 0), "spell_mana": Reading(2, 0),
                "nexus_hp": Reading(20, 0), "enemy_nexus_hp": Reading(20, 0)}
    first = ready(mana=0, spell_mana=2, hand=[rocket(0), rocket(1)],
                  hand_expanded=True, readings=readings)
    staged_first = replace(first, ui_state=UIState.COMBAT_RESOLVING)
    second = replace(first, hand=[rocket(0)], spell_mana=1,
                     readings={**readings, "spell_mana": Reading(1, 0)})
    staged_second = replace(second, ui_state=UIState.COMBAT_RESOLVING)
    after = replace(second, hand=[], spell_mana=0,
                    readings={**readings, "spell_mana": Reading(0, 0)})
    engine, device, _, _, snapshots = engine_for(
        monkeypatch, [first, staged_first, second, staged_second, after], [],
    )
    policy = JinxOpeningPolicy(jinx_summoned=True)
    engine.router = RealRouter([policy, CombatConfirmPolicy()])
    engine.run(max_ticks=5)
    assert len(device.drags) == 2
    assert device.taps[:2] == [(20, 20), (20, 20)]
    assert policy._rockets_played == 2
    assert snapshots == []


def test_rocket_confirmation_waits_through_animation_and_counts_once(monkeypatch):
    from lorwright.core.champions.jinx.policy import JinxOpeningPolicy
    from lorwright.core.decide.generic import CombatConfirmPolicy
    from lorwright.core.decide.router import Router as RealRouter

    cards = [CardInHand(i, "超威能死亡火箭！", 1, Rect(300 + i * 100, 800, 50, 50))
             for i in range(2)]
    before = ready(mana=8, hand=cards, hand_expanded=True,
                   readings={"mana": Reading(8, 0), "nexus_hp": Reading(20, 0)})
    staged = replace(before, ui_state=UIState.COMBAT_RESOLVING)
    animation = replace(staged, ui_state=UIState.UNKNOWN, hand=cards[:1])
    blocking = replace(before, ui_state=UIState.BLOCKING, hand=cards[:1], mana=7,
                       readings={**before.readings, "mana": Reading(7, 0)})
    engine, device, _, _, snapshots = engine_for(
        monkeypatch, [before, staged, animation, blocking], [],
    )
    policy = JinxOpeningPolicy(jinx_summoned=True)
    engine.router = RealRouter([policy, CombatConfirmPolicy()])
    clock = [0.0]
    monkeypatch.setattr("lorwright.core.loop.engine.time.monotonic", lambda: clock[0])
    build = engine._build_state
    times = iter([0.0, 1.0, 10.0, 12.0])

    def next_state(image):
        clock[0] = next(times)
        return build(image)

    monkeypatch.setattr(engine, "_build_state", next_state)
    engine.run(max_ticks=4)
    assert len(device.drags) == 1 and device.taps == [(20, 20)]
    assert policy._rockets_played == 1
    assert snapshots == []


def test_staged_spell_stops_when_confirmation_does_not_prove_play(monkeypatch):
    card = CardInHand(0, "火箭", 1, Rect(300, 800, 50, 50))
    before = ready(hand=[card], hand_expanded=True)
    staged = replace(before, ui_state=UIState.COMBAT_RESOLVING)
    after = replace(staged, ui_state=UIState.MY_TURN_IDLE)
    engine, device, router, _, snapshots = engine_for(
        monkeypatch, [before, staged, after],
        [Action(ActionType.PLAY_CARD, 0), Action(ActionType.CONFIRM)],
    )
    result = engine.run(max_ticks=3)
    assert result.status == "stopped" and result.reason == "staged_play_unverified"
    assert len(device.drags) == 1 and device.taps == [(20, 20)]
    assert router.calls == 2
    assert snapshots == [{"tag": "staged_play_unverified"}]


def test_stale_mulligan_decision_does_not_skip_to_confirmation(monkeypatch):
    from lorwright.core.champions.jinx.policy import JinxOpeningPolicy
    from lorwright.core.decide.router import Router as RealRouter
    from lorwright.core.models import MulliganCard

    cards = [MulliganCard(i, False, Rect(100 + i * 100, 100, 8, 8))
             for i in range(4)]
    mulligan = ready(ui_state=UIState.MULLIGAN, mulligan_cards=cards,
                     mulligan_selected=(False,) * 4)
    engine, device, _, events, _ = engine_for(monkeypatch, [mulligan, mulligan], [])
    engine.router = RealRouter([JinxOpeningPolicy()])
    ages = iter([0, 10, 0, 0])
    monkeypatch.setattr(Frame, "age_s", lambda self: next(ages))
    engine.run(max_ticks=2)
    assert device.taps == [cards[0].rect.center]
    assert any(event.get("reason") == "frame_expired_during_decision" for event in events)


@pytest.mark.parametrize("settled", [True, False])
def test_combat_confirm_waits_for_settlement_without_repeating(monkeypatch, settled):
    combat = ready(ui_state=UIState.COMBAT_RESOLVING)
    animation = replace(combat, ui_state=UIState.UNKNOWN)
    final = replace(combat, ui_state=UIState.ENEMY_TURN) if settled else animation
    engine, device, router, events, snapshots = engine_for(
        monkeypatch, [combat, animation, final],
        [Action(ActionType.CONFIRM), Action(ActionType.NO_OP)],
    )
    decide = router.decide
    monkeypatch.setattr(router, "decide", lambda state: replace(decide(state), layer="combat_confirm"))
    clock = [0.0]
    monkeypatch.setattr("lorwright.core.loop.engine.time.monotonic", lambda: clock[0])
    build = engine._build_state
    times = iter([0.0, 10.0, 12.0 if settled else 20.0])

    def next_state(image):
        clock[0] = next(times)
        return build(image)

    monkeypatch.setattr(engine, "_build_state", next_state)
    result = engine.run(max_ticks=3)
    outcomes = [e["status"] for e in events if e.get("event") == "action_outcome"]
    assert outcomes == ["waiting", "succeeded" if settled else "timed_out"]
    assert device.taps == [(20, 20)]
    assert snapshots == ([] if settled else [{"tag": "action_timeout"}])
    if not settled:
        assert result.reason == "action_timeout"
        assert router.calls == 1


def test_combat_confirm_wait_can_be_stopped(monkeypatch):
    from lorwright.core.runtime.session import StopRequested

    combat = ready(ui_state=UIState.COMBAT_RESOLVING)
    animation = replace(combat, ui_state=UIState.UNKNOWN)
    engine, device, router, _, _ = engine_for(
        monkeypatch, [combat, animation], [Action(ActionType.CONFIRM)],
    )
    decide = router.decide
    monkeypatch.setattr(router, "decide", lambda state: replace(decide(state), layer="combat_confirm"))

    def stop_after_animation():
        if device.frames >= 2:
            raise StopRequested()

    monkeypatch.setattr("lorwright.core.loop.engine.checkpoint", stop_after_animation)
    with pytest.raises(StopRequested):
        engine.run(max_ticks=4)
    assert device.taps == [(20, 20)]
    assert router.calls == 1
    assert device.closed


def test_timeout_saves_evidence_and_stops_without_retry_or_restart(monkeypatch):
    state = ready(ui_state=UIState.MULLIGAN)
    engine, device, router, events, snapshots = engine_for(
        monkeypatch, [state, state], [Action(ActionType.CONFIRM)], timeout=0,
    )
    engine.run(max_ticks=10)
    assert router.calls == 1
    assert device.taps == [(20, 20)]
    assert snapshots == [{"tag": "action_timeout"}]
    assert any(e.get("status") == "timed_out" for e in events)
    assert device.closed and device.frames == 2


def test_unchanged_play_timeout_stops_before_repeating_drag(monkeypatch):
    hand = [CardInHand(0, "unit", 3, Rect(200, 800, 8, 8))]
    state = ready(hand=hand, hand_expanded=True)
    engine, device, router, events, snapshots = engine_for(
        monkeypatch, [state] * 3,
        [Action(ActionType.PLAY_CARD, card_index=0)] * 2, timeout=0,
    )
    result = engine.run(max_ticks=3)
    assert result.reason == "action_timeout"
    assert router.calls == 1
    assert len(device.drags) == 1
    assert snapshots == [{"tag": "action_timeout"}]
    assert any(e.get("status") == "timed_out" for e in events)


def test_battle_end_returns_to_outer_loop_without_repeating_pending_action(monkeypatch):
    engine, device, router, _, _ = engine_for(
        monkeypatch, [ready(), ready(ui_state=UIState.BATTLE_END)],
        [Action(ActionType.END_TURN)],
    )
    engine.run(max_ticks=5)
    assert device.taps == [(20, 20)]
    assert device.frames == 2
    assert router.calls == 1
    assert engine._pending is None


def test_paid_card_waits_for_its_resource_evidence_then_resumes(monkeypatch):
    card = CardInHand(0, "unit", 3, Rect(200, 900, 8, 8))
    current = ready(hand=[card], hand_expanded=True)
    stale = replace(current, readings={**current.readings, "mana": Reading(3, 1)})
    play = Action(ActionType.PLAY_CARD, 0)
    engine, device, router, events, _ = engine_for(
        monkeypatch, [stale, current], [play, play],
    )
    engine.run(max_ticks=2)
    assert router.calls == 2
    assert len(device.drags) == 1
    assert events[0]["layer"] == "unreadable"
    assert events[0]["missing_readings"] == ["mana"]


def test_unreadable_mana_is_masked_for_decision_but_does_not_block_end_turn(monkeypatch):
    state = ready(mana=10, spell_mana=3,
                  readings={"mana": Reading(10, 1), "spell_mana": Reading(3, 1)})
    engine, device, router, _, _ = engine_for(
        monkeypatch, [state], [Action(ActionType.END_TURN)],
    )
    decide = router.decide
    observed = []

    def inspect(s):
        observed.append((s.mana, s.spell_mana))
        return decide(s)

    monkeypatch.setattr(router, "decide", inspect)
    engine.run(max_ticks=1)
    assert observed == [(-1, None)]
    assert state.mana == 10 and state.spell_mana == 3
    assert device.taps == [(20, 20)]


@pytest.mark.parametrize("cost,can_play", [(0, True), (1, False), (-1, False)])
def test_unknown_mana_does_not_become_free_mana(monkeypatch, cost, can_play):
    state = ready(hand_expanded=True,
                  hand=[CardInHand(0, "unit", cost, Rect(200, 900, 8, 8))], readings={})
    engine, device, _, _, _ = engine_for(
        monkeypatch, [state], [Action(ActionType.PLAY_CARD, 0)],
    )
    engine.run(max_ticks=1)
    assert bool(device.drags) is can_play


@pytest.mark.parametrize("ui,reason,budget", [
    (UIState.UNKNOWN, "unknown_ui", 8),
    (UIState.MULLIGAN, "no_action", 8),
    (UIState.ENEMY_TURN, "enemy_turn", 60),
])
def test_core_stops_unresolved_waits_without_an_external_observer(monkeypatch, ui, reason, budget):
    state = ready(ui_state=ui)
    actions = [] if ui is UIState.UNKNOWN else [Action(ActionType.NO_OP)] * 2
    engine, device, _, _, snapshots = engine_for(monkeypatch, [state] * 2, actions)
    monkeypatch.setattr(
        "lorwright.core.loop.engine.time.monotonic", lambda: float((device.frames - 1) * budget),
    )
    result = engine.run(max_ticks=5)
    assert (result.status, result.reason) == ("stopped", reason)
    assert snapshots == [{"tag": reason}]
    assert not device.taps and not device.drags
    assert device.frames == 2


def test_missing_payment_evidence_is_bounded_and_saves_the_reason(monkeypatch):
    state = ready(hand_expanded=True, readings={},
                  hand=[CardInHand(0, "unit", 2, Rect(300, 900, 20, 20))])
    engine, device, _, _, snapshots = engine_for(
        monkeypatch, [state] * 2, [Action(ActionType.PLAY_CARD, 0)] * 2,
    )
    monkeypatch.setattr("lorwright.core.loop.engine.time.monotonic",
                        lambda: float((device.frames - 1) * 8))
    result = engine.run(max_ticks=5)
    assert result.reason == "action_preconditions_unverified"
    assert engine._stop_details["missing_readings"] == ["mana"]
    assert snapshots == [{"tag": "action_preconditions_unverified"}]
    assert not device.drags


@pytest.mark.parametrize("champion,name,kwargs,cost,spell_mana", [
    ("jinx", "爆破幫菜鳥", {}, 0, None),
    ("elise", "蜘蛛哨兵", {}, 0, None),
    ("jinx", "應急裝置", {}, 1, 3),
    ("jinx", "超威能死亡火箭！", {"jinx_summoned": True}, 1, 3),
])
def test_real_policies_use_free_cards_or_fresh_spell_mana_without_other_readings(
    monkeypatch, champion, name, kwargs, cost, spell_mana,
):
    from lorwright.cli.app import _battle_layers
    from lorwright.core.champions import load
    from lorwright.core.decide.router import Router as RealRouter

    state = ready(hand_expanded=True, mana=10, spell_mana=spell_mana,
                  hand=[CardInHand(0, name, cost, Rect(300, 900, 20, 20))],
                  readings={"mana": Reading(10, 1), "spell_mana": Reading(spell_mana, 0)})
    engine, device, _, _, _ = engine_for(monkeypatch, [state], [])
    engine.router = RealRouter(_battle_layers(load(champion), policy_kwargs=kwargs))
    engine.run(max_ticks=1)
    assert len(device.drags) == 1
    assert not device.taps


def test_unknown_cards_do_not_require_agent_commands_to_finish_battle(monkeypatch):
    from lorwright.cli.app import _battle_layers
    from lorwright.core.champions import load
    from lorwright.core.decide.router import Router as RealRouter

    card = CardInHand(0, "", 1, Rect(300, 900, 20, 20))
    unit = Unit("", 1, 1, Rect(500, 850, 20, 20))
    start = ready(hand=[card], hand_expanded=True, has_attack_token=True, my_units=[unit],
                  readings={})
    combat = replace(start, ui_state=UIState.COMBAT_RESOLVING,
                     my_units=[replace(unit, rect=Rect(500, 450, 20, 20))])
    enemy = replace(start, ui_state=UIState.ENEMY_TURN, has_attack_token=False)
    next_turn = replace(enemy, ui_state=UIState.MY_TURN_IDLE)
    end = replace(enemy, ui_state=UIState.BATTLE_END)
    engine, device, _, _, snapshots = engine_for(
        monkeypatch, [start, combat, enemy, next_turn, end], [],
    )
    engine.router = RealRouter(_battle_layers(load("jinx"), policy_kwargs={"jinx_summoned": True}))
    engine.layout.attack_row = Rect(700, 470, 520, 70)
    result = engine.run(max_ticks=10)
    assert (result.status, result.reason) == ("completed", "battle_end")
    assert len(device.drags) == 1
    assert device.taps == [(20, 20), (20, 20)]
    assert snapshots == []


def test_unknown_state_never_reaches_a_strategy(monkeypatch):
    engine, device, router, _, _ = engine_for(monkeypatch, [GameState()], [])
    engine.run(max_ticks=1)
    assert router.calls == 0
    assert device.taps == []


def test_frame_that_expires_during_decision_is_not_executed(monkeypatch):
    engine, device, router, events, _ = engine_for(
        monkeypatch, [ready()], [Action(ActionType.END_TURN)],
    )
    frame = device.screencap()
    frame.ts = time.time()
    monkeypatch.setattr(device, "screencap", lambda: frame)
    decide = router.decide

    def slow_decide(state):
        # 模拟决策时已经经过100秒，不真实等待。
        frame.ts -= 100
        return decide(state)

    monkeypatch.setattr(router, "decide", slow_decide)
    engine.run(max_ticks=1)
    assert device.taps == []
    assert engine._pending is None
    assert engine._skipped_stale == 1
    assert events[-1]["reason"] == "frame_expired_during_decision"


def test_pending_action_times_out_even_if_every_followup_frame_is_stale(monkeypatch):
    state = ready(ui_state=UIState.MULLIGAN)
    engine, device, router, events, snapshots = engine_for(
        monkeypatch, [state, state], [Action(ActionType.CONFIRM)], timeout=0,
    )
    capture = device.screencap

    def frames():
        frame = capture()
        if device.frames > 1:
            frame.ts = time.time() - 100
        return frame

    monkeypatch.setattr(device, "screencap", frames)
    engine.run(max_ticks=10)
    assert router.calls == 1
    assert device.frames == 2
    assert len(device.taps) == 1
    assert snapshots == [{"tag": "action_timeout"}]
    assert events[-1]["reason"] == "no_fresh_frame_before_deadline"
