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


@pytest.mark.parametrize("closed", [False, True])
def test_discard_sends_once_then_verifies_exit_or_times_out(monkeypatch, closed):
    from lorwright.core.models import DiscardCandidates

    candidates = DiscardCandidates((Rect(200, 600, 50, 50),), ((1.0,),), (1,))
    discard = ready(ui_state=UIState.DISCARD)
    after = ready() if closed else discard
    engine, device, router, events, snapshots = engine_for(
        monkeypatch, [discard, discard, ready(ui_state=UIState.UNKNOWN), after],
        [Action(ActionType.NO_OP)], check_readiness=True,
    )
    monkeypatch.setattr("lorwright.core.loop.engine.discard_candidates", lambda *_: candidates)
    monkeypatch.setattr("lorwright.core.loop.engine.time.monotonic",
                        lambda: 20.0 if device.frames >= 4 and not closed else 0.0)
    callbacks = []

    class Layer:
        def on_action_outcome(self, action, *_):
            callbacks.append(action.type)

    router.layers = [Layer()]
    engine.run(max_ticks=4)
    assert device.taps == [(225, 625)]
    assert router.calls == (1 if closed else 0)
    assert callbacks == ([ActionType.DISCARD_CARD] if closed else [])
    assert snapshots == ([] if closed else [{"tag": "action_timeout"}])
    outcomes = [event for event in events if event.get("event") == "action_outcome"]
    assert outcomes[0]["status"] == "waiting"
    assert outcomes[-1]["status"] == ("succeeded" if closed else "timed_out")
    if closed:
        assert outcomes[-1]["reason"] == "discard_selection_closed"


def test_play_choice_reroutes_without_play_success_then_verifies_skip(monkeypatch):
    before = ready(hand_expanded=True,
                   hand=[CardInHand(0, "", 1, Rect(200, 900, 80, 100))])
    choice = replace(before, ui_state=UIState.OPTIONAL_CHOICE)
    engine, device, router, events, snapshots = engine_for(
        monkeypatch, [before, choice, choice, before],
        [Action(ActionType.PLAY_CARD, card_index=0), Action(ActionType.SKIP_CHOICE),
         Action(ActionType.NO_OP)],
    )
    callbacks = []

    class Layer:
        def on_action_outcome(self, action, *_):
            callbacks.append(action.type)

    router.layers = [Layer()]
    engine.run(max_ticks=4)
    assert len(device.drags) == 1
    assert device.taps == [(20, 20)]
    assert router.calls == 3
    assert callbacks == [ActionType.SKIP_CHOICE]
    assert snapshots == []
    outcomes = [event for event in events if event.get("event") == "action_outcome"]
    assert [(event["status"], event["reason"]) for event in outcomes] == [
        ("needs_input", "optional_choice_required"),
        ("waiting", "awaiting_visible_result"),
        ("succeeded", "optional_choice_closed"),
    ]


@pytest.mark.parametrize("closed", [False, True])
def test_optional_skip_is_sent_once_and_waits_for_visible_exit(monkeypatch, closed):
    choice = ready(ui_state=UIState.OPTIONAL_CHOICE)
    successor = ready() if closed else choice
    engine, device, router, events, snapshots = engine_for(
        monkeypatch, [choice, choice, successor],
        [Action(ActionType.SKIP_CHOICE), Action(ActionType.NO_OP)],
    )
    monkeypatch.setattr("lorwright.core.loop.engine.time.monotonic",
                        lambda: 20.0 if device.frames >= 3 and not closed else 0.0)
    engine.run(max_ticks=3)
    assert device.taps == [(20, 20)]
    assert router.calls == (2 if closed else 1)
    assert bool(snapshots) is not closed
    outcomes = [event for event in events if event.get("event") == "action_outcome"]
    assert outcomes[-1]["status"] == ("succeeded" if closed else "timed_out")
    if closed:
        assert outcomes[-1]["reason"] == "optional_choice_closed"


@pytest.mark.parametrize("previous_count", [0, 1])
def test_pass_yields_to_new_opponent_board_without_success_callback(monkeypatch, previous_count):
    unit = Unit("", 2, 2, Rect(900, 100, 100, 150))
    before = ready(hand_expanded=True, enemy_units=[unit] * previous_count,
                   readings={"enemy_units_visible": Reading(
                       previous_count or None, 0 if previous_count else None,
                   )})
    after = replace(before, enemy_units=[unit] * (previous_count + 1),
                    readings={"enemy_units_visible": Reading(previous_count + 1, 0)})
    engine, device, router, events, snapshots = engine_for(
        monkeypatch, [before, after],
        [Action(ActionType.END_TURN), Action(ActionType.NO_OP)],
    )
    callbacks = []

    class Layer:
        def on_action_outcome(self, *args):
            callbacks.append(args)

    router.layers = [Layer()]
    engine.run(max_ticks=2)
    assert router.calls == 2
    assert len(device.taps) == 1
    assert callbacks == []
    assert snapshots == []
    outcomes = [e for e in events if e.get("event") == "action_outcome"]
    assert [(e["status"], e["reason"]) for e in outcomes] == [
        ("needs_input", "opponent_unit_appeared"),
    ]


