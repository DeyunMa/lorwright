
import cv2
import pytest

from lorwright.core.decide.discard import choose_discard
from lorwright.core.models import DiscardCandidates, Rect
from tools.test_data import fixtures_root


def test_discard_candidates_include_visible_edge_cards():
    from lorwright.core.perceive.digits import DigitReader
    from lorwright.core.perceive.discard import discard_candidates

    image = cv2.imread(str(fixtures_root() / "screens/f1-discard-candidates-20261117.png"))
    digits = DigitReader("assets/digits")
    digits.load()
    candidates = discard_candidates(image, digits)
    assert candidates is not None
    assert len(candidates.cards) == 4
    # The last two badges supply the discard1080 prototypes at (1306, 594) and (1702, 642).
    assert candidates.costs == (1, 1, 1, 6)
    action = choose_discard(candidates)
    assert action is not None
    assert action.card_index in (0, 1)
    assert action.raw["duplicate"]


@pytest.mark.parametrize("bounds", [(87, 640, 122, 785), (467, 570, 502, 715),
                                    (126, 654, 178, 706)])
def test_obscured_discard_border_or_selected_cost_blocks_input(bounds):
    from lorwright.core.perceive.digits import DigitReader
    from lorwright.core.perceive.discard import discard_candidates

    image = cv2.imread(str(fixtures_root() / "screens/f1-discard-candidates-20261117.png"))
    x1, y1, x2, y2 = bounds
    image[y1:y2, x1:x2] = 0
    digits = DigitReader("assets/digits")
    digits.load()
    candidates = discard_candidates(image, digits)
    assert candidates is None or choose_discard(candidates) is None


@pytest.mark.parametrize(("index", "bounds"), [
    (2, (1292, 582, 1320, 594)),
    (3, (1688, 630, 1716, 642)),
], ids=["partial-one", "six-without-top-stroke"])
def test_discard_partial_glyph_is_not_read_as_another_cost(index, bounds):
    from lorwright.core.perceive.digits import DigitReader
    from lorwright.core.perceive.discard import discard_candidates

    image = cv2.imread(str(fixtures_root() / "screens/f1-discard-candidates-20261117.png"))
    x1, y1, x2, y2 = bounds
    # Cover the glyph inside the badge without removing the card or badge border.
    image[y1:y2, x1:x2] = (120, 60, 20)
    digits = DigitReader("assets/digits")
    digits.load()
    candidates = discard_candidates(image, digits)
    assert candidates is not None
    expected = [1, 1, 1, 6]
    expected[index] = None
    assert candidates.costs == tuple(expected)


def test_discard_ignores_isolated_highlight_at_badge_perimeter():
    from lorwright.core.perceive.digits import DigitReader
    from lorwright.core.perceive.discard import discard_candidates

    image = cv2.imread(str(fixtures_root() / "screens/f1-discard-candidates-20261117.png"))
    cv2.circle(image, (1289, 579), 3, (238, 238, 238), -1)
    digits = DigitReader()
    digits.load()
    candidates = discard_candidates(image, digits)
    assert candidates is not None
    assert candidates.costs == (1, 1, 1, 6)


def test_cost_ranking_and_unreadable_costs():
    cards = tuple(Rect(i, 0, 1, 1) for i in range(3))
    duplicate = ((1.0, 0.8, 0.1), (0.8, 1.0, 0.1), (0.1, 0.1, 1.0))
    distinct = ((1.0, 0.1, 0.1), (0.1, 1.0, 0.1), (0.1, 0.1, 1.0))
    assert choose_discard(DiscardCandidates(cards, duplicate, (1, 3, 9))).card_index == 1
    assert choose_discard(DiscardCandidates(cards, distinct, (1, 3, 9))).card_index == 2
    assert choose_discard(DiscardCandidates(cards, duplicate, (1, None, 9))) is None
    assert choose_discard(DiscardCandidates(cards, distinct, (1, None, 9))) is None
    assert choose_discard(DiscardCandidates(cards, duplicate, (1, 3, None))).card_index == 1


def test_discard_reads_reduced_green_costs_under_highlight():
    # 20261120T071319 的 discard_cost_unverified 停止原图；砰砰 1 费、打磨心志 0 费为绿色减费数字。
    from lorwright.core.perceive.digits import DigitReader
    from lorwright.core.perceive.discard import discard_candidates

    image = cv2.imread(str(fixtures_root() / "screens/f1-discard-green-costs-20261120.png"))
    if image is None:
        pytest.skip("missing f1-discard-green-costs-20261120.png")
    digits = DigitReader("assets/digits")
    digits.load()
    candidates = discard_candidates(image, digits)
    assert candidates is not None
    assert candidates.costs == (3, 2, 1, 0)
    action = choose_discard(candidates)
    assert action is not None and action.card_index == 0

