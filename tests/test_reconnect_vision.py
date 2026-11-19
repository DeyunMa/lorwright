"""用安全裁剪合成重连页，并以现有实拍场景排除误命中。"""

from pathlib import Path

import cv2
import numpy as np
import pytest

from lorwright.core.perceive.reconnect import ReconnectDetector
from tools.test_data import fixtures_root

ASSETS = Path("assets/ui")
SCREENS = sorted(
    path for path in (fixtures_root() / "screens").iterdir()
    if path.suffix.lower() in {".png", ".jpg"}
)
CROPS = (
    ("reconnect_title.png", 768, 514),
    ("reconnect_exit_button.png", 821, 927),
)


@pytest.fixture
def detector() -> ReconnectDetector:
    result = ReconnectDetector()
    result.load()
    return result


def _paste(image: np.ndarray, index: int, dx: int = 0, dy: int = 0) -> None:
    name, x, y = CROPS[index]
    crop = cv2.imread(str(ASSETS / name))
    assert crop is not None
    h, w = crop.shape[:2]
    image[y + dy:y + dy + h, x + dx:x + dx + w] = crop


def _scene(dx: int = 0, dy: int = 0) -> np.ndarray:
    # 完整原帧含账户信息，不入库；这里只把两个安全裁剪放到合成背景。
    image = np.full((1080, 1920, 3), 90, dtype=np.uint8)
    _paste(image, 0, dx, dy)
    _paste(image, 1, dx, dy)
    return image


@pytest.mark.parametrize("dx,dy", [(0, 0), (-8, -8), (8, 8)])
def test_title_and_button_match_with_small_offset(detector, dx, dy):
    assert detector.detect(_scene(dx, dy)) is True


@pytest.mark.parametrize("visible", [(), (0,), (1,)])
def test_both_evidence_required(detector, visible):
    image = np.full((1080, 1920, 3), 90, dtype=np.uint8)
    for index in visible:
        _paste(image, index)
    assert detector.detect(image) is False


@pytest.mark.parametrize("dots", [0, 1, 3, 6])
def test_animated_ellipsis_is_ignored(detector, dots):
    image = _scene()
    for index in range(dots):
        cv2.circle(image, (1052 + index * 18, 542), 4, (170, 170, 170), -1)
    assert detector.detect(image) is True


@pytest.mark.parametrize("brightness", [-45, 45])
def test_smooth_background_changes_preserve_detection(detector, brightness):
    image = _scene().astype(np.float32)
    # 在字形下方也改变低频背景，验证不依赖裁剪时的底图明暗。
    gradient = np.linspace(-35, 35, 1920, dtype=np.float32)[None, :, None]
    image = np.clip(image + gradient + brightness, 0, 255).astype(np.uint8)
    assert detector.detect(image) is True


def test_weak_reconnect_title_requires_strong_exit_button(detector):
    image = _scene()
    title = image[500:580, 750:1060]
    title[:] = cv2.GaussianBlur(title, (0, 0), 1.28)
    assert detector.detect(image) is True
    image[910:1045, 800:1120] = 90
    assert detector.detect(image) is False


def test_jpeg_compression_preserves_detection(detector):
    encoded, data = cv2.imencode(".jpg", _scene(), [cv2.IMWRITE_JPEG_QUALITY, 85])
    assert encoded
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    assert detector.detect(image) is True


@pytest.mark.parametrize("path", SCREENS, ids=lambda path: path.name)
def test_existing_screens_are_not_reconnect(detector, path):
    image = cv2.imread(str(path))
    assert image is not None
    assert detector.detect(image) is False
    if image.shape == (1080, 1920, 3):
        # 非重连实拍上单独出现同款退出按钮或标题，仍不足以确认重连页。
        for index in range(2):
            partial = image.copy()
            _paste(partial, index)
            assert detector.detect(partial) is False


@pytest.mark.parametrize("shape", [(720, 1280, 3), (540, 960, 3), (1080, 1919, 3),
                                    (1079, 1920, 3), (1080, 1920), (1080, 1920, 4)])
def test_wrong_size_or_channels_safely_rejected(detector, shape):
    assert detector.detect(np.zeros(shape, dtype=np.uint8)) is False


def test_unnormalized_and_unloaded_inputs_safely_rejected(detector):
    image = _scene()
    assert ReconnectDetector().detect(image) is False
    assert detector.detect(image.astype(np.float32)) is False
    assert detector.detect(cv2.resize(image, (1280, 720))) is False


@pytest.mark.parametrize("missing", [0, 1])
def test_missing_either_template_safely_rejected(tmp_path, missing):
    name = CROPS[1 - missing][0]
    (tmp_path / name).write_bytes((ASSETS / name).read_bytes())
    detector = ReconnectDetector(root=tmp_path)
    detector.load()
    assert detector.detect(_scene()) is False
