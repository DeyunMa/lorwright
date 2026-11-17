from pathlib import Path

import cv2
import pytest

from lorwright.core.decide.discard import choose_discard
from lorwright.core.models import DiscardCandidates, Rect


def test_discard_candidates_include_visible_edge_cards():
    from lorwright.core.perceive.digits import DigitReader
    from lorwright.core.perceive.discard import discard_candidates

    image = cv2.imread(str(Path(__file__).parent / "fixtures/screens/f1-discard-candidates-20261117.png"))
    digits = DigitReader("assets/digits")
    digits.load()
    candidates = discard_candidates(image, digits)
    assert candidates is not None
    assert len(candidates.cards) == 4
    assert candidates.costs[:2] == (1, 1)
    action = choose_discard(candidates)
    assert action is not None
    assert action.card_index in (0, 1)
    assert action.raw["duplicate"]


@pytest.mark.parametrize("bounds", [(87, 640, 122, 785), (467, 570, 502, 715),
                                    (126, 654, 178, 706)])
def test_obscured_discard_border_or_selected_cost_blocks_input(bounds):
    from lorwright.core.perceive.digits import DigitReader
    from lorwright.core.perceive.discard import discard_candidates

    image = cv2.imread(str(Path(__file__).parent / "fixtures/screens/f1-discard-candidates-20261117.png"))
    x1, y1, x2, y2 = bounds
    image[y1:y2, x1:x2] = 0
    digits = DigitReader("assets/digits")
    digits.load()
    candidates = discard_candidates(image, digits)
    assert candidates is None or choose_discard(candidates) is None


def test_cost_ranking_and_unreadable_costs():
    cards = tuple(Rect(i, 0, 1, 1) for i in range(3))
    duplicate = ((1.0, 0.8, 0.1), (0.8, 1.0, 0.1), (0.1, 0.1, 1.0))
    distinct = ((1.0, 0.1, 0.1), (0.1, 1.0, 0.1), (0.1, 0.1, 1.0))
    assert choose_discard(DiscardCandidates(cards, duplicate, (1, 3, 9))).card_index == 1
    assert choose_discard(DiscardCandidates(cards, distinct, (1, 3, 9))).card_index == 2
    assert choose_discard(DiscardCandidates(cards, duplicate, (1, None, 9))) is None
    assert choose_discard(DiscardCandidates(cards, distinct, (1, None, 9))) is None
    assert choose_discard(DiscardCandidates(cards, duplicate, (1, 3, None))).card_index == 1
