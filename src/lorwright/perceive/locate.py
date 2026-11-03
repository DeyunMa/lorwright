"""模板匹配：在截图里找按钮 / 图标 / 卡面。"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from lorwright.models import Rect


def load_template(path: str | Path) -> np.ndarray:
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"模板不存在或无法读取: {path}")
    return img


def find_all(
    frame: np.ndarray,
    template: np.ndarray,
    threshold: float = 0.85,
) -> list[tuple[Rect, float]]:
    """返回所有匹配位置及置信度，按置信度降序。"""
    # 常数模板（零方差）在 TM_CCOEFF_NORMED 下是除零，结果依平台而异：
    # Apple Silicon 上出 NaN，x86 上出 1.0。这种模板本身没有可定位的特征，
    # 直接判为「没找到」，否则同一份代码在 Mac 和 Windows 上结论相反。
    if float(template.std()) < 1e-6:
        return []

    # 模板比画面还大：matchTemplate 会直接抛断言错误。
    # 分辨率变了、或模板采错时会出现，按「没找到」处理。
    fh, fw = frame.shape[:2]
    th, tw = template.shape[:2]
    if th > fh or tw > fw:
        return []

    res = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)
    res = np.nan_to_num(res, nan=-1.0, posinf=-1.0, neginf=-1.0)
    ys, xs = np.where(res >= threshold)

    hits: list[tuple[Rect, float]] = []
    for x, y in zip(xs, ys, strict=False):
        hits.append((Rect(int(x), int(y), tw, th), float(res[y, x])))

    # 非极大值抑制（简单版：按置信度排序后去掉重叠）
    hits.sort(key=lambda h: h[1], reverse=True)
    kept: list[tuple[Rect, float]] = []
    for rect, score in hits:
        if all(_iou(rect, k[0]) < 0.3 for k in kept):
            kept.append((rect, score))
    return kept


def find_one(
    frame: np.ndarray,
    template: np.ndarray,
    threshold: float = 0.85,
) -> tuple[Rect, float] | None:
    hits = find_all(frame, template, threshold)
    return hits[0] if hits else None


def exists(frame: np.ndarray, template: np.ndarray, threshold: float = 0.85) -> bool:
    return find_one(frame, template, threshold) is not None


def _iou(a: Rect, b: Rect) -> float:
    x1 = max(a.x, b.x)
    y1 = max(a.y, b.y)
    x2 = min(a.x + a.w, b.x + b.w)
    y2 = min(a.y + a.h, b.y + b.h)
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    if inter == 0:
        return 0.0
    return inter / (a.area + b.area - inter)
