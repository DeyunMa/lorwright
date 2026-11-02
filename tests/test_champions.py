"""英雄包注册表的单测：验证「加英雄 = 加目录，不改核心」。"""

from __future__ import annotations

import pytest

from lorwright.champions import available, load
from lorwright.decide.base import Policy
from lorwright.decide.card import CardDef


def test_available_lists_elise():
    assert "elise" in available()


def test_load_returns_a_champion_pack():
    pack = load("elise")
    assert pack.name == "elise"
    assert pack.display_name == "伊莉絲"


def test_pack_deck_uses_generic_card_interface():
    """核心层只认 CardDef 的通用字段，不该看到伊莉丝专属字段。"""
    pack = load()
    assert len(pack.deck) == 9
    for card in pack.deck:
        assert isinstance(card, CardDef)
        assert card.name
        assert card.cost >= 0


def test_pack_builds_a_policy():
    policy = load().make_policy()
    assert isinstance(policy, Policy)


def test_unknown_champion_raises():
    with pytest.raises(ValueError, match="未知英雄包"):
        load("不存在的英雄")


def test_empty_name_falls_back_to_default():
    assert load("").name == load().name
