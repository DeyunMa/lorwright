"""实拍可选三选牌界面；不推断卡牌名称或机制。"""

from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from lorwright.core.models import UIState


@lru_cache(maxsize=3)
def _template(name: str) -> np.ndarray:
    image = cv2.imread(str(Path("assets/ui") / f"optional_choice_{name}.png"),
                       cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise FileNotFoundError(f"optional_choice_{name}.png")
    return image


def _visible(gray: np.ndarray, name: str, area: tuple[int, int, int, int],
             threshold: float = 0.90) -> bool:
    x, y, w, h = area
    patch = gray[y:y + h, x:x + w]
    template = _template(name)
    scores = cv2.matchTemplate(patch, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, (dx, dy) = cv2.minMaxLoc(scores)
    matched = patch[dy:dy + template.shape[0], dx:dx + template.shape[1]]
    bright = template > 180
    return score >= threshold and float(matched[bright].mean()) >= 180


def _controls(image: np.ndarray) -> tuple[bool, bool, list[bool]] | None:
    """三项控件证据：跳过文字、收起控件、三列候选费用框。"""
    if image.shape[:2] != (1080, 1920):
        return None
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    skip = _visible(gray, "skip", (1685, 505, 125, 80))
    # 收起控件本体固定，但模板含棋盘背景；bg2 覆盖棕色棋盘变体
    # （20261121T113114 停帧 0.890<0.90）。
    collapse = (_visible(gray, "collapse", (195, 245, 95, 100))
                or _visible(gray, "collapse_bg2", (195, 245, 95, 100)))
    costs = [_visible(gray, "cost_edge", (x, 325, 70, 80), 0.85)
             for x in (490, 810, 1130)]
    return skip, collapse, costs


def required_choice_layout(image: np.ndarray) -> bool:
    """收起控件与三列费用框齐全且没有跳过文字：可能是强制选牌。

    单凭控件区分不了「可选但跳过文字暂未认出」，由调用方结合动作
    按钮文字「選擇目標」确认；部分证据只保证不是普通战斗画面。
    """
    controls = _controls(image)
    if controls is None:
        return False
    skip, collapse, costs = controls
    return collapse and all(costs) and not skip


def optional_choice_state(image: np.ndarray) -> UIState | None:
    """控件不完整时阻止蓝色按钮兜底；仅覆盖已标定的三列布局。"""
    controls = _controls(image)
    if controls is None:
        return None
    skip, collapse, costs = controls
    if skip and collapse and all(costs):
        return UIState.OPTIONAL_CHOICE
    # 两列已构成部分选择布局；单个费用框也可能出现在普通战斗中。
    # 收起控件是普通战斗界面也常驻的收牌按钮，单独不算选择证据。
    if skip or sum(costs) >= 2:
        return UIState.UNKNOWN
    return None