@pytest.mark.parametrize("filename,previous_count,expected_count", [
    ("f1-pass-new-opponent-20261116.png", 0, 1),
    ("1080p_units_idle.png", 1, 2),
])
def test_real_parsed_opponent_board_reroutes_engine(
    monkeypatch, filename, previous_count, expected_count,
):
    from lorwright.core.config import load_settings
    from lorwright.core.models import ClickPlan
    from lorwright.core.perceive.digits import DigitReader
    from lorwright.core.perceive.state import StateParser
    from lorwright.core.perceive.ui_state import UIStateDetector

    image = cv2.imread(str(Path("tests/fixtures/screens") / filename))
    assert image is not None
    settings = load_settings()
    layout = settings.layout.to_layout()
    parser = StateParser(layout, UIStateDetector(action_button=layout.end_turn), DigitReader())
    parser.load()
    after = parser.parse(image)
    assert after.ui_state is UIState.MY_TURN_IDLE
    assert len(after.enemy_units) == expected_count
    # 后帧为真实实拍；前态删减单位以隔离增员，不作为连续录像证据。
    before = replace(after, enemy_units=after.enemy_units[:previous_count], readings={
        **after.readings, "enemy_units_visible": Reading(
            previous_count or None, 0 if previous_count else None,
        ),
    })
    engine, device, router, events, snapshots = engine_for(
        monkeypatch, [], [Action(ActionType.END_TURN), Action(ActionType.NO_OP)],
    )
    monkeypatch.setattr(device, "screencap", lambda: Frame(image=image.copy()))
    frames = iter([before, None])

    def build(image):
        initial = next(frames)
        return initial if initial is not None else parser.parse(image)

    monkeypatch.setattr(engine, "_build_state", build)
    monkeypatch.setattr(engine.translator, "translate", lambda *_: ClickPlan([(20, 20)], wait_ms=0))
    callbacks = []

    class Observer:
        def on_action_outcome(self, *args):
            callbacks.append(args)

    router.layers = [Observer()]
    engine.run(max_ticks=2)
    assert device.taps == [(20, 20)] and not device.drags
    assert router.calls == 2 and callbacks == [] and snapshots == []
    outcomes = [event for event in events if event.get("event") == "action_outcome"]
    assert [(event["status"], event["reason"]) for event in outcomes] == [
        ("needs_input", "opponent_unit_appeared"),
    ]


@pytest.mark.parametrize("successor,elapsed,expected", [
    (UIState.BATTLE_END, 30, "battle_end"),
    (UIState.UNKNOWN, 63, "battle_result_transition_unverified"),
    (UIState.BATTLE_END, 63, "battle_result_transition_unverified"),
    (UIState.MY_TURN_IDLE, 12, "action_timeout"),
])
def test_known_result_transition_observes_without_replaying_or_renewing_action(
    monkeypatch, successor, elapsed, expected,
):
    before = ready(ui_state=UIState.TARGETING,
                   enemy_units=[Unit("", 1, 1, Rect(800, 400, 8, 8))])
    unknown = ready(ui_state=UIState.UNKNOWN)
    engine, device, router, events, snapshots = engine_for(
        monkeypatch, [before, unknown, unknown, ready(ui_state=successor)],
        [Action(ActionType.SELECT_TARGET, raw={"enemy": True, "index": 0})],
    )
    image = np.zeros((1080, 1920, 3), np.uint8)
    image[100:900, 300:1600] = cv2.imread(
        "tests/fixtures/continue/f1-result-transition-20261117.png",
    )
    times = [0, 2, 12, elapsed]

    def capture():
        device.frames += 1
        return Frame(image=image if device.frames in (2, 3) else np.zeros_like(image))

    monkeypatch.setattr(device, "screencap", capture)
    monkeypatch.setattr("lorwright.core.loop.engine.time.monotonic",
                        lambda: times[min(device.frames - 1, 3)])
    result = engine.run(max_ticks=4)
    assert result.reason == expected
    assert device.taps == [(804, 404)]
    assert router.calls == 1
    outcomes = [event for event in events if event.get("event") == "action_outcome"]
    assert not any(event["status"] == "succeeded" for event in outcomes)
    assert bool(snapshots) is (expected != "battle_end")
    if expected != "battle_end":
        assert engine._pending.deadline == 8


def test_jinx_summon_with_eight_collapsed_cards_advances_without_replaying(monkeypatch):
    from lorwright.core.champions.jinx.policy import JinxOpeningPolicy

    # 复现 20261116T120041-d1f7775cd206 的解析字段；不是逐帧图像回放。
    cards = [CardInHand(i, "吉茵珂絲" if i == 0 else "", 2,
                        Rect(400 + i * 80, 800, 50, 50)) for i in range(6)]
    before = ready(hand=cards, hand_expanded=True, enemy_nexus_hp=33,
                   readings={"mana": Reading(3, 0), "enemy_nexus_hp": Reading(33, 0)})
    after = ready(hand=[replace(cards[1], index=i) for i in range(8)],
                  hand_expanded=False, mana=1, enemy_nexus_hp=18,
                  readings={"mana": Reading(1, 0), "enemy_nexus_hp": Reading(18, 0)},
                  my_units=[Unit("", 6, 7, Rect(900 + i * 120, 850, 100, 150))
                            for i in range(3)])
    animation = replace(after, ui_state=UIState.UNKNOWN)
    engine, device, router, events, snapshots = engine_for(
        monkeypatch, [before, animation, after],
        [Action(ActionType.PLAY_CARD, card_index=0), Action(ActionType.NO_OP)], timeout=8,
    )
    policy = JinxOpeningPolicy()
    router.layers = [policy]
    monkeypatch.setattr("lorwright.core.loop.engine.time.monotonic", lambda: device.frames * 6.0)
    engine.run(max_ticks=3)
    outcomes = [e for e in events if e.get("event") == "action_outcome"]
    assert [e["status"] for e in outcomes] == ["waiting", "succeeded"]
    assert policy.step == 2
    assert policy._rockets_played == 0
    assert len(device.drags) == 1
    assert router.calls == 2
    assert snapshots == []


