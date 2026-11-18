"""场上升级 Jinx：安全实拍裁剪与明确标注的合成反例。"""

from dataclasses import replace

import cv2
import numpy as np
import pytest

from lorwright.core.champions.jinx import PACK
from lorwright.core.config import load_settings
from lorwright.core.decide.router import Router
from lorwright.core.loop.engine import Engine
from lorwright.core.models import Rect, UIState, Unit
from tools.test_data import fixtures_root


def board_image(filename="board-summoned-after-20261117.png"):
    image = np.zeros((1080, 1920, 3), np.uint8)
    image[830:1040, 760:1150] = cv2.imread(str(fixtures_root() / "jinx" / filename))
    return image


@pytest.mark.parametrize("filename", ["board-summoned-after-20261117.png",
                                      "board-summoned-glow-20261117.png",
                                      "board-summoned-badge-glow-20261117.png"])
@pytest.mark.parametrize("offset", [(0, 0), (-200, -120), (200, 0)])
def test_parser_names_only_jinx_inside_detected_unit_body(offset, filename):
    settings = load_settings()
    engine = Engine(settings, Router([]), None, my_unit_recognizer=PACK.recognize_my_units)
    engine.parser.load()
    # 裁剪未保留行动按钮；只隔离 UI 检测，其余单位感知走真实 parser。
    engine.parser.ui.detect = lambda image: UIState.MY_TURN_IDLE
    image = board_image(filename)
    dx, dy = offset
    image = cv2.warpAffine(image, np.float32([[1, 0, dx], [0, 1, dy]]), (1920, 1080))
    state = engine.parser.parse(image)
    assert [unit.name for unit in state.my_units] == ["", "吉茵珂絲"]
    assert not state.hand_expanded
    assert state.readings["my_units_visible"].value == 2


@pytest.mark.parametrize("filename", ["board-summoned-after-20261117.png",
                                      "board-summoned-glow-20261117.png",
                                      "board-summoned-badge-glow-20261117.png"])
@pytest.mark.parametrize("change", ["neighbor", "obscured", "left_half", "top_half",
                                    "no_units", "blank", "small"])
def test_board_identity_requires_local_card_art_and_detected_unit(change, filename):
    image = board_image(filename)
    jinx = Unit("", 6, 7, Rect(1055, 928, 8, 8))
    units = [jinx]
    if change == "neighbor":
        units = [replace(jinx, rect=Rect(875, 929, 8, 8))]
    elif change == "obscured":
        image[913:988, 1000:1090] = 0
    elif change == "left_half":
        image[913:988, 1000:1045] = 0
    elif change == "top_half":
        image[913:951, 1000:1090] = 0
    elif change == "no_units":
        units = []
    elif change == "blank":
        image[:] = 0
    else:
        image = image[:50, :50]
    assert all(not unit.name for unit in PACK.recognize_my_units(image, units))


@pytest.mark.parametrize("row,col", [(0, 0), (0, 1), (1, 0), (1, 1)])
@pytest.mark.parametrize("fragment_only", [False, True])
def test_board_identity_needs_three_quarters_at_one_alignment(row, col, fragment_only):
    image = board_image()
    art = image[913:988, 1000:1090]
    mask = np.zeros(art.shape[:2], dtype=bool)
    mask[row * 75 // 2:(row + 1) * 75 // 2,
         col * 90 // 2:(col + 1) * 90 // 2] = True
    art[~mask if fragment_only else mask] = 0
    units = PACK.recognize_my_units(image, [Unit("", 6, 7, Rect(1055, 928, 8, 8))])
    assert bool(units[0].name) is not fragment_only


def test_missing_jinx_badge_does_not_borrow_visible_portrait():
    settings = load_settings()
    engine = Engine(settings, Router([]), None, my_unit_recognizer=PACK.recognize_my_units)
    engine.parser.load()
    engine.parser.ui.detect = lambda image: UIState.MY_TURN_IDLE
    image = board_image("board-summoned-20261117.png")
    # 合成遮挡徽章，保留其下方实际卡面；不允许仅凭卡面补出单位。
    image[840:910, 980:1110] = 0
    state = engine.parser.parse(image)
    assert [unit.name for unit in state.my_units] == [""]


def test_unknown_animation_does_not_assign_board_identity():
    settings = load_settings()
    engine = Engine(settings, Router([]), None, my_unit_recognizer=PACK.recognize_my_units)
    engine.parser.load()
    engine.parser.ui.detect = lambda image: UIState.UNKNOWN
    state = engine.parser.parse(board_image())
    assert state.my_units
    assert all(not unit.name for unit in state.my_units)
