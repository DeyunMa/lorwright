"""辅助英雄援军选择页：仅识别已有截图验证过的画面元素。"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path

import cv2
import numpy as np

from lorwright.decide.support import SupportGroup
from lorwright.models import Rect
from lorwright.perceive.adventure_scene import _template
from lorwright.perceive.digits import segment_glyphs
from lorwright.perceive.reward_screen import _visible_match

_DIGITS = Path("assets/adventure/support_digits")
_CARD_X = (308, 778, 1244)
_CARD_Y = (422, 493, 565)
_GROUP_X_960 = (142, 376, 610)
_HIGHLIGHT_Y_960 = (203, 239, 276, 317)


@dataclass(frozen=True)
class SupportChoice:
    group: SupportGroup
    target: Rect


@cache
def _digit_templates() -> dict[int, list[np.ndarray]]:
    templates: dict[int, list[np.ndarray]] = {}
    for path in sorted(_DIGITS.glob("*.png")):
        prefix = path.stem.split("-")[0]
        if not prefix.isdigit():
            continue
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if image is not None and image.shape == (24, 16):
            templates.setdefault(int(prefix), []).append(image.astype(np.float32) / 255.0)
    return templates


def is_support_screen(image: np.ndarray) -> bool:
    """标题和副标题同时可见；遮罩或非设计尺寸时拒绝。"""
    if image.shape != (1080, 1920, 3):
        return False
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return (
        _visible_match(gray, "support_title", (760, 15, 1160, 110)) >= 0.93
        and _visible_match(gray, "support_subtitle", (800, 125, 1120, 200)) >= 0.86
    )


def support_selection(image: np.ndarray) -> int | None:
    """返回选中组 0–2；-1 为未选中，None 为不可确定。"""
    if not is_support_screen(image):
        return None
    small = cv2.resize(image, (960, 540), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    bright = (hsv[:, :, 2] > 220) & (hsv[:, :, 1] < 120)
    bands = [
        [float(bright[y:y + 5, x:x + 208].mean()) for y in _HIGHLIGHT_Y_960]
        for x in _GROUP_X_960
    ]
    button = hsv[480:520, 400:560]
    gold = ((button[:, :, 0] > 5) & (button[:, :, 0] < 30)
            & (button[:, :, 1] > 90) & (button[:, :, 2] > 130))
    enabled = float(gold.mean())
    if enabled < 0.02 and all(max(group) < 0.03 for group in bands):
        return -1
    selected = [i for i, group in enumerate(bands) if sum(v > 0.10 for v in group) >= 3]
    if enabled > 0.06 and len(selected) == 1 and all(
        max(group) < 0.03 for i, group in enumerate(bands) if i != selected[0]
    ):
        return selected[0]
    return None


def _cost(image: np.ndarray, x: int, y: int) -> int | None:
    # 扩大检测范围，避免多位数字被单字 ROI 截成看似有效的一位。
    gray = cv2.cvtColor(image[y + 17:y + 51, x + 16:x + 53], cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 165, 255, cv2.THRESH_BINARY)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    core = labels[7:27, 4:33]
    components = [i for i in range(1, count)
                  if stats[i, cv2.CC_STAT_WIDTH] >= 2 and int((core == i).sum()) >= 8]
    if len(components) != 1:
        return None
    wider = segment_glyphs(image, Rect(x + 16, y + 17, 37, 34), threshold=165)
    if len(wider) != 1 or not 19 <= wider[0].rect.h <= 28 or wider[0].rect.w > 18:
        return None
    glyphs = segment_glyphs(image, Rect(x + 20, y + 19, 29, 30), threshold=165)
    if len(glyphs) != 1 or not 19 <= glyphs[0].rect.h <= 28:
        return None
    scores = sorted((
        (max(float(cv2.matchTemplate(glyphs[0].image, template,
                                    cv2.TM_CCOEFF_NORMED)[0, 0])
             for template in templates), digit)
        for digit, templates in _digit_templates().items()
    ), reverse=True)
    if not scores or scores[0][0] < 0.84:
        return None
    if len(scores) > 1 and scores[0][0] - scores[1][0] < 0.12:
        return None
    # 选项页显示 0 不一定是固定 0 费（例如生热光束）；暂不能据此排序。
    return scores[0][1] if scores[0][1] != 0 else None


def recognize_support_choices(image: np.ndarray) -> list[SupportChoice] | None:
    """识别未选择的三组费用；英雄行或英雄费用不明时由决策层弃权。"""
    if support_selection(image) != -1:
        return None
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    choices = []
    for x in _CARD_X:
        gold_ratios = []
        for y in _CARD_Y:
            strip = hsv[y + 4:y + 55, x:x + 13]
            gold = ((strip[:, :, 0] >= 12) & (strip[:, :, 0] <= 38)
                    & (strip[:, :, 1] > 80) & (strip[:, :, 2] > 130))
            gold_ratios.append(float(gold.mean()))
        heroes = [i for i, ratio in enumerate(gold_ratios) if ratio > 0.45]
        if len(heroes) != 1 or any(
            ratio >= 0.22 for i, ratio in enumerate(gold_ratios) if i != heroes[0]
        ):
            return None
        hero = heroes[0]
        costs = [_cost(image, x, y) for y in _CARD_Y]
        others = tuple(cost for i, cost in enumerate(costs) if i != hero)
        choices.append(SupportChoice(
            SupportGroup(hero_cost=costs[hero], card_costs=others),
            Rect(x + 20, _CARD_Y[hero] + 19, 29, 30),
        ))
    return choices


def support_confirm_button(image: np.ndarray) -> Rect | None:
    """仅在唯一组高亮且选择按钮亮起时，返回确认区域。"""
    if support_selection(image) not in (0, 1, 2):
        return None
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    bounds = (800, 960, 1120, 1045)
    template = _template("support_choose")
    if template is None or _visible_match(gray, "support_choose", bounds) < 0.90:
        return None
    x1, y1, x2, y2 = bounds
    scores = cv2.matchTemplate(gray[y1:y2, x1:x2], template, cv2.TM_CCOEFF_NORMED)
    _, _, _, (x, y) = cv2.minMaxLoc(scores)
    height, width = template.shape
    return Rect(x1 + x, y1 + y, width, height)


def same_support_choices(before: np.ndarray, after: np.ndarray, selected: int) -> bool:
    """核对三组内容和费用，避免遮挡或重抽后错误确认。"""
    if selected not in (0, 1, 2) or before.shape != (1080, 1920, 3):
        return False
    if after.shape != before.shape:
        return False
    for index, x in enumerate(_CARD_X):
        if index == selected:
            continue
        for y in _CARD_Y:
            # 费用与卡牌名称分别核对，不能让大面积未变化背景掩盖费用变化。
            for dx1, dy1, dx2, dy2, limit in (
                (16, 17, 53, 51, 8), (70, 10, 260, 60, 15), (235, 10, 285, 60, 10),
            ):
                a = before[y + dy1:y + dy2, x + dx1:x + dx2]
                b = after[y + dy1:y + dy2, x + dx1:x + dx2]
                if float(cv2.absdiff(a, b).mean()) > limit:
                    return False

    # 选中组会放大并移位：分别用费用徽记和卡名区域匹配每一行。
    # 当前缩放范围来自唯一一组实拍选中前后帧，无法匹配时保守停止。
    a = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY)
    b = cv2.cvtColor(after, cv2.COLOR_BGR2GRAY)
    x = _CARD_X[selected]
    group_x = _GROUP_X_960[selected] * 2
    for row, y in enumerate(_CARD_Y):
        y1, y2 = y - 12 + 9 * row, y + 65 + 9 * row
        regions = (
            (a[y + 19:y + 49, x + 20:x + 49], b[y1:y2, group_x + 3:group_x + 73], 0.84),
            (a[y + 10:y + 50, x + 70:x + 220], b[y1:y2, group_x - 2:group_x + 418], 0.75),
        )
        for template, region, threshold in regions:
            scores = []
            for factor in (1.05, 1.075, 1.1, 1.125, 1.15, 1.175, 1.2):
                scaled = cv2.resize(template, None, fx=factor, fy=factor,
                                    interpolation=cv2.INTER_LINEAR)
                if scaled.shape[0] <= region.shape[0] and scaled.shape[1] <= region.shape[1]:
                    scores.append(float(cv2.matchTemplate(
                        region, scaled, cv2.TM_CCOEFF_NORMED
                    ).max()))
            if not scores or max(scores) < threshold:
                return False
    return True
