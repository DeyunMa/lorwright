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


@pytest.mark.parametrize("action_type,allowed", [
    (ActionType.ATTACK, True),
    (ActionType.PLAY_CARD, False),
    (ActionType.END_TURN, False),
    (ActionType.CONFIRM, False),
])
def test_stale_mana_only_allows_attack_with_confirmed_empty_hand(monkeypatch, action_type, allowed):
    state = ready(
        hand_empty_confirmed=True, has_attack_token=True,
        my_units=[Unit("unit", 1, 1, Rect(200, 700, 50, 50))],
        readings={"mana": Reading(10, 1), "nexus_hp": Reading(20, 0)},
    )
    engine, device, router, events, _ = engine_for(
        monkeypatch, [state], [Action(action_type)],
    )
    engine.layout.attack_row = Rect(500, 400, 100, 50)
    engine.run(max_ticks=1)

    assert router.calls == 1
    assert bool(device.drags) is allowed
    assert not device.taps
    if not allowed:
        assert events[-1]["layer"] == "unreadable"


@pytest.mark.parametrize("change", [
    {"hand_empty_confirmed": False},
    {"has_attack_token": False},
    {"my_units": []},
    {"readings": {"mana": Reading(10, 1), "nexus_hp": Reading(20, 1)}},
])
def test_stale_mana_requires_all_attack_evidence(monkeypatch, change):
    values = dict(hand_empty_confirmed=True, has_attack_token=True,
                  my_units=[Unit("unit", 1, 1, Rect(200, 700, 50, 50))],
                  readings={"mana": Reading(10, 1), "nexus_hp": Reading(20, 0)})
    values.update(change)
    engine, device, router, _, _ = engine_for(monkeypatch, [ready(**values)], [])
    engine.run(max_ticks=1)
    assert router.calls == 0
    assert not device.drags and not device.taps


@pytest.mark.parametrize("action,spell_reading,cost,expected", [
    (Action(ActionType.PLAY_CARD, card_index=0, raw={"spell_mana_only": True}), Reading(3, 0), 1, True),
    (Action(ActionType.PLAY_CARD, card_index=0), Reading(3, 0), 1, False),
    (Action(ActionType.END_TURN), Reading(3, 0), 1, False),
    (Action(ActionType.PLAY_CARD, card_index=0, raw={"spell_mana_only": True}), Reading(3, 1), 1, False),
    (Action(ActionType.PLAY_CARD, card_index=0, raw={"spell_mana_only": True}), Reading(3, 0), 4, False),
])
def test_unreadable_mana_only_allows_verified_spell_mana_action(
    monkeypatch, action, spell_reading, cost, expected
):
    s = ready(hand_expanded=True, hand=[CardInHand(0, "砰砰", cost, Rect(200, 900, 8, 8))],
              enemy_units=[Unit("", 2, 1, Rect(500, 200, 20, 20))], spell_mana=3,
              readings={"mana": Reading(None, None), "spell_mana": spell_reading,
                        "nexus_hp": Reading(20, 0)})
    engine, device, _, _, _ = engine_for(monkeypatch, [s], [action])
    engine.run(max_ticks=1)
    assert bool(device.drags) is expected
    assert not device.taps


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
        monkeypatch, [state, later], [Action(ActionType.NO_OP)],
    )
    engine._confirm_empty_hand_once = True
    engine.run(max_ticks=2)
    assert router.calls == 1
    assert state.hand_empty_confirmed and not later.hand_empty_confirmed
    assert not device.drags and not device.taps


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
    engine, device, router, _, _ = engine_for(monkeypatch, [state, later], [])
    engine._confirm_empty_hand_once = True
    engine.run(max_ticks=2)
    assert router.calls == 0
    assert not later.hand_empty_confirmed
    assert not device.drags and not device.taps


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
    clock = iter([0.0, 0.0, 0.0, 20.0])
    monkeypatch.setattr("lorwright.core.loop.engine.time.monotonic", lambda: next(clock))

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


def test_old_readings_block_decision_then_resume_when_fresh(monkeypatch):
    current = ready()
    stale = replace(current, readings={**current.readings, "mana": Reading(3, 1)})
    engine, device, router, events, _ = engine_for(
        monkeypatch, [stale, current], [Action(ActionType.END_TURN)],
    )
    engine.run(max_ticks=2)
    assert router.calls == 1
    assert len(device.taps) == 1
    assert events[0]["layer"] == "unreadable"
    assert events[0]["readings"]["mana"] == {"value": 3, "age_frames": 1}


def test_zero_mana_unreadable_still_allows_ending_turn(monkeypatch):
    # 同一段优先权中先确认 0 费，再连续 5 帧读不出时允许结束回合。
    state = ready(
        mana=0,
        readings={"mana": Reading(None, None), "nexus_hp": Reading(20, 0),
                  "enemy_nexus_hp": Reading(20, 0)},
    )
    confirmed = replace(state, readings={**state.readings, "mana": Reading(0, 0)})
    engine, device, router, _, _ = engine_for(
        monkeypatch, [confirmed, *([state] * 5)],
        [Action(ActionType.NO_OP), Action(ActionType.END_TURN)], timeout=0,
    )
    engine.run(max_ticks=6)
    assert router.calls == 2
    assert len(device.taps) == 1


def test_unreadable_mana_is_not_assumed_zero_without_confirmation(monkeypatch):
    state = ready(readings={"mana": Reading(None, None), "nexus_hp": Reading(20, 0)})
    engine, device, router, _, _ = engine_for(
        monkeypatch, [state] * 5, [Action(ActionType.END_TURN)],
    )
    engine.run(max_ticks=5)
    assert router.calls == 0
    assert device.taps == []


def test_zero_mana_confirmation_does_not_cross_priority_change(monkeypatch):
    confirmed = ready(mana=0, readings={"mana": Reading(0, 0), "nexus_hp": Reading(20, 0)})
    enemy = ready(ui_state=UIState.ENEMY_TURN)
    unreadable = ready(readings={"mana": Reading(None, None), "nexus_hp": Reading(20, 0)})
    engine, device, router, _, _ = engine_for(
        monkeypatch, [confirmed, enemy, *([unreadable] * 5)],
        [Action(ActionType.NO_OP), Action(ActionType.NO_OP), Action(ActionType.END_TURN)],
    )
    engine.run(max_ticks=7)
    assert router.calls == 2
    assert device.taps == []


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
