"""出错时保存截图，便于复盘。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np

from lorwright.util.logger import logger


def save_snapshot(frame: np.ndarray, out_dir: str = "logs/snapshots", tag: str = "error") -> Path:
    """保存一帧图像，返回路径。"""
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    name = f"{tag}_{datetime.now():%Y%m%d_%H%M%S_%f}.png"
    path = d / name

    import cv2

    cv2.imwrite(str(path), frame)
    logger.debug("snapshot saved: {}", path)
    return path
