"""空手需有独立画面证据，徽章漏检或局部遮挡不能作为空手。"""
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
import pytest

from lorwright.cli.app import _battle_layers
from lorwright.core.champions import load
from lorwright.core.config import load_settings
from lorwright.core.decide.router import Router
from lorwright.core.models import ActionType, GameState, Rect, UIState, Unit
from lorwright.core.perceive.hand import EMPTY_HAND_REGION, is_confirmed_empty
from lorwright.core.perceive.state import StateParser

SCREENS = Path("tests/fixtures/screens")


def image(name):
    frame = cv2.imread(str(SCREENS / name))
    assert frame is not None
    return frame


class IdleUI:
    def detect(self, frame):
        return UIState.MY_TURN_IDLE


def synthetic_empty(index):
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    suffix = "" if index == 0 else "_2"
    frame[855:1080, 1420:1920] = cv2.imread(f"assets/ui/empty_hand_karma{suffix}.png")
    return frame


@pytest.mark.parametrize("index", [0, 1])
def test_synthetic_empty_hand_flows_through_parser(index):
    settings = load_settings()
    parser = StateParser(settings.layout.to_layout(), IdleUI())
    state = parser.parse(synthetic_empty(index))
    assert not state.hand
    assert state.hand_empty_confirmed


@pytest.mark.parametrize("name", [
    "1080p_hand_fan.png", "1080p_hand_expanded.png", "1080p_battle_turn2.png",
    "1080p_battle_loading_20261114.png",
    "1080p_commit_phase.png", "1080p_block_phase.png",
])
def test_other_screens_do_not_confirm_empty(name):
    assert not is_confirmed_empty(image(name), EMPTY_HAND_REGION)


def test_animation_intermediate_frame_is_accepted():
    first = synthetic_empty(0)
    second = synthetic_empty(1)
    assert is_confirmed_empty(cv2.addWeighted(first, 0.5, second, 0.5, 0), EMPTY_HAND_REGION)


@pytest.mark.parametrize("index", [0, 1])
def test_card_or_occlusion_over_empty_background_is_unknown(index):
    empty = synthetic_empty(index)
    fan = image("1080p_hand_fan.png")
    # 局部贴入真实手牌，模拟漏检徽章；单独覆盖背景模拟动画或遮挡。
    card = empty.copy()
    card[930:1080, 1750:1920] = fan[930:1080, 1750:1920]
    assert not is_confirmed_empty(card, EMPTY_HAND_REGION)
    obscured = empty.copy()
    obscured[920:945, 1700:1725] = 0
    assert not is_confirmed_empty(obscured, EMPTY_HAND_REGION)
    obscured = empty.copy()
    obscured[865:890, 1425:1450] = 0
    assert not is_confirmed_empty(obscured, EMPTY_HAND_REGION)
    assert not is_confirmed_empty(empty, Rect(1420, 855, 499, 225))


def test_jinx_empty_hand_routes_attack_before_end_turn():
    router = Router(_battle_layers(load("jinx"), policy_kwargs={"spell_already_played": True}))
    state = GameState(ui_state=UIState.MY_TURN_IDLE, hand_empty_confirmed=True,
                      has_attack_token=True, my_units=[Unit("", 1, 1, Rect(700, 900, 10, 10))])
    result = router.decide(state)
    assert (result.layer, result.action.type) == ("attack_when_token", ActionType.ATTACK)
    result = router.decide(replace(state, has_attack_token=False))
    assert (result.layer, result.action.type) == ("fallback", ActionType.END_TURN)
    result = router.decide(replace(state, hand_empty_confirmed=False))
    assert (result.layer, result.action.type) == ("attack_when_token", ActionType.ATTACK)
