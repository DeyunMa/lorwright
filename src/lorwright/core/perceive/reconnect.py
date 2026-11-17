"""重连页识别：静态标题与底部退出按钮必须同时出现。"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from lorwright.core.perceive.locate import exists

__all__ = ["ReconnectDetector"]


class ReconnectDetector:
    """只接受调用者已归一化的 1920×1080 BGR 图像。"""

    def __init__(
        self,
        root: str | Path = "assets/ui",
        threshold: float = 0.85,
    ) -> None:
        self.root = Path(root)
        self.threshold = threshold
        self._title: np.ndarray | None = None
        self._button: np.ndarray | None = None

    def load(self) -> None:
        self._title = _read(self.root / "reconnect_title.png")
        self._button = _read(self.root / "reconnect_exit_button.png")

    def detect(self, image: np.ndarray) -> bool:
        if image.shape != (1080, 1920, 3) or image.dtype != np.uint8:
            return False
        if self._title is None or self._button is None:
            return False
        # 固定设计区域内留少量定位余量；标题模板不包含右侧动态省略号。
        return (
            exists(_detail(image[500:580, 750:1060]), self._title, self.threshold)
            and exists(_detail(image[910:1045, 800:1120]), self._button, self.threshold)
        )


def _detail(image: np.ndarray) -> np.ndarray:
    # 去掉模糊背景的低频明暗，保留静态字形与按钮纹理。
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
    return gray - cv2.GaussianBlur(gray, (0, 0), 3)


def _read(path: Path) -> np.ndarray | None:
    image = cv2.imread(str(path)) if path.is_file() else None
    return _detail(image) if image is not None else None
