from lorwright.champions import load
from lorwright.champions.jinx.deck import BY_CODE
from lorwright.decide.card import CardKind


def test_jinx_deck_has_nine_types_and_key_cards():
    pack = load("jinx")
    assert len(pack.deck) == 9
    assert len({card.name for card in pack.deck}) == 9
    assert BY_CODE["01PZ040"].kind is CardKind.CHAMPION
    assert BY_CODE["01PZ028"].kind is CardKind.SPELL
    assert BY_CODE["01PZ045"].name == "佐恩小乞丐"


def test_jinx_lookup_accepts_common_alias():
    pack = load("jinx")
    assert pack.lookup("祖安小乞丐").name == "佐恩小乞丐"
    assert pack.lookup("不存在") is None
