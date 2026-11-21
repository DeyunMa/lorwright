
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
def test_obscured_discard_candidate_is_dropped_not_clicked(bounds):
    """证据不足的锚点被丢弃；剩余候选不足或全丢时返回 None，且不点被遮挡位置。"""
    from lorwright.core.perceive.digits import DigitReader
    from lorwright.core.perceive.discard import discard_candidates

    image = cv2.imread(str(fixtures_root() / "screens/f1-discard-candidates-20261117.png"))
    x1, y1, x2, y2 = bounds
    image[y1:y2, x1:x2] = 0
    digits = DigitReader("assets/digits")
    digits.load()
    candidates = discard_candidates(image, digits)
    if candidates is None:
        return
    action = choose_discard(candidates)
    if action is None:
        return
    center = candidates.cards[action.card_index].center
    assert not (x1 <= center[0] <= x2 and y1 <= center[1] <= y2)


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


def test_discard_drops_spurious_hough_anchor_on_card_emblem():
    """20261121T003005 停止帧：砰砰关键字徽记产生伪圆，蓝色边框核验不通过；
    边缘裁掉的卡费用圆在搜索区外。保留三个可见砰砰，费用均为 1。"""
    from lorwright.core.perceive.digits import DigitReader
    from lorwright.core.perceive.discard import discard_candidates

    image = cv2.imread(str(fixtures_root() / "screens/f1-discard-spurious-anchor-20261121.png"))
    if image is None:
        pytest.skip("missing f1-discard-spurious-anchor-20261121.png")
    digits = DigitReader("assets/digits")
    digits.load()
    candidates = discard_candidates(image, digits)
    assert candidates is not None
    assert len(candidates.cards) == 3
    assert candidates.costs == (1, 1, 1)
    # 三张砰砰插画互为重复。
    for i, row in enumerate(candidates.similarities):
        for j, score in enumerate(row):
            if i != j:
                assert score >= 0.55
    action = choose_discard(candidates)
    assert action is not None and action.raw["duplicate"]
    center = candidates.cards[action.card_index].center
    assert 0 <= center[0] < 1920 and 500 <= center[1] <= 900


def test_discard_reads_green_one_with_detached_edge_fragment():
    """20261121T011026 停止帧：最左砰砰的绿色「1」带 7×10 碎笔画（核心 1px），
    旧核心成员判定逃过边缘排除致双字一致性失败。修后五张全读。"""
    from lorwright.core.perceive.digits import DigitReader
    from lorwright.core.perceive.discard import discard_candidates

    image = cv2.imread(str(fixtures_root() / "screens/f1-discard-cost-20261121.png"))
    if image is None:
        pytest.skip("missing f1-discard-cost-20261121.png")
    digits = DigitReader("assets/digits")
    digits.load()
    candidates = discard_candidates(image, digits)
    assert candidates is not None
    assert len(candidates.cards) == 5
    assert candidates.costs == (1, 1, 3, 1, 1)
    action = choose_discard(candidates)
    assert action is not None
    assert action.card_index in (0, 1)  # 重复砰砰
    assert action.raw["duplicate"]


def test_discard_returns_none_when_no_anchor_passes_evidence():
    """所有锚点都缺蓝色边框（全部涂黑）时仍返回 None。"""
    from lorwright.core.perceive.digits import DigitReader
    from lorwright.core.perceive.discard import discard_candidates

    image = cv2.imread(str(fixtures_root() / "screens/f1-discard-spurious-anchor-20261121.png"))
    if image is None:
        pytest.skip("missing f1-discard-spurious-anchor-20261121.png")
    # 涂黑每个锚点左侧的蓝色边框，Hough 圆仍在但全部不过证据。
    for x, y in ((378, 634), (734, 592), (1010, 710), (1096, 588)):
        image[y - 35:y + 105, x - 65:x - 30] = 0
    digits = DigitReader("assets/digits")
    digits.load()
    assert discard_candidates(image, digits) is None


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

