"""通过多个页面特征识别战斗后的任务与宝库结算页。"""

from __future__ import annotations

import cv2
import numpy as np

from lorwright.core.perceive.adventure_scene import _template


def _visible(image: np.ndarray, name: str, bounds: tuple[int, int, int, int],
             *, text_min: int = 160, score_min: float = 0.83) -> bool:
    template = _template(name)
    if template is None:
        return False
    x1, y1, x2, y2 = bounds
    region = cv2.cvtColor(image[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    if region.shape[0] < template.shape[0] or region.shape[1] < template.shape[1]:
        return False
    scores = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, (x, y) = cv2.minMaxLoc(scores)
    h, w = template.shape
    patch = region[y:y + h, x:x + w]
    bright = template >= text_min
    return bool(score >= score_min and bright.any()
                and float(patch[bright].mean()) >= float(template[bright].mean()) * 0.8)


def is_result_transition(image: np.ndarray) -> bool:
    """双区域核验已采样的结算背景；只授权等待，不证明战斗结束。"""
    if image.shape != (1080, 1920, 3) or image.dtype != np.uint8:
        return False
    return (
        _visible(image, "result_transition_cliff", (640, 110, 860, 230),
                 text_min=60, score_min=0.95)
        and _visible(image, "result_transition_rocks", (1310, 610, 1530, 750),
                     text_min=100, score_min=0.95)
    )


def is_task_reward(image: np.ndarray) -> bool:
    """随机任务完成插页；任务名称、奖励种类和数量均可变化。"""
    if image.shape != (1080, 1920, 3):
        return False
    return (_visible(image, "task_completed_title", (183, 84, 737, 159))
            and _visible(image, "task_completed_icon", (69, 89, 180, 210)))


def is_adventure_victory(image: np.ndarray) -> bool:
    """最终胜利页须同时具有胜利和两项完成时间标签，不依赖英雄、评级或数值。"""
    if image.shape != (1080, 1920, 3):
        return False
    return (
        _visible(image, "adventure_victory_label", (205, 96, 288, 146))
        and _visible(image, "adventure_completion_time", (182, 266, 321, 315), text_min=100)
        and _visible(image, "adventure_best_time", (182, 389, 321, 438), text_min=100)
    )


def is_adventure_rewards(image: np.ndarray) -> bool:
    """胜利后的奖励汇总：胜利文字与英雄经验标签同时可见，不依赖奖励数值。"""
    if image.shape != (1080, 1920, 3):
        return False
    return (_visible(image, "adventure_victory_label", (205, 96, 288, 146))
            and _visible(image, "adventure_hero_xp", (450, 610, 920, 680), text_min=100))


def adventure_settlement(image: np.ndarray) -> str | None:
    """已采样的最终结算阶段；圣物箱本身不证明冒险获胜。"""
    if is_adventure_victory(image):
        return "victory"
    if is_adventure_rewards(image):
        return "rewards"
    if image.shape == (1080, 1920, 3) and (
        _visible(image, "silver_vault_title", (185, 100, 565, 195), score_min=0.94)
        and _visible(image, "silver_relic_icon", (65, 90, 190, 215))
    ):
        return "silver_vault"
    if (image.shape != (1080, 1920, 3)
            or not _visible(image, "silver_relic_title", (185, 100, 565, 195))
            or not _visible(image, "silver_relic_icon", (65, 90, 190, 215))):
        return None
    if (_visible(image, "relic_reward_frame_top", (790, 360, 840, 415), text_min=100)
            and _visible(image, "relic_reward_frame_bottom", (1085, 805, 1135, 855),
                         text_min=60)):
        return "relic_reward"
    if _visible(image, "silver_relic_chest", (850, 510, 1080, 775), text_min=100):
        return "relic_chest"
    return None


def result_screen(image: np.ndarray) -> str | None:
    """识别已采样的结算页；输入应为 1920×1080 设计帧。"""
    if image.shape != (1080, 1920, 3):
        return None
    if (_visible(image, "result_missions_title", (528, 187, 779, 274))
            and _visible(image, "result_missions_xp", (1496, 46, 1683, 126))):
        return "missions"
    if (_visible(image, "result_vault_title", (1158, 20, 1387, 153))
            and _visible(image, "result_vault_xp", (214, 349, 390, 427))):
        return "vault"
    return None
