"""地图图标实拍与用户分叉优先级；不依赖游戏。"""

import random
from pathlib import Path

import cv2
import pytest

from lorwright.core.decide.adventure import pick_map_node
from lorwright.core.models import MapNodeKind
from lorwright.core.perceive.mapnav import MapNode, node_kind

FIXTURES = Path(__file__).parent / "fixtures" / "mapnav"


@pytest.mark.parametrize("preferred,other", [
    (MapNodeKind.EVENT, MapNodeKind.SHOP),
    (MapNodeKind.EVENT, MapNodeKind.GOLD),
    (MapNodeKind.SHOP, MapNodeKind.ITEM),
    (MapNodeKind.SHOP, MapNodeKind.SPELL),
    (MapNodeKind.ITEM, MapNodeKind.GOLD),
    (MapNodeKind.SPELL, MapNodeKind.GOLD),
])
@pytest.mark.parametrize("reverse", [False, True])
def test_map_priority_is_independent_of_candidate_order(preferred, other, reverse):
    kinds = [other, preferred] if reverse else [preferred, other]
    for seed in range(6):
        index = pick_map_node(kinds, rng=random.Random(seed))
        assert kinds[index] is preferred


def test_equal_item_and_spell_priorities_still_use_random_choice():
    kinds = [MapNodeKind.ITEM, MapNodeKind.SPELL]
    assert {pick_map_node(kinds, rng=random.Random(seed)) for seed in range(6)} == {0, 1}


def test_unknown_icons_are_not_given_an_invented_priority():
    assert pick_map_node([], rng=random.Random(0)) is None
    assert pick_map_node([None, MapNodeKind.EVENT], rng=random.Random(0)) == 1
    assert pick_map_node([None, MapNodeKind.GOLD], rng=random.Random(0)) == 1
    assert {pick_map_node([None, None], rng=random.Random(seed)) for seed in range(6)} == {0, 1}


@pytest.mark.parametrize("name,node,kind", [
    ("f1-weekly-after-second-reward-20261116.png", MapNode(689, 151, 55), MapNodeKind.EVENT),
    ("f1-weekly-after-second-reward-20261116.png", MapNode(910, 233, 45), MapNodeKind.GOLD),
    ("f1-shop-20261114.png", MapNode(245, 536, 45), MapNodeKind.SHOP),
    ("f1-after-shop-20261114.png", MapNode(959, 535, 45), MapNodeKind.SHOP),
])
def test_real_map_icons_keep_gold_separate_from_shop(name, node, kind):
    image = cv2.imread(str(FIXTURES / name))
    assert image is not None
    assert node_kind(image, node) is kind
    x, y = node.center
    image[y - 40:y + 40, x - 40:x + 40] = 128
    assert node_kind(image, node) is None
