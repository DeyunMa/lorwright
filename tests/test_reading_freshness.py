"""数字读数的时效与跨对局隔离；不依赖设备或 OCR 模板。"""

import numpy as np
import pytest

from lorwright.models import Layout, Rect, UIState
from lorwright.perceive.state import StateParser


class _UI:
    state = UIState.MY_TURN_IDLE

    def detect(self, image):
        return self.state


class _Digits:
    def __init__(self):
        self.values = {}
        self.calls = []

    def read(self, image, rect):
        self.calls.append(rect)
        return self.values.get(rect)


@pytest.fixture
def parser_setup():
    layout = Layout(
        mana=Rect(0, 0, 1, 1),
        my_hp=Rect(1, 0, 1, 1),
        enemy_hp=Rect(2, 0, 1, 1),
    )
    ui = _UI()
    digits = _Digits()
    parser = StateParser(layout, ui, digits)
    image = np.zeros((1, 3, 3), dtype=np.uint8)
    return parser, ui, digits, layout, image


def test_initial_unknown_has_no_observed_numbers(parser_setup):
    parser, ui, digits, layout, image = parser_setup
    ui.state = UIState.UNKNOWN
    digits.values = {layout.mana: 9, layout.my_hp: 50, layout.enemy_hp: 30}

    state = parser.parse(image)

    assert digits.calls == []
    assert not state.has_fresh_readings("mana", "nexus_hp", "enemy_nexus_hp")
    assert all(r.value is None and r.age_frames is None for r in state.readings.values())
    assert not state.has_fresh_readings("missing")


def test_observed_zero_is_fresh_not_missing(parser_setup):
    parser, _, digits, layout, image = parser_setup
    digits.values = {layout.mana: 0, layout.my_hp: 0, layout.enemy_hp: 0}

    state = parser.parse(image)

    assert (state.mana, state.nexus_hp, state.enemy_nexus_hp) == (0, 0, 0)
    assert state.has_fresh_readings("mana", "nexus_hp", "enemy_nexus_hp")
    assert all(r.value == 0 and r.age_frames == 0 for r in state.readings.values())


def test_obscured_numbers_keep_values_but_age_until_reobserved(parser_setup):
    parser, _, digits, layout, image = parser_setup
    digits.values = {layout.mana: 3, layout.my_hp: 50, layout.enemy_hp: 30}
    first = parser.parse(image)
    digits.values = {}
    obscured = parser.parse(image)
    twice_obscured = parser.parse(image)

    assert (obscured.mana, obscured.nexus_hp, obscured.enemy_nexus_hp) == (3, 50, 30)
    assert not obscured.has_fresh_readings("mana", "nexus_hp", "enemy_nexus_hp")
    assert all(r.age_frames == 1 for r in obscured.readings.values())
    assert all(r.age_frames == 2 for r in twice_obscured.readings.values())

    digits.values = {layout.mana: 1, layout.my_hp: 45, layout.enemy_hp: 25}
    restored = parser.parse(image)

    assert (restored.mana, restored.nexus_hp, restored.enemy_nexus_hp) == (1, 45, 25)
    assert restored.has_fresh_readings("mana", "nexus_hp", "enemy_nexus_hp")
    # Later parses must not change observations kept in earlier state snapshots.
    assert first.has_fresh_readings("mana", "nexus_hp", "enemy_nexus_hp")
    assert first.readings["mana"].value == 3
    assert obscured.readings["mana"].age_frames == 1


@pytest.mark.parametrize("non_battle_ui", [UIState.UNKNOWN, UIState.BATTLE_END])
def test_non_battle_screens_do_not_refresh_cached_numbers(parser_setup, non_battle_ui):
    parser, ui, digits, layout, image = parser_setup
    digits.values = {layout.mana: 3, layout.my_hp: 50, layout.enemy_hp: 30}
    parser.parse(image)
    digits.calls.clear()
    digits.values = {layout.mana: 9, layout.my_hp: 99, layout.enemy_hp: 99}
    ui.state = non_battle_ui

    state = parser.parse(image)

    assert digits.calls == []
    assert (state.mana, state.nexus_hp, state.enemy_nexus_hp) == (3, 50, 30)
    assert all(r.age_frames == 1 for r in state.readings.values())
    assert not state.has_fresh_readings("mana", "nexus_hp", "enemy_nexus_hp")


def test_new_battle_does_not_inherit_previous_battle_numbers(parser_setup):
    parser, ui, digits, layout, image = parser_setup
    digits.values = {layout.mana: 7, layout.my_hp: 12, layout.enemy_hp: 2}
    previous_battle = parser.parse(image)
    ui.state = UIState.BATTLE_END
    parser.parse(image)
    ui.state = UIState.MULLIGAN
    digits.values = {}

    new_battle = parser.parse(image)

    assert (new_battle.mana, new_battle.nexus_hp, new_battle.enemy_nexus_hp) == (0, 20, 20)
    assert all(r.value is None and r.age_frames is None for r in new_battle.readings.values())
    assert not new_battle.has_fresh_readings("mana", "nexus_hp", "enemy_nexus_hp")
    assert previous_battle.readings["nexus_hp"].value == 12

    digits.values = {layout.mana: 1, layout.my_hp: 50, layout.enemy_hp: 30}
    observed = parser.parse(image)
    digits.values = {}
    still_mulligan = parser.parse(image)

    assert observed.has_fresh_readings("mana", "nexus_hp", "enemy_nexus_hp")
    assert (still_mulligan.mana, still_mulligan.nexus_hp, still_mulligan.enemy_nexus_hp) == (1, 50, 30)
    assert all(r.age_frames == 1 for r in still_mulligan.readings.values())
