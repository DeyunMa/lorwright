"""设计坐标空间：归一化与反算。"""

from __future__ import annotations

import numpy as np

from lorwright.perceive.normalize import Normalizer, Scale


def test_identity_when_size_matches() -> None:
    norm = Normalizer((1920, 1080))
    img = np.zeros((1080, 1920, 3), np.uint8)
    out, scale = norm.fit(img)
    assert out is img, "尺寸一致时不该重采样"
    assert scale.identity
    assert scale.to_device(960, 540) == (960, 540)


def test_downscale_keeps_design_coordinates() -> None:
    """实际分辨率更大时缩小到设计尺寸，动作坐标反算回原像素。"""
    norm = Normalizer((1920, 1080))
    img = np.zeros((2160, 3840, 3), np.uint8)
    out, scale = norm.fit(img)
    assert out.shape[:2] == (1080, 1920)
    assert scale.to_device(960, 540) == (1920, 1080)


def test_upscale_for_small_frames() -> None:
    norm = Normalizer((1920, 1080))
    out, scale = norm.fit(np.zeros((720, 1280, 3), np.uint8))
    assert out.shape[:2] == (1080, 1920)
    # 设计坐标 (1920,1080) → 设备像素 (1280,720)
    assert scale.to_device(1920, 1080) == (1280, 720)


def test_scale_roundtrip() -> None:
    scale = Scale(sx=1280 / 1920, sy=720 / 1080)
    for x, y in [(0, 0), (960, 540), (1920, 1080), (1433, 967)]:
        dx, dy = scale.to_device(x, y)
        rx, ry = scale.to_design(dx, dy)
        assert abs(rx - x) <= 1 and abs(ry - y) <= 1