@pytest.mark.parametrize("filename", ["board-summoned-after-20261117.png",
                                      "board-summoned-glow-20261117.png",
                                      "board-summoned-badge-glow-20261117.png"])
def test_jinx_summon_with_enemy_healing_uses_parsed_board_identity(monkeypatch, filename):
    from lorwright.core.champions.jinx import PACK
    from lorwright.core.champions.jinx.policy import JinxOpeningPolicy
    from lorwright.core.config import load_settings
    from lorwright.core.perceive.state import StateParser
    from lorwright.core.perceive.ui_state import UIStateDetector

    # 真实单位裁剪 + 事件里的前后资源；不是完整实机逐帧录像。
    settings = load_settings()
    parser = StateParser(settings.layout.to_layout(), UIStateDetector(),
                         my_unit_recognizer=PACK.recognize_my_units)
    parser.load()
    monkeypatch.setattr(parser.ui, "detect", lambda image: UIState.MY_TURN_IDLE)
    image = np.zeros((1080, 1920, 3), np.uint8)
    image[830:1040, 760:1150] = cv2.imread(
        "tests/fixtures/jinx/" + filename,
    )
    parsed = parser.parse(image)
    assert any(unit.name == "吉茵珂絲" for unit in parsed.my_units)
    cards = [CardInHand(i, "吉茵珂絲" if i == 2 else "", 2 if i == 2 else 1,
                        Rect(400 + i * 80, 800, 50, 50)) for i in range(6)]
    before = ready(hand=cards, hand_expanded=True)
    after = replace(parsed, mana=1, enemy_nexus_hp=23,
                    readings={**parsed.readings, "mana": Reading(1, 0),
                              "enemy_nexus_hp": Reading(23, 0)})
    animation = replace(after, ui_state=UIState.UNKNOWN)
    engine, device, router, events, snapshots = engine_for(
        monkeypatch, [before, animation, after],
        [Action(ActionType.PLAY_CARD, card_index=2), Action(ActionType.NO_OP)],
    )
    policy = JinxOpeningPolicy()
    router.layers = [policy]
    monkeypatch.setattr("lorwright.core.loop.engine.time.monotonic", lambda: device.frames * 6.0)
    engine.run(max_ticks=3)
    outcomes = [event for event in events if event.get("event") == "action_outcome"]
    assert [event["status"] for event in outcomes] == ["waiting", "succeeded"]
    assert policy.step == 2
    assert len(device.drags) == 1
    assert not device.taps
    assert snapshots == []


