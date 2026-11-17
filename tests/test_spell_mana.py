from pathlib import Path

import cv2
import pytest

from lorwright.core.config import load_settings
from lorwright.core.perceive.state import StateParser
from lorwright.core.perceive.ui_state import UIStateDetector


@pytest.mark.parametrize(('name', 'expected'), [
    ('1080p_hand_expanded.png', 0),
    ('1080p_spell_mana_one.png', 1),
    ('1080p_no_attack_token.png', 2),
    ('1080p_confirm_phase.png', 3),
])
def test_spell_mana_from_real_screens(name, expected):
    image = cv2.imread(str(Path('tests/fixtures/screens') / name))
    assert image is not None
    settings = load_settings()
    layout = settings.layout.to_layout()
    detector = UIStateDetector(action_button=layout.end_turn)
    parser = StateParser(layout, detector)
    parser.load()
    assert parser.parse(image).spell_mana == expected


@pytest.mark.parametrize('name', [
    'f1-spell-mana-glow-fragment-20261117.png',
    'f1-spell-mana-glow-bright-20261117.png',
])
def test_spell_mana_ignores_colored_glow_without_reusing_old_value(name, monkeypatch):
    from lorwright.core.models import Layout, Rect, UIState

    image = cv2.imread(str(Path('tests/fixtures/screens') / name))
    assert image is not None
    layout = Layout(spell_mana=Rect(111, 59, 34, 38))
    detector = UIStateDetector()
    monkeypatch.setattr(detector, 'detect', lambda _: UIState.MY_TURN_IDLE)
    parser = StateParser(layout, detector)
    parser.load()
    state = parser.parse(image)
    assert state.spell_mana == 1
    assert state.has_fresh_readings('spell_mana')
    rect = layout.spell_mana
    image[rect.y:rect.y + rect.h, rect.x:rect.x + rect.w] = 0
    assert parser.parse(image).spell_mana is None


def test_obscured_spell_mana_is_not_reused():
    image = cv2.imread('tests/fixtures/screens/1080p_confirm_phase.png')
    assert image is not None
    layout = load_settings().layout.to_layout()
    parser = StateParser(layout, UIStateDetector(action_button=layout.end_turn))
    parser.load()
    assert parser.parse(image).spell_mana == 3
    rect = layout.spell_mana
    image[rect.y:rect.y + rect.h, rect.x:rect.x + rect.w] = 0
    assert parser.parse(image).spell_mana is None
