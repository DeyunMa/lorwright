"""重连页识别：静态标题（「重新連線中」或「連線中」）与底部退出按钮必须同时出现。"""

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
        self._titles: tuple[np.ndarray, ...] = ()
        self._button: np.ndarray | None = None

    def load(self) -> None:
        self._titles = tuple(title for name in ("reconnect_title.png", "connecting_title.png")
                             if (title := _read(self.root / name)) is not None)
        self._button = _read(self.root / "reconnect_exit_button.png")

    def detect(self, image: np.ndarray) -> bool:
        if image.shape != (1080, 1920, 3) or image.dtype != np.uint8:
            return False
        if not self._titles or self._button is None:
            return False
        # 固定设计区域内留少量定位余量；标题模板不包含右侧动态省略号。
        # 对局背景的蓝光会降低标题对比度，标题分数略低时要求更完整的按钮证据。
        title = _detail(image[500:580, 750:1060])
        button = _detail(image[910:1045, 800:1120])
        return any((exists(title, template, self.threshold)
                    and exists(button, self._button, self.threshold)) or (
            exists(title, template, self.threshold - 0.02)
            and exists(button, self._button, max(0.92, self.threshold))
        ) for template in self._titles)


def _detail(image: np.ndarray) -> np.ndarray:
    # 去掉模糊背景的低频明暗，保留静态字形与按钮纹理。
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
    return gray - cv2.GaussianBlur(gray, (0, 0), 3)


def _read(path: Path) -> np.ndarray | None:
    image = cv2.imread(str(path)) if path.is_file() else None
    return _detail(image) if image is not None else None