def test_jinx_rebuild_uses_special_window_and_advances_once(monkeypatch):
    from lorwright.core.champions.jinx.policy import JinxOpeningPolicy

    cards = [CardInHand(i, "吉茵珂絲" if i == 2 else "", 2 if i == 2 else 1,
                        Rect(400 + i * 80, 800, 50, 50)) for i in range(6)]
    before = ready(hand=cards, hand_expanded=True)
    after = ready(hand=[replace(cards[0], index=i) for i in range(7)], hand_expanded=True,
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


def test_expanded_attack_collapses_before_using_fresh_unit_coordinates(monkeypatch):
    from lorwright.core.decide.generic import AttackWhenTokenPolicy, ExpandHandPolicy
    from lorwright.core.decide.router import Router as RealRouter

    card = CardInHand(0, "砰砰", 1, Rect(1300, 850, 80, 100))
    mistaken = Unit("", 1, 1, Rect(1300, 850, 80, 100))
    expanded = ready(hand=[card], hand_expanded=True, has_attack_token=True,
                     my_units=[mistaken])
    real_unit = Unit("", 6, 7, Rect(1000, 850, 100, 150))
    collapsed = replace(expanded, hand_expanded=False, my_units=[real_unit])
    engine, device, _, _, snapshots = engine_for(monkeypatch, [expanded, collapsed], [])
    engine.layout.collapse_hand_point = Rect(499, 619, 2, 2)
    engine.layout.attack_row = Rect(700, 470, 520, 70)
    engine.router = RealRouter([ExpandHandPolicy(), AttackWhenTokenPolicy()])
    engine.run(max_ticks=2)
    assert device.taps == [(500, 620)]
    assert len(device.drags) == 1
    assert device.drags[0][:4] == (*real_unit.rect.center, *engine.layout.attack_row.center)
    assert snapshots == []


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


def engine_for(monkeypatch, states, actions, timeout=8, *, check_readiness=False):
    settings = Settings()
    settings.loop.tick_ms = 0
    settings.loop.action_timeout_s = timeout
    settings.act.tap_wait_ms = settings.act.expand_wait_ms = settings.act.drag_wait_ms = 0
    device = Device()
    router = Router(actions)
    layout = Layout(end_turn=Rect(10, 10, 20, 20), hand_region=Rect(100, 800, 300, 200),
                    play_area=Rect(500, 500, 100, 100))
    engine = Engine(settings, router, device, layout=layout)
    # 原有单帧测试专注动作前提/后验；稳定门槛由下方真实多帧闭环另行覆盖。
    if not check_readiness:
        monkeypatch.setattr(engine._readiness, "ready", lambda action: True)
    sequence = iter(states)
    monkeypatch.setattr(engine.parser, "load", lambda: None)
    monkeypatch.setattr(engine, "_build_state", lambda image: next(sequence))
    events, snapshots = [], []
    monkeypatch.setattr("lorwright.core.loop.engine.emit", lambda **event: events.append(event))
    monkeypatch.setattr("lorwright.core.loop.engine.save_snapshot", lambda *args, **kw: snapshots.append(kw))
    return engine, device, router, events, snapshots


def test_readiness_uses_fresh_selected_slot_and_resets_after_each_input(monkeypatch):
    before = ready(hand_expanded=True, hand=[CardInHand(0, "known", 1, Rect(200, 900, 80, 100))])
    moved = replace(before, hand=[replace(before.hand[0], rect=Rect(400, 900, 80, 100))])
    chosen = ready(ui_state=UIState.OPTIONAL_CHOICE)
    states = [before, moved, moved, chosen, chosen, chosen]
    actions = [Action(ActionType.PLAY_CARD, card_index=0)] * 3 + [Action(ActionType.SKIP_CHOICE)] * 2
    engine, device, router, _, snapshots = engine_for(
        monkeypatch, states, actions, check_readiness=True,
    )
    sent = []

    class Layer:
        def on_action_sent(self, action, state):
            sent.append((action.type, device.frames))

    router.layers = [Layer()]
    result = engine.run(max_ticks=6)
    assert result.reason == "tick_limit"
    assert len(device.drags) == 1
    assert device.drags[0][:2] == (440, 950)
    assert sent == [(ActionType.PLAY_CARD, 3), (ActionType.SKIP_CHOICE, 5)]
    assert device.taps == [(20, 20)]
    assert snapshots == []


def test_readiness_reroutes_current_state_instead_of_replaying_old_candidate(monkeypatch):
    from lorwright.core.decide.generic import AttackWhenTokenPolicy
    from lorwright.core.decide.router import Router as RealRouter

    old = ready()
    attack = replace(old, has_attack_token=True,
                     my_units=[Unit("ally", 2, 2, Rect(300, 900, 60, 60))])
    engine, device, _, _, _ = engine_for(
        monkeypatch, [old, attack, attack], [], check_readiness=True,
    )
    engine.router = RealRouter([AttackWhenTokenPolicy()])
    engine.layout.attack_row = Rect(500, 400, 100, 50)
    engine.run(max_ticks=3)
    assert device.taps == []
    assert len(device.drags) == 1


def test_result_phase_can_interrupt_readiness_without_sending_candidate(monkeypatch):
    before = ready()
    unknown = ready(ui_state=UIState.UNKNOWN)
    engine, device, _, _, _ = engine_for(
        monkeypatch, [before, unknown, unknown, ready(ui_state=UIState.BATTLE_END)],
        [Action(ActionType.END_TURN)], check_readiness=True,
    )
    image = np.zeros((1080, 1920, 3), np.uint8)
    image[100:900, 300:1600] = cv2.imread(
        "tests/fixtures/continue/f1-result-transition-20261117.png",
    )

    def capture():
        device.frames += 1
        return Frame(image=image if device.frames in (2, 3) else np.zeros_like(image))

    monkeypatch.setattr(device, "screencap", capture)
    monkeypatch.setattr("lorwright.core.loop.engine.time.monotonic",
                        lambda: (0, 2, 12, 30)[device.frames - 1])
    assert engine.run(max_ticks=4).reason == "battle_end"
    assert device.taps == [] and device.drags == []


def test_readiness_keeps_block_declaration_before_confirmation(monkeypatch):
    from lorwright.core.champions.elise import SpiderAggroPolicy
    from lorwright.core.decide.generic import BlockingPolicy
    from lorwright.core.decide.router import Router as RealRouter

    before = ready(ui_state=UIState.BLOCKING,
                   my_units=[Unit("ally", 3, 4, Rect(300, 900, 60, 60))],
                   enemy_attackers=[Unit("enemy", 2, 3, Rect(500, 300, 60, 60))])
    moved = replace(before, my_units=[replace(before.my_units[0], rect=Rect(500, 700, 60, 60))])
    enemy = replace(moved, ui_state=UIState.ENEMY_TURN)
    engine, device, _, _, _ = engine_for(
        monkeypatch, [before, before, before, moved, moved, enemy], [], check_readiness=True,
    )
    blocking = BlockingPolicy()
    engine.router = RealRouter([SpiderAggroPolicy(), blocking])
    engine.run(max_ticks=6)
    assert len(device.drags) == 1
    assert device.drags[0][:4] == (330, 930, 530, 330)
    assert device.taps == [(20, 20)]
    assert not blocking._declared


def test_readiness_does_not_mark_elise_candidate_as_failed_play(monkeypatch):
    from lorwright.core.champions.elise import SpiderAggroPolicy
    from lorwright.core.decide.router import Router as RealRouter

    before = ready(hand_expanded=True, hand=[CardInHand(0, "小蜘蛛", 1, Rect(200, 900, 80, 100))])
    engine, device, _, _, _ = engine_for(
        monkeypatch, [before] * 3, [], check_readiness=True,
    )
    policy = SpiderAggroPolicy()
    engine.router = RealRouter([policy])
    engine.run(max_ticks=3)
    assert len(device.drags) == 1
    assert device.taps == []
    assert policy._pending_play == 0
    assert policy._unplayable == set()


def test_readiness_deadline_survives_ui_and_candidate_changes(monkeypatch):
    unknown = ready(ui_state=UIState.UNKNOWN)
    before = ready()
    choice = ready(ui_state=UIState.OPTIONAL_CHOICE)
    engine, device, _, _, snapshots = engine_for(
        monkeypatch, [before, unknown, choice, before],
        [Action(ActionType.END_TURN), Action(ActionType.SKIP_CHOICE)], check_readiness=True,
    )
    monkeypatch.setattr("lorwright.core.loop.engine.time.monotonic",
                        lambda: (0, 2, 5, 9)[device.frames - 1])
    result = engine.run(max_ticks=4)
    assert result.reason == "action_readiness_unverified"
    assert snapshots[-1]["tag"] == result.reason
    assert device.taps == [] and device.drags == []


def test_stale_frame_interrupts_readiness_without_extending_deadline(monkeypatch):
    state = ready()
    engine, device, _, _, _ = engine_for(
        monkeypatch, [state] * 4, [Action(ActionType.END_TURN)] * 3, check_readiness=True,
    )
    sent = []

    class Layer:
        def on_action_sent(self, *_):
            sent.append(device.frames)

    engine.router.layers = [Layer()]
    monkeypatch.setattr(Frame, "age_s", lambda _: 99 if device.frames == 2 else 0)
    engine.run(max_ticks=4)
    assert sent == [4]
    assert device.taps == [(20, 20)]


@pytest.mark.parametrize("transition_time,stale,expected", [
    (2, False, "battle_end"),
    (2, True, "battle_end"),
    (9, False, "action_timeout"),
])
def test_real_readiness_and_result_phase_preserve_original_action_deadline(
    monkeypatch, transition_time, stale, expected,
):
    from lorwright.core.models import TargetedSpell

    before = ready(ui_state=UIState.TARGETING,
                   targeted_spell=TargetedSpell("known", Rect(900, 500, 50, 50)),
                   enemy_units=[Unit("enemy", 1, 1, Rect(800, 400, 8, 8))])
    unknown = ready(ui_state=UIState.UNKNOWN)
    engine, device, _, events, _ = engine_for(
        monkeypatch, [before, before, unknown, unknown, ready(ui_state=UIState.BATTLE_END)],
        [Action(ActionType.SELECT_TARGET, raw={"enemy": True, "index": 0})] * 2,
        check_readiness=True,
    )
    image = np.zeros((1080, 1920, 3), np.uint8)
    image[100:900, 300:1600] = cv2.imread(
        "tests/fixtures/continue/f1-result-transition-20261117.png",
    )

    def capture():
        device.frames += 1
        return Frame(image=image if device.frames in (3, 4) else np.zeros_like(image))

    monkeypatch.setattr(device, "screencap", capture)
    monkeypatch.setattr(Frame, "age_s", lambda _: 99 if stale and device.frames == 4 else 0)
    monkeypatch.setattr("lorwright.core.loop.engine.time.monotonic",
                        lambda: (0, 0, transition_time, 12, 30)[device.frames - 1])
    result = engine.run(max_ticks=5)
    assert result.reason == expected
    assert device.taps == [(804, 404)]
    assert not any(e.get("status") == "succeeded" for e in events)
    if expected == "action_timeout":
        assert engine._pending.deadline == 8


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


@pytest.mark.parametrize("action_prompt", ["action_commit", "action_confirm"])
@pytest.mark.parametrize("hand_expanded", [False, True])
def test_expand_interrupted_by_combat_confirmation_yields_without_play_success(
    monkeypatch, hand_expanded, action_prompt,
):
    from lorwright.core.decide.generic import CombatConfirmPolicy, ExpandHandPolicy
    from lorwright.core.decide.router import Router as RealRouter

    # 按 run 20261116T140322-bbb448edad6f 的中断状态构造；不是逐帧图像回放。
    before = ready(hand=[CardInHand(0, "", 1, Rect(300, 800, 50, 50))])
    animation = replace(before, ui_state=UIState.UNKNOWN, hand_expanded=True,
                        action_prompt=action_prompt)
    commit = replace(before, ui_state=UIState.COMBAT_RESOLVING,
                     action_prompt=action_prompt, hand_expanded=hand_expanded)
    after = replace(before, ui_state=UIState.ENEMY_TURN)
    engine, device, _, events, snapshots = engine_for(
        monkeypatch, [before, before, animation, commit, commit, animation, after], [],
    )
    notifications = []

    class Observer:
        def decide(self, state):
            return None

        def on_action_outcome(self, action, previous, current):
            notifications.append((action.type, current.ui_state))

    engine.router = RealRouter([Observer(), ExpandHandPolicy(), CombatConfirmPolicy()])
    clock = [0.0]
    monkeypatch.setattr("lorwright.core.loop.engine.time.monotonic", lambda: clock[0])
    build = engine._build_state
    times = iter([0.0, 1.0, 2.0, 3.0, 4.0, 10.0, 12.0])

    def next_state(image):
        clock[0] = next(times)
        return build(image)

    monkeypatch.setattr(engine, "_build_state", next_state)
    result = engine.run(max_ticks=7)
    assert result.reason == "tick_limit"
    assert device.taps == [engine.layout.hand_region.center, engine.layout.end_turn.center]
    assert device.drags == []
    assert engine.router.stats == {"expand_hand": 1, "combat_confirm": 1, "fallback": 1}
    assert notifications == [(ActionType.CONFIRM, UIState.ENEMY_TURN)]
    outcomes = [e for e in events if e.get("event") == "action_outcome"]
    assert [(e["action"], e["status"], e["reason"]) for e in outcomes] == [
        ("play_card", "waiting", "awaiting_visible_result"),
        ("play_card", "waiting", "awaiting_visible_result"),
        ("play_card", "needs_input", "hand_expansion_interrupted"),
        ("confirm", "waiting", "awaiting_visible_result"),
        ("confirm", "waiting", "awaiting_visible_result"),
        ("confirm", "succeeded", "ui_transition"),
    ]
    assert snapshots == []


@pytest.mark.parametrize("ui,action_prompt,hand_expanded", [
    (UIState.UNKNOWN, "action_commit", True),
    (UIState.UNKNOWN, "action_confirm", True),
    (UIState.COMBAT_RESOLVING, None, False),
    (UIState.COMBAT_RESOLVING, "unrecognized", False),
    (UIState.MY_TURN_IDLE, "action_commit", False),
])
def test_expand_wait_requires_known_confirmation_before_original_deadline(
    monkeypatch, ui, action_prompt, hand_expanded,
):
    from lorwright.core.decide.generic import CombatConfirmPolicy, ExpandHandPolicy
    from lorwright.core.decide.router import Router as RealRouter

    before = ready(hand=[CardInHand(0, "", 1, Rect(300, 800, 50, 50))])
    unverified = replace(before, ui_state=ui, action_prompt=action_prompt,
                         hand_expanded=hand_expanded)
    late_commit = replace(before, ui_state=UIState.COMBAT_RESOLVING,
                          action_prompt="action_commit")
    engine, device, _, events, snapshots = engine_for(
        monkeypatch, [before, unverified, unverified, late_commit], [],
    )
    engine.router = RealRouter([ExpandHandPolicy(), CombatConfirmPolicy()])
    clock = [0.0]
    monkeypatch.setattr("lorwright.core.loop.engine.time.monotonic", lambda: clock[0])
    build = engine._build_state
    times = iter([0.0, 3.0, 7.0, 8.0])

    def next_state(image):
        clock[0] = next(times)
        return build(image)

    monkeypatch.setattr(engine, "_build_state", next_state)
    result = engine.run(max_ticks=4)
    assert (result.status, result.reason) == ("stopped", "action_timeout")
    assert device.taps == [engine.layout.hand_region.center]
    assert device.drags == []
    assert engine.router.stats == {"expand_hand": 1}
    assert [e["status"] for e in events if e.get("event") == "action_outcome"] == [
        "waiting", "waiting", "timed_out",
    ]
    assert snapshots == [{"tag": "action_timeout"}]


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


def test_new_confirmation_prompt_is_handled_once_after_waiting(monkeypatch):
    confirm = ready(ui_state=UIState.COMBAT_RESOLVING, action_prompt="action_confirm")
    commit = replace(confirm, action_prompt="action_commit")
    after = replace(commit, ui_state=UIState.ENEMY_TURN, action_prompt=None)
    engine, device, router, events, snapshots = engine_for(
        monkeypatch, [confirm, confirm, replace(confirm, ui_state=UIState.UNKNOWN),
                      commit, commit, after],
        [Action(ActionType.CONFIRM), Action(ActionType.CONFIRM), Action(ActionType.NO_OP)],
    )
    engine.run(max_ticks=6)
    assert device.taps == [(20, 20), (20, 20)]
    assert router.calls == 3
    outcomes = [e for e in events if e.get("event") == "action_outcome"]
    assert [e["status"] for e in outcomes] == [
        "waiting", "waiting", "needs_input", "waiting", "succeeded",
    ]
    assert outcomes[2]["reason"] == "confirmation_prompt_changed"
    assert snapshots == []


def test_staged_spell_survives_intermediate_confirmation_prompt(monkeypatch):
    before = ready(hand=[CardInHand(0, "spell", 1, Rect(400, 800, 80, 100))],
                   hand_expanded=True)
    staged = replace(before, ui_state=UIState.COMBAT_RESOLVING,
                     action_prompt="action_confirm")
    commit = replace(staged, action_prompt="action_commit")
    after = replace(before, ui_state=UIState.ENEMY_TURN, hand=[], mana=2,
                    readings={"mana": Reading(2, 0)})
    play = Action(ActionType.PLAY_CARD, 0)
    engine, device, router, events, snapshots = engine_for(
        monkeypatch, [before, staged, commit, after],
        [play, Action(ActionType.CONFIRM), Action(ActionType.CONFIRM), Action(ActionType.NO_OP)],
    )
    notifications = []

    class Policy:
        def on_action_outcome(self, action, previous, current):
            notifications.append((action.type, current.ui_state))

    router.layers = [Policy()]
    engine.run(max_ticks=4)
    assert len(device.drags) == 1
    assert device.taps == [(20, 20), (20, 20)]
    assert notifications == [(ActionType.CONFIRM, UIState.ENEMY_TURN),
                             (ActionType.PLAY_CARD, UIState.ENEMY_TURN)]
    assert snapshots == []


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
    assert [(event["action"], event["status"]) for event in events
            if event.get("event") == "action_outcome"] == [
        ("play_card", "waiting"), ("play_card", "needs_input"),
        ("confirm", "succeeded"), ("play_card", "succeeded"),
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


def test_rocket_confirmation_accepts_damage_with_refilled_mana(monkeypatch):
    from lorwright.core.champions.jinx.policy import JinxOpeningPolicy
    from lorwright.core.decide.generic import CombatConfirmPolicy
    from lorwright.core.decide.router import Router as RealRouter

    cards = [CardInHand(i, "超威能死亡火箭！", 1, Rect(300 + i * 100, 800, 50, 50))
             for i in range(2)]
    before = ready(hand=cards, hand_expanded=True, spell_mana=3, enemy_nexus_hp=8,
                   readings={"mana": Reading(3, 0), "spell_mana": Reading(3, 0),
                             "enemy_nexus_hp": Reading(8, 0)})
    staged = replace(before, ui_state=UIState.COMBAT_RESOLVING)
    after = replace(before, hand=cards[:1], enemy_nexus_hp=1,
                    readings={**before.readings, "enemy_nexus_hp": Reading(1, 0)})
    engine, device, _, _, snapshots = engine_for(monkeypatch, [before, staged, after], [])
    policy = JinxOpeningPolicy(jinx_summoned=True)
    engine.router = RealRouter([policy, CombatConfirmPolicy()])
    engine.run(max_ticks=3)
    assert policy._rockets_played == 1
    assert snapshots == []
    # 第三帧的新火箭决策可发下一枚，已确认的第一枚只计一次。
    assert len(device.drags) == 2


def test_rocket_confirmation_accepts_collapsed_hand_with_same_visible_count(monkeypatch):
    from lorwright.core.champions.jinx.policy import JinxOpeningPolicy
    from lorwright.core.decide.generic import CombatConfirmPolicy
    from lorwright.core.decide.router import Router as RealRouter

    cards = [CardInHand(i, "超威能死亡火箭！", 1, Rect(300 + i * 100, 800, 50, 50))
             for i in range(6)]
    before = ready(hand=cards, hand_expanded=True, mana=1, spell_mana=3, enemy_nexus_hp=13,
                   readings={"mana": Reading(1, 0), "spell_mana": Reading(3, 0),
                             "enemy_nexus_hp": Reading(13, 0)})
    staged = replace(before, ui_state=UIState.COMBAT_RESOLVING)
    after = replace(before, hand_expanded=False, enemy_nexus_hp=6,
                    readings={**before.readings, "enemy_nexus_hp": Reading(6, 0)})
    engine, device, _, _, snapshots = engine_for(monkeypatch, [before, staged, after], [])
    policy = JinxOpeningPolicy(jinx_summoned=True)
    engine.router = RealRouter([policy, CombatConfirmPolicy()])
    engine.run(max_ticks=3)
    assert policy._rockets_played == 1
    # 结果核验后第三帧正常回退结束回合，不重复拖火箭或重复计数。
    assert len(device.drags) == 1 and device.taps == [(20, 20), (20, 20)]
    assert snapshots == []


def test_rocket_confirmation_accepts_fresh_net_payment_when_collapsed(monkeypatch):
    from lorwright.core.champions.jinx.policy import JinxOpeningPolicy
    from lorwright.core.decide.generic import CombatConfirmPolicy
    from lorwright.core.decide.router import Router as RealRouter

    # 复用 run 20261116T130316-16a80a08bbff 的字段，不假定血量上升的原因。
    cards = [CardInHand(i, "超威能死亡火箭！" if i == 0 else "砰砰", 1,
                        Rect(300 + i * 100, 800, 50, 50)) for i in range(6)]
    before = ready(hand=cards, hand_expanded=True, mana=1, spell_mana=2, enemy_nexus_hp=10,
                   readings={"mana": Reading(1, 0), "spell_mana": Reading(2, 0),
                             "enemy_nexus_hp": Reading(10, 0)})
    staged = replace(before, hand=cards[1:], hand_expanded=False,
                     ui_state=UIState.COMBAT_RESOLVING)
    after = replace(staged, ui_state=UIState.MY_TURN_IDLE, spell_mana=1, enemy_nexus_hp=11,
                    readings={"mana": Reading(1, 0), "spell_mana": Reading(1, 0),
                              "enemy_nexus_hp": Reading(11, 0)})
    engine, device, _, _, snapshots = engine_for(monkeypatch, [before, staged, after], [])
    policy = JinxOpeningPolicy(jinx_summoned=True)
    engine.router = RealRouter([policy, CombatConfirmPolicy()])
    result = engine.run(max_ticks=3)
    assert result.reason != "staged_play_unverified"
    assert policy._rockets_played == 1
    assert len(device.drags) == 1
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


@pytest.mark.parametrize("settled", [True, False])
def test_staged_spell_observes_delayed_result_with_original_budget(monkeypatch, settled):
    card = CardInHand(0, "火箭", 1, Rect(300, 800, 50, 50))
    before = ready(hand=[card], hand_expanded=True)
    staged = replace(before, ui_state=UIState.COMBAT_RESOLVING)
    unverified = replace(before, hand=[])
    paid = replace(unverified, mana=2, readings={"mana": Reading(2, 0)})
    engine, device, router, events, snapshots = engine_for(
        monkeypatch, [before, staged, unverified, paid if settled else unverified],
        [Action(ActionType.PLAY_CARD, 0), Action(ActionType.CONFIRM), Action(ActionType.NO_OP)],
        timeout=20,
    )
    callbacks = []

    class Layer:
        def on_action_outcome(self, action, *_):
            callbacks.append(action.type)

    router.layers = [Layer()]
    clock = [0.0]
    monkeypatch.setattr("lorwright.core.loop.engine.time.monotonic", lambda: clock[0])
    build = engine._build_state
    times = iter([0.0, 18.0, 19.0, 19.5 if settled else 20.0])

    def next_state(image):
        clock[0] = next(times)
        return build(image)

    monkeypatch.setattr(engine, "_build_state", next_state)
    result = engine.run(max_ticks=4)
    assert len(device.drags) == 1 and device.taps == [(20, 20)]
    assert router.calls == (3 if settled else 2)
    assert callbacks == ([ActionType.CONFIRM, ActionType.PLAY_CARD] if settled
                         else [ActionType.CONFIRM])
    assert snapshots == ([] if settled else [{"tag": "action_timeout"}])
    if not settled:
        assert result.reason == "action_timeout"
    outcomes = [e for e in events if e.get("event") == "action_outcome"]
    assert any(e["action"] == "play_card" and e["status"] == "waiting" for e in outcomes)
    assert outcomes[-1]["status"] == ("succeeded" if settled else "timed_out")


def test_staged_spell_confirmation_changes_do_not_renew_parent_budget(monkeypatch):
    card = CardInHand(0, "火箭", 1, Rect(300, 800, 50, 50))
    before = ready(hand=[card], hand_expanded=True)
    confirm = replace(before, ui_state=UIState.COMBAT_RESOLVING, action_prompt="action_confirm")
    commit = replace(confirm, action_prompt="action_commit")
    after = replace(before, hand=[], mana=2, readings={"mana": Reading(2, 0)})
    engine, device, router, _, snapshots = engine_for(
        monkeypatch, [before, confirm, commit, after],
        [Action(ActionType.PLAY_CARD, 0), Action(ActionType.CONFIRM), Action(ActionType.CONFIRM),
         Action(ActionType.NO_OP)],
        timeout=20,
    )
    clock = [0.0]
    monkeypatch.setattr("lorwright.core.loop.engine.time.monotonic", lambda: clock[0])
    build = engine._build_state
    times = iter([0.0, 18.0, 19.0, 20.0])

    def next_state(image):
        clock[0] = next(times)
        return build(image)

    monkeypatch.setattr(engine, "_build_state", next_state)
    result = engine.run(max_ticks=4)
    assert result.reason == "action_timeout"
    assert len(device.drags) == 1 and device.taps == [(20, 20), (20, 20)]
    assert router.calls == 3
    assert snapshots == [{"tag": "action_timeout"}]


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


@pytest.mark.parametrize("ui_state", [UIState.COMBAT_RESOLVING, UIState.MULLIGAN])
@pytest.mark.parametrize("settled", [True, False])
def test_phase_confirm_waits_for_settlement_without_repeating(monkeypatch, settled, ui_state):
    # 换牌确认案例依据 f1 会话 20261117T014309-ca7207857b14 的事件时序构造。
    combat = ready(ui_state=ui_state)
    animation = replace(combat, ui_state=UIState.UNKNOWN)
    final = replace(combat, ui_state=UIState.MY_TURN_IDLE) if settled else animation
    engine, device, router, events, snapshots = engine_for(
        monkeypatch, [combat, animation, final],
        [Action(ActionType.CONFIRM), Action(ActionType.NO_OP)],
    )
    if ui_state is UIState.COMBAT_RESOLVING:
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


@pytest.mark.parametrize("settled", [True, False])
def test_round_end_waits_for_effects_without_repeating(monkeypatch, settled):
    # 依据 f1 结束回合后动画仍在播放、随后新回合稳定的日志构造；不是逐帧录像。
    before = ready(mana=1, readings={"mana": Reading(1, 0)})
    animation = replace(before, ui_state=UIState.UNKNOWN)
    final = ready(mana=4, readings={"mana": Reading(4, 0)}) if settled else animation
    engine, device, router, events, snapshots = engine_for(
        monkeypatch, [before, animation, final],
        [Action(ActionType.END_TURN), Action(ActionType.NO_OP)],
    )
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
    monkeypatch.setattr("lorwright.core.loop.engine.time.monotonic",
                        lambda: 20.0 if device.frames >= 2 else 0.0)
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
    monkeypatch.setattr("lorwright.core.loop.engine.time.monotonic",
                        lambda: 20.0 if device.frames >= 2 else 0.0)
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
