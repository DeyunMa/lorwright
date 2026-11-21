"""TARGETING 内的法术变体选项：两张悬浮法术卡的二选一提示。

实机 20261121T140928：打出哈洛威后游戏开「希格斯 彈跳炸彈」变体
选择（左：单体 2 伤；右：双敌各 1 伤），ui_state 仍为 TARGETING，
但 targeted_spell/action_prompt/replace_prompt 全为空，提示无
法路由 → unknown_target。选项卡的唯一结构证据是固定槽位上的
费用徽章；卡名与文本不登记，点击中心即选。
"""

import cv2
import numpy as np

from lorwright.core.models import Rect

#: 两个选项槽位的费用徽章检查区（实机标定，1920×1080）。
_BADGE_REGIONS = ((660, 330, 100, 80), (980, 330, 100, 80))

#: 对应选项卡的整卡点击区域：徽章在卡面左上角偏内。
_OPTION_RECTS = (
    Rect(645, 240, 280, 320),
    Rect(965, 240, 280, 320),
)

#: 蓝紫色费用徽章的色域；区域内徽章实测约 420 px（≈5% 占比）。
_BADGE_MIN_FRACTION = 0.04


def spell_options(image: np.ndarray) -> tuple[Rect, ...]:
    """识别 TARGETING 内的法术变体选项，按左到右返回整卡区域。

    只在固定槽位检费用徽章，不识别卡名或效果；两处都有徽章才算
    变体提示（单张悬浮卡是普通选目标法术，归 targeted_spell）。
    """
    if image.shape[:2] != (1080, 1920):
        return ()
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    found = []
    for (x, y, w, h), rect in zip(_BADGE_REGIONS, _OPTION_RECTS, strict=True):
        patch = hsv[y:y + h, x:x + w]
        badge = cv2.inRange(patch, (95, 80, 120), (140, 255, 255))
        if float(badge.mean() / 255.0) < _BADGE_MIN_FRACTION:
            return ()
        found.append(rect)
    return tuple(found)
