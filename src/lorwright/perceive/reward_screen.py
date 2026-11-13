"""识别已采集模板覆盖的能力三选一；不完整时弃权。"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

import cv2
import numpy as np

from lorwright.decide.rewards import CardRewardCandidate, RewardCandidate
from lorwright.models import Rect
from lorwright.perceive.adventure_scene import _matches, _template
from lorwright.perceive.digits import DigitReader, segment_glyphs

_ASSETS = Path("assets/adventure")
_SLOTS = (472, 815, 1158)
_MIN_SCORE = 0.93


@cache
def _names() -> tuple[tuple[str, str], ...]:
    path = _ASSETS / "power_names.json"
    if not path.exists():
        return ()
    return tuple(
        (entry["template"], entry["name"])
        for entry in json.loads(path.read_text(encoding="utf-8"))
    )


def is_power_screen(image: np.ndarray) -> bool:
    return _matches(image, "power_title", (880, 25, 1036, 102), 0.93)


def _best(region: np.ndarray, choices: tuple[tuple[str, str], ...]) -> str | None:
    scores = []
    for template_name, value in choices:
        template = _template(template_name)
        if template is None or template.shape[0] > region.shape[0] or template.shape[1] > region.shape[1]:
            continue
        score = float(cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED).max())
        scores.append((score, value))
    scores.sort(reverse=True)
    if not scores or scores[0][0] < _MIN_SCORE:
        return None
    if len(scores) > 1 and scores[0][0] - scores[1][0] < 0.05:
        return None
    return scores[0][1]


def recognize_powers(image: np.ndarray) -> list[RewardCandidate] | None:
    """返回左到右的候选；任一名称或品质未识别就返回 None。"""
    if not is_power_screen(image):
        return None
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    result = []
    for x in _SLOTS:
        name = _best(gray[540:583, x:x + 290], _names())
        quality = _best(gray[584:610, x:x + 290], (
            ("rarity_rare", "rare"), ("rarity_common", "common"),
        ))
        if name is None or quality is None:
            return None
        result.append(RewardCandidate(name=name, quality=quality))
    return result


_CARD_SLOTS = (354, 769, 1184)


@cache
def _card_catalog() -> dict:
    path = _ASSETS / "card_rewards.json"
    try:
        catalog = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return catalog if _valid_card_catalog(catalog) else {}


def _valid_card_catalog(catalog: object) -> bool:
    if not isinstance(catalog, dict):
        return False
    cards, items = catalog.get("cards"), catalog.get("items")
    if not isinstance(cards, list) or not cards or not isinstance(items, list) or not items:
        return False
    for entries, fields in ((cards, ("name", "template", "art", "quality")),
                            (items, ("name", "template"))):
        if any(not isinstance(entry, dict) or any(
            not isinstance(entry.get(field), str) or not entry[field].strip() for field in fields
        ) for entry in entries):
            return False
        if len({entry["name"] for entry in entries}) != len(entries):
            return False
    return all(isinstance(item.get("cost_certain"), bool) for item in items)


@cache
def _reward_digits() -> DigitReader:
    reader = DigitReader(_ASSETS / "reward_digits", min_score=0.92)
    reader.load()
    return reader


def _visible_match(gray: np.ndarray, template_name: str, rect: tuple[int, int, int, int]) -> float:
    """匹配图案并拒绝明显变暗的遮罩画面。"""
    template = _template(template_name)
    if template is None:
        return -1.0
    x1, y1, x2, y2 = rect
    region = gray[y1:y2, x1:x2]
    h, w = template.shape
    if region.shape[0] < h or region.shape[1] < w:
        return -1.0
    scores = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, (x, y) = cv2.minMaxLoc(scores)
    matched = region[y:y + h, x:x + w]
    if float(matched.mean()) < float(template.mean()) * 0.78:
        return -1.0
    bright = template >= 180
    if bright.any() and float(matched[bright].mean()) < float(template[bright].mean()) * 0.78:
        return -1.0
    return float(score)


def is_card_reward_screen(image: np.ndarray) -> bool:
    """战斗卡牌奖励：标题、副标题和选择按钮必须同时可见。"""
    if image.shape != (1080, 1920, 3):
        return False
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return (
        _visible_match(gray, "card_reward_title", (760, 18, 1160, 110)) >= 0.93
        and _visible_match(gray, "card_reward_subtitle", (590, 130, 1330, 195)) >= 0.93
        and _visible_match(gray, "card_reward_choose", (800, 960, 1120, 1045)) >= 0.93
    )


def card_reward_selection(image: np.ndarray) -> int | None:
    """返回选中的 0–2 号槽，-1 为未选中，None 为状态不明。"""
    if not is_card_reward_screen(image):
        return None
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    ratios = []
    for x in _CARD_SLOTS:
        edge = hsv[300:780, x + 6:x + 11]
        ratios.append(float(((edge[:, :, 2] > 180) & (edge[:, :, 1] < 160)).mean()))
    button = hsv[968:1030, 810:1110]
    gold = ((button[:, :, 0] > 5) & (button[:, :, 0] < 30)
            & (button[:, :, 1] > 90) & (button[:, :, 2] > 130))
    enabled = float(gold.mean())
    if max(ratios) < 0.15 and enabled < 0.02:
        return -1
    selected = [i for i, ratio in enumerate(ratios) if ratio > 0.5]
    if enabled > 0.08 and len(selected) == 1 and all(
        ratio < 0.15 for i, ratio in enumerate(ratios) if i != selected[0]
    ):
        return selected[0]
    return None


def card_reward_target(image: np.ndarray, index: int, name: str) -> Rect | None:
    """定位卡面并核对点击中心未被遮挡，返回设计尺寸坐标。"""
    if index not in range(len(_CARD_SLOTS)) or card_reward_selection(image) != -1:
        return None
    catalog = _card_catalog()
    if not _valid_card_catalog(catalog):
        return None
    card = next((entry for entry in catalog["cards"] if entry["name"] == name), None)
    if card is None:
        return None
    template = _template(card["art"])
    if template is None:
        return None
    x = _CARD_SLOTS[index]
    rect = (x + 55, 300, x + 325, 465)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if _visible_match(gray, card["art"], rect) < 0.93:
        return None
    x1, y1, x2, y2 = rect
    scores = cv2.matchTemplate(gray[y1:y2, x1:x2], template, cv2.TM_CCOEFF_NORMED)
    _, _, _, (dx, dy) = cv2.minMaxLoc(scores)
    h, w = template.shape
    cx, cy = w // 2, h // 2
    actual = gray[y1 + dy + cy - 10:y1 + dy + cy + 10,
                  x1 + dx + cx - 10:x1 + dx + cx + 10]
    reference = template[cy - 10:cy + 10, cx - 10:cx + 10]
    if actual.shape != (20, 20) or float((cv2.absdiff(actual, reference) > 40).mean()) > 0.05:
        return None
    return Rect(x1 + dx, y1 + dy, w, h)


def card_reward_confirm_button(image: np.ndarray) -> Rect | None:
    """仅在有唯一已选候选且按钮启用时返回按钮文字位置。"""
    if card_reward_selection(image) not in (0, 1, 2):
        return None
    template = _template("card_reward_choose")
    if template is None:
        return None
    region = cv2.cvtColor(image[960:1045, 800:1120], cv2.COLOR_BGR2GRAY)
    scores = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, (x, y) = cv2.minMaxLoc(scores)
    if score < 0.93:
        return None
    h, w = template.shape
    return Rect(800 + x, 960 + y, w, h)


def _card_entry(gray: np.ndarray, entries: list[dict], rect: tuple[int, int, int, int]) -> dict | None:
    scores = sorted(
        ((_visible_match(gray, entry["template"], rect), i) for i, entry in enumerate(entries)),
        reverse=True,
    )
    if not scores or scores[0][0] < 0.93:
        return None
    if len(scores) > 1 and scores[0][0] - scores[1][0] < 0.05:
        return None
    return entries[scores[0][1]]


def _card_cost(image: np.ndarray, x: int) -> int | None:
    glyphs = segment_glyphs(image, Rect(x + 74, 276, 36, 33), threshold=180)
    if len(glyphs) != 1 or not 20 <= glyphs[0].rect.h <= 30:
        return None
    hit = _reward_digits().classify(glyphs[0].image)
    return hit[0] if hit else None


def recognize_card_rewards(image: np.ndarray) -> list[CardRewardCandidate] | None:
    """识别未选中的三张奖励卡；任何卡、道具或费用不明时弃权。"""
    if card_reward_selection(image) != -1:
        return None
    catalog = _card_catalog()
    if not _valid_card_catalog(catalog):
        return None
    cards, items = catalog.get("cards", []), catalog.get("items", [])
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    result = []
    for x in _CARD_SLOTS:
        card = _card_entry(gray, cards, (x + 45, 470, x + 330, 575))
        item = _card_entry(gray, items, (x + 100, 655, x + 300, 700))
        cost = _card_cost(image, x)
        if card is None or item is None or cost is None:
            return None
        if _visible_match(gray, card["art"], (x + 55, 300, x + 325, 465)) < 0.93:
            return None
        result.append(CardRewardCandidate(
            card=RewardCandidate(name=card["name"], quality=card["quality"], cost=cost),
            item_name=item["name"], cost_certain=item["cost_certain"],
        ))
    return result
