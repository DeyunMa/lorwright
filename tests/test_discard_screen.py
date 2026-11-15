from lorwright.core.decide.discard import choose_discard
from lorwright.core.models import DiscardCandidates, Rect


def test_cost_ranking_and_unreadable_costs():
    cards = tuple(Rect(i, 0, 1, 1) for i in range(3))
    duplicate = ((1.0, 0.8, 0.1), (0.8, 1.0, 0.1), (0.1, 0.1, 1.0))
    distinct = ((1.0, 0.1, 0.1), (0.1, 1.0, 0.1), (0.1, 0.1, 1.0))
    assert choose_discard(DiscardCandidates(cards, duplicate, (1, 3, 9))).card_index == 1
    assert choose_discard(DiscardCandidates(cards, distinct, (1, 3, 9))).card_index == 2
    assert choose_discard(DiscardCandidates(cards, duplicate, (1, None, 9))) is None
    assert choose_discard(DiscardCandidates(cards, distinct, (1, None, 9))) is None
    assert choose_discard(DiscardCandidates(cards, duplicate, (1, 3, None))).card_index == 1
