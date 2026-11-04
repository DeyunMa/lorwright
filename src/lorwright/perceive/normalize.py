"""设计坐标空间：把任意分辨率的截图归一化到标定尺寸。

为什么需要它：`config/settings.yaml` 里的 `layout` 坐标、`assets/` 里的模板
都是按某一个分辨率（现在 1920×1080）标的。换设备 / 换模拟器实例 / `wm size`
失效时，像素坐标全错，得重新标定一遍——我们为此踩过好几次。

做法（MaaFramework 的思路）：识别一律在**固定的设计尺寸**上做，动作坐标再
按同一个比例反算回设备像素。于是模板和坐标只跟设计尺寸有关，跟实际分辨率无关。

注意设计尺寸不是越小越好：我们的数字字形在 720p 只有 ~10px，读不出来，
所以才把设计尺寸定在 1080p。实际分辨率更小时会被放大（模糊，但坐标仍然对），
更大时会缩小。
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

__all__ = ["Scale", "Normalizer"]


@dataclass(frozen=True)
class Scale:
    """设计坐标 ↔ 设备像素。"""

    sx: float
    sy: float

    def to_device(self, x: float, y: float) -> tuple[int, int]:
        return int(round(x * self.sx)), int(round(y * self.sy))

    def to_design(self, x: float, y: float) -> tuple[int, int]:
        return int(round(x / self.sx)), int(round(y / self.sy))

    @property
    def identity(self) -> bool:
        return abs(self.sx - 1.0) < 1e-6 and abs(self.sy - 1.0) < 1e-6


class Normalizer:
    """按设计尺寸归一化截图。"""

    def __init__(self, design: tuple[int, int]) -> None:
        self.design = design

    def fit(self, image: np.ndarray) -> tuple[np.ndarray, Scale]:
        """返回（设计尺寸的图，缩放系数）。尺寸一致时原样返回，不做重采样。"""
        dh, dw = self.design[1], self.design[0]
        h, w = image.shape[:2]
        scale = Scale(sx=w / dw, sy=h / dh)
        if (w, h) == (dw, dh):
            return image, scale
        # 宽高比不一致（旋转 / 裁切）时按比例强行拉到设计尺寸：
        # 模板仍能匹配，坐标仍能反算，但会失真——所以打日志让人知道。
        resized = cv2.resize(image, (dw, dh), interpolation=cv2.INTER_AREA)
        return resized, scale
