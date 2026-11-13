"""Jinx 手牌身份：9 张卡面 ORB + 费用约束。"""

from pathlib import Path

import cv2
import numpy as np
import pytest

from lorwright.champions.jinx.deck import BY_NAME
from lorwright.champions.jinx.policy import JinxOpeningPolicy
from lorwright.champions.jinx.vision import recognize_hand, recognize_mulligan
from lorwright.models import ActionType, GameState, Rect, UIState
from lorwright.perceive.digits import DigitReader
from lorwright.perceive.hand import recognize_expanded
from lorwright.perceive.mulligan import recognize_mulligan_selection


def _named(filename: str):
    region = cv2.imread(str(Path("tests/fixtures/jinx") / filename))
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    image[700:1080, 200:1800] = region
    digits = DigitReader()
    digits.load()
    cards = recognize_expanded(image, Rect(200, 700, 1600, 380), digits)
    return recognize_hand(image, cards)


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("battle-hand.png", {4: "吉茵珂絲", 5: "應急裝置"}),
        ("battle-expand2.png", {3: "吉茵珂絲", 4: "應急裝置"}),
        ("live-8cards.png", {4: "吉茵珂絲", 5: "應急裝置"}),
    ],
)
def test_key_cards_are_recognized(filename, expected):
    named = {card.index: card for card in _named(filename) if card.name}
    for index, name in expected.items():
        assert named[index].name == name


@pytest.mark.parametrize(
    "filename", ["battle-hand.png", "battle-expand2.png", "live-8cards.png"]
)
def test_named_cards_respect_known_costs(filename):
    for card in _named(filename):
        if not card.name:
            continue
        definition = BY_NAME[card.name]
        # 普通牌费用应精确一致；英雄牌可能被减费（4→2）。
        assert card.cost == definition.cost or definition.cost >= card.cost


def test_live_eight_card_hand_names_most_cards():
    named = [card for card in _named("live-8cards.png") if card.name]
    assert len(named) >= 6


def test_reduced_cost_pow_pow_is_not_mistaken_for_jinx():
    # PoC 道具把砰砰减到 1 费；旧逻辑只给英雄牌放宽费用，导致砰砰被
    # 当成 Jinx（4 费英雄牌允许减费），策略随后去拖一张法术。
    named = {card.index: card for card in _named("live-6cards-20261107.png") if card.name}
    assert named[0].name == "超威能死亡火箭！"
    for index in (1, 2, 3, 4):
        assert named[index].name == "砰砰"


def test_mulligan_cards_are_recognized():
    image = cv2.imread(str(Path("tests/fixtures/jinx/mulligan-4cards.png")))
    assert image is not None
    cards = recognize_mulligan(image)
    assert [card.matches_target for card in cards] == [False] * 4
    assert [card.rect.center for card in cards] == [
        (438, 820), (756, 820), (1068, 817), (1386, 817),
    ]
    action = JinxOpeningPolicy().decide(GameState(
        ui_state=UIState.MULLIGAN, mulligan_cards=cards,
        mulligan_selected=recognize_mulligan_selection(image),
    ))
    assert action.type is ActionType.MULLIGAN_REPLACE
    assert action.raw["points"] == [cards[0].rect.center]


def test_mulligan_does_not_need_support_or_reward_card_names():
    image = cv2.imread(str(Path("tests/fixtures/jinx/mulligan-support-before.png")))
    assert image is not None
    cards = recognize_mulligan(image)
    # 金色英雄标志不能排除是 Jinx，保留未知。
    assert [card.matches_target for card in cards] == [False, False, False, None]


def test_mulligan_selected_card_is_unknown_without_prior_view():
    image = cv2.imread(str(Path("tests/fixtures/jinx/mulligan-support-first-selected.png")))
    assert image is not None
    assert [card.matches_target for card in recognize_mulligan(image)] == [None, False, False, None]


def test_synthetic_jinx_and_obscured_slot():
    # 把素材嵌入真实换牌画面只检验接线，不等于真实 Jinx 换牌截图。
    image = cv2.imread(str(Path("tests/fixtures/jinx/mulligan-4cards.png")))
    target = cv2.imread(str(Path("src/lorwright/champions/jinx/assets/01PZ040.png")))
    assert image is not None and target is not None
    image[332:732, 347:627] = cv2.resize(target, (280, 400))
    assert recognize_mulligan(image)[0].matches_target is True
    image[340:550, 363:443] = 0
    assert recognize_mulligan(image)[0].matches_target is None
