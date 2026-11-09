"""数字识别：把 UI 上的小数字（水晶血量、法力、卡牌费用）读成 int。

为什么不用 OCR：这些数字只有 8–24 px 高、字体固定、位置固定。
按高度归一化后做字形模板匹配，比通用 OCR 快一个数量级，也不会被
「0/O」「1/l」混淆。代价是游戏换字体就要重采字形（`tools/build_digits.py`）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from lorwright.models import Rect

#: 归一化后的字形尺寸（宽, 高）。太大会放大噪点，太小会丢笔画。
GLYPH_SIZE = (16, 24)

#: 白色文字 → 二值图。Otsu 在「深色底 + 白字」上很稳，不用手调阈值。
_MIN_AREA = 12
_MIN_WIDTH = 4        # ROI 边界上常粘连一两条 2px 宽的水晶描边，不是字形
_MIN_HEIGHT_RATIO = 0.45
_MAX_ASPECT = 1.6


@dataclass(frozen=True)
class Glyph:
    """从 ROI 里切出来的一个字形（已归一化）。"""

    image: np.ndarray
    rect: Rect          # 在原始截图里的位置

    def __len__(self) -> int:
        return 1


def _to_gray(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img


def normalize_glyph(patch: np.ndarray) -> np.ndarray:
    """裁到笔画外框后缩放到固定尺寸，0..1 float。"""
    ys, xs = np.where(patch > 0)
    if len(xs) == 0:
        return np.zeros((GLYPH_SIZE[1], GLYPH_SIZE[0]), np.float32)
    patch = patch[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    out = cv2.resize(patch, GLYPH_SIZE, interpolation=cv2.INTER_AREA)
    return (out.astype(np.float32) / 255.0).clip(0.0, 1.0)


def segment_glyphs(img: np.ndarray, rect: Rect, threshold: int | None = None) -> list[Glyph]:
    """把矩形区域里的白色数字切成单个字形，按从左到右排序。"""
    patch = img[rect.y : rect.y + rect.h, rect.x : rect.x + rect.w]
    if patch.size == 0:
        return []
    gray = _to_gray(patch)

    if threshold is None:
        threshold, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    _, binary = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)

    count, _, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    boxes = [
        (int(stats[i, 0]), int(stats[i, 1]), int(stats[i, 2]), int(stats[i, 3]), int(stats[i, 4]))
        for i in range(1, count)
        if stats[i, 4] >= _MIN_AREA and stats[i, 2] >= _MIN_WIDTH
    ]
    if not boxes:
        return []

    # 同一行里，数字高度接近；比最高字形矮太多的多半是图标碎片
    tallest = max(b[3] for b in boxes)
    kept = [
        b for b in boxes
        if b[3] >= tallest * _MIN_HEIGHT_RATIO and b[2] <= b[3] * _MAX_ASPECT
    ]

    glyphs: list[Glyph] = []
    for x, y, w, h, _area in sorted(kept):
        sub = binary[y : y + h, x : x + w]
        glyphs.append(
            Glyph(
                image=normalize_glyph(sub),
                rect=Rect(rect.x + x, rect.y + y, w, h),
            )
        )
    return glyphs


def rotate_glyph(image: np.ndarray, angle: float) -> np.ndarray:
    """绕中心旋转字形（正 = 逆时针）。用于手牌徽章里倾斜的数字。"""
    h, w = image.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(image, m, (w, h), flags=cv2.INTER_LINEAR, borderValue=0)


@dataclass
class DigitTemplate:
    digit: int
    image: np.ndarray
    source: str = ""


class DigitReader:
    """字形模板库 + 读数。

    同一个数字可以有多个原型（`6.png`、`6-mulligan720.png`）：字号差一倍时
    同一个字形的像素形态并不一样，只存一个原型会把 13px 的 6 读成 8。
    分类时取所有原型里的最高分，因此每个字号区间各存一份就行。
    """

    def __init__(self, root: str | Path = "assets/digits", min_score: float = 0.60) -> None:
        self.root = Path(root)
        self.min_score = min_score
        self._templates: list[DigitTemplate] = []

    def load(self) -> None:
        self._templates.clear()
        if not self.root.exists():
            return
        for png in sorted(self.root.glob("*.png")):
            head = png.stem.split("-")[0]
            if not head.isdigit():
                continue
            img = cv2.imread(str(png), cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            # 模板可以带黑边（例如用字体渲染的整张画布）；先裁到笔画外框，
            # 否则缩放到 16×24 时数字会被黑边压小，相似度直接掉到噪声。
            ys, xs = np.where(img > 0)
            if len(xs) == 0:
                continue
            img = img[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
            if img.shape != (GLYPH_SIZE[1], GLYPH_SIZE[0]):
                img = cv2.resize(img, GLYPH_SIZE, interpolation=cv2.INTER_AREA)
            self._templates.append(
                DigitTemplate(
                    digit=int(head),
                    image=(img.astype(np.float32) / 255.0).clip(0.0, 1.0),
                    source=png.stem,
                )
            )

    def __len__(self) -> int:
        return len(self._templates)

    @property
    def digits(self) -> set[int]:
        return {t.digit for t in self._templates}

    def classify(
        self, image: np.ndarray, rotations: tuple[int, ...] = (0,)
    ) -> tuple[int, float] | None:
        """识别一个归一化字形。`rotations` 给出要试的角度（手牌徽章里的数字会斜）。"""
        if not self._templates:
            return None
        best: tuple[int, float] | None = None
        for angle in rotations:
            rotated = image if angle == 0 else rotate_glyph(image, angle)
            for tpl in self._templates:
                score = _similarity(rotated, tpl.image)
                if best is None or score > best[1]:
                    best = (tpl.digit, score)
        if best is None or best[1] < self.min_score:
            return None
        return best

    def read(self, img: np.ndarray, rect: Rect, threshold: int | None = None) -> int | None:
        """读矩形区域里的整数。切不出字形、或有字形认不出，都返回 None。"""
        glyphs = segment_glyphs(img, rect, threshold)
        if not glyphs:
            return None
        out = ""
        for glyph in glyphs:
            hit = self.classify(glyph.image)
            if hit is None:
                return None
            out += str(hit[0])
        return int(out)


def _similarity(a: np.ndarray, b: np.ndarray) -> float:
    """归一化互相关，等价于把两边都去均值后求余弦。"""
    av = a.ravel() - a.mean()
    bv = b.ravel() - b.mean()
    denom = float(np.linalg.norm(av) * np.linalg.norm(bv))
    if denom < 1e-6:
        return 0.0
    return float(av @ bv) / denom
