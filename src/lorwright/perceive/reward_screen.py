"""识别已采集模板覆盖的能力三选一；不完整时弃权。"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

import cv2
import numpy as np

from lorwright.decide.rewards import RewardCandidate
from lorwright.perceive.adventure_scene import _matches, _template

_ASSETS = Path("assets/adventure")
_SLOTS = (472, 815, 1158)
_MIN_SCORE = 0.93


@cache
def _names() -> tuple[tuple[str, str], ...]:
    path = _ASSETS / "power_names.json"
    if not path.exists():
        return ()
    return tuple((entry["template"], entry["name"]) for entry in json.loads(path.read_text()))


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
