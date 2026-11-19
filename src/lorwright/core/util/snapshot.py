"""出错时保存截图，便于复盘。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np

from lorwright.core.util.logger import logger


def save_snapshot(frame: np.ndarray, out_dir: str = "logs/snapshots", tag: str = "error") -> Path | None:
    """保存一帧图像。写入失败时记录原因，由调用方保留原停止结果。"""
    import cv2

    name = f"{tag}_{datetime.now():%Y%m%d_%H%M%S_%f}.png"
    path = Path(out_dir) / name
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(path), frame):
            logger.warning("snapshot write failed: {}", path)
            return None
    except (OSError, cv2.error) as exc:
        logger.warning("snapshot write failed: {} ({})", path, exc)
        return None
    logger.debug("snapshot saved: {}", path)
    return path
