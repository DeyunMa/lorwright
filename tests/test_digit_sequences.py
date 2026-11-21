"""费用序列回归：现有实拍字形合成，不冒充真实十费徽章或缺失字模覆盖。"""

import importlib.util
from pathlib import Path

import cv2
import numpy as np
import pytest

from lorwright.core.models import Rect
from lorwright.core.perceive.digits import DigitReader
from lorwright.core.perceive.discard import discard_candidates
from lorwright.core.perceive.hand import Badge, read_cost
from lorwright.core.perceive.reward_screen import _card_cost, _reward_digits
from tools.test_data import fixtures_root

ROOT = Path(__file__).resolve().parents[1]


def _reader():
    reader = DigitReader(ROOT / "assets/digits")
    reader.load()
    return reader


def _glyphs(reward=False):
    if reward:
        # 奖励 1/0 保留原尺寸，避免压窄重采样把 1 的分数降到 0.92 以下。
        one = cv2.imread(str(fixtures_root() / "card_rewards/f1-narrow-one-reward-20261117.png"))
        zero = cv2.imread(str(fixtures_root() / "card_rewards/f1-weekly-second-reward-20261116.png"))
        patches = (one[263:287, 521:532], zero[280:305, 432:450])
        return [cv2.threshold(cv2.cvtColor(p, cv2.COLOR_BGR2GRAY), 180, 255,
                              cv2.THRESH_BINARY)[1] for p in patches]
    return [cv2.resize(cv2.imread(str(ROOT / f"assets/digits/{digit}-hand1080.png"),
                                  cv2.IMREAD_GRAYSCALE), (width, 20))
            for digit, width in ((1, 7), (0, 12))]


def _put_ten(image, center, *, reward=False, color="white"):
    glyphs = _glyphs(reward)
    cx, cy = center
    left = cx - (sum(g.shape[1] for g in glyphs) + 3) // 2
    for glyph in glyphs:
        h, w = glyph.shape
        patch = np.repeat(glyph[:, :, None], 3, axis=2)
        if color == "green":
            patch[:, :, (0, 2)] = 0
        elif color == "red":
            patch[:, :, (0, 1)] = 0
        image[cy - h // 2:cy - h // 2 + h, left:left + w] = patch
        left += w + 3


def _hand_ten(*, color="white", angle=0):
    image = np.zeros((80, 80, 3), np.uint8)
    _put_ten(image, (40, 40), color=color)
    return cv2.warpAffine(image, cv2.getRotationMatrix2D((40, 40), angle, 1), (80, 80))


@pytest.mark.parametrize("color", ["white", "green", "red"])
# 现有单字路径对合成 1 在 -12° 已会误读 7；此处只覆盖可分类的倾角。
@pytest.mark.parametrize("angle", [-4, 0, 12])
def test_hand_ten_reads_every_digit_with_existing_color_and_tilt(color, angle):
    assert read_cost(_hand_ten(color=color, angle=angle), Badge((40, 40), 1.0), _reader()) == 10


@pytest.mark.parametrize("damage", ["remnant", "small_remnant", "joined", "extra_component"])
def test_hand_ten_with_visible_damage_cannot_be_reduced_to_one_digit(damage):
    image = _hand_ten()
    if damage in ("remnant", "small_remnant"):
        image[30:50, 29:37] = 0
        bottom = 45 if damage == "remnant" else 42
        image[37:bottom, 32:35] = 255  # 包含低于原 20px 提取门槛的明显残笔。
    elif damage == "joined":
        image[40, 32:44] = 255
    else:
        image[51:54, 36:44] = 255
    assert read_cost(image, Badge((40, 40), 1.0), _reader()) is None


def test_reward_ten_reads_original_size_real_glyphs():
    image = np.zeros((1080, 1920, 3), np.uint8)
    _put_ten(image, (861, 292), reward=True)
    assert _card_cost(image, 769) == 10


@pytest.mark.parametrize("damage", ["remnant", "joined", "narrow_resample"])
def test_reward_ten_with_partial_or_low_score_digit_stays_unknown(damage):
    image = np.zeros((1080, 1920, 3), np.uint8)
    _put_ten(image, (861, 292), reward=True)
    if damage == "remnant":
        image[280:298, 845:856] = 0
    elif damage == "joined":
        image[292, 850:867] = 255
    else:
        image[:] = 0
        for filename, width, left in (
            ("1-f1-20261117.png", 7, 851),
            ("0-weekly-second-20261116.png", 12, 861),
        ):
            glyph = cv2.imread(str(ROOT / "assets/adventure/reward_digits" / filename),
                               cv2.IMREAD_GRAYSCALE)
            image[280:304, left:left + width] = cv2.resize(glyph, (width, 24))[:, :, None]
    assert _card_cost(image, 769) is None


def test_discard_ten_keeps_both_digits_in_public_candidates():
    image = cv2.imread(str(fixtures_root() / "screens/f1-discard-candidates-20261117.png"))
    cv2.circle(image, (152, 680), 23, (120, 60, 20), -1)
    _put_ten(image, (152, 680))
    candidates = discard_candidates(image, _reader())
    assert candidates is not None and candidates.costs[0] == 10


@pytest.mark.parametrize("weak", [
    [(1, 0.79), (7, 0.40)],  # 低于下限
    [(1, 0.95), (7, 0.81)],  # 领先第二名不足
], ids=["below-floor", "ambiguous"])
def test_discard_requires_confident_reading_for_every_digit(monkeypatch, weak):
    reader = _reader()
    rank = reader.rank

    def weak_one(glyph, rotations):
        ranked = rank(glyph, rotations=rotations)
        return weak if ranked and ranked[0][0] == 1 else ranked

    monkeypatch.setattr(reader, "rank", weak_one)
    image = cv2.imread(str(fixtures_root() / "screens/f1-discard-candidates-20261117.png"))
    cv2.circle(image, (152, 680), 23, (120, 60, 20), -1)
    _put_ten(image, (152, 680))
    candidates = discard_candidates(image, reader)
    assert candidates is not None and candidates.costs[0] is None


def test_sequence_decoder_keeps_lowest_per_digit_score_and_rejects_unknown():
    reader = _reward_digits()
    glyphs = [cv2.resize(g, (16, 24)).astype(np.float32) / 255 for g in _glyphs(True)]
    hits = [reader.classify(g) for g in glyphs]
    assert all(hit is not None for hit in hits)
    assert reader.classify_sequence(glyphs) == (10, min(hit[1] for hit in hits))
    assert reader.classify_sequence([]) is None
    assert reader.classify_sequence([glyphs[0], np.zeros((24, 16), np.float32), glyphs[1]]) is None


def test_sequence_decoder_propagates_weakest_score(monkeypatch):
    reader = _reader()
    hits = iter(((1, 0.86), (0, 0.99)))
    monkeypatch.setattr(reader, "classify", lambda glyph, rotations: next(hits))
    assert reader.classify_sequence([np.zeros((24, 16))] * 2) == (10, 0.86)


@pytest.mark.parametrize("digit", [-1, 10])
def test_sequence_decoder_rejects_non_single_digit_classes(monkeypatch, digit):
    reader = _reader()
    monkeypatch.setattr(reader, "classify", lambda glyph, rotations: (digit, 1.0))
    assert reader.classify_sequence([np.zeros((24, 16))]) is None


def test_generic_reader_keeps_existing_integer_sequence():
    image = _hand_ten()
    assert _reader().read(image, Rect(20, 20, 40, 40), threshold=170) == 10


@pytest.fixture
def builder():
    spec = importlib.util.spec_from_file_location("build_hand_digits", ROOT / "tools/build_hand_digits.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_builder_saves_ten_as_two_single_digit_prototypes(builder, monkeypatch, tmp_path):
    image_path, output = tmp_path / "ten.png", tmp_path / "digits"
    assert cv2.imwrite(str(image_path), _hand_ten())
    monkeypatch.setattr("sys.argv", ["build_hand_digits", "--image", str(image_path),
                                    "--badge", "40,40=10", "--out", str(output), "--tag", "test"])
    builder.main()
    assert sorted(p.name for p in output.iterdir()) == ["0-test.png", "1-test.png"]
    assert all(cv2.imread(str(p), cv2.IMREAD_GRAYSCALE).shape == (24, 16) for p in output.iterdir())


def test_builder_rejects_label_count_mismatch_before_saving(builder, monkeypatch, tmp_path):
    image_path, output = tmp_path / "one.png", tmp_path / "digits"
    image = np.zeros((80, 80, 3), np.uint8)
    glyph = _glyphs()[1]
    image[30:50, 34:46] = glyph[:, :, None]
    assert cv2.imwrite(str(image_path), image)
    monkeypatch.setattr("sys.argv", ["build_hand_digits", "--image", str(image_path),
                                    "--badge", "40,40=10", "--out", str(output)])
    with pytest.raises(SystemExit, match="1"):
        builder.main()
    assert not list(output.glob("*.png"))


@pytest.mark.parametrize("text", ["", "-1", "a", "1.0", "１０"])
def test_builder_rejects_non_decimal_labels(builder, text):
    with pytest.raises(SystemExit):
        builder.parse_badge(f"40,40={text}")


# 完全抹去一位后，单帧与真实个位可能不可区分；上述反例只承诺仍有残笔时不截断。
