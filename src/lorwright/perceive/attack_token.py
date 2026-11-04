"""攻击令牌检测。

有攻击令牌时，动作按钮左侧会冒出一个橙色箭头（带火焰粒子）。实测四种
状态的大橙色连通域面积：有令牌 8446 / 攻击声明中 3603 / 无令牌 30 /
对手施法 5 —— 阈值取 1000，两边都有几十倍余量。

注意：对手攻击时按钮旁也可能出现箭头，但那时按钮是「略過格擋」、状态是
BLOCKING，所以这个判断只在 MY_TURN_IDLE 下用来区分「能攻击」和「只能出牌」。
"""

from __future__ import annotations

import cv2
import numpy as np

from lorwright.models import Rect

__all__ = ["ATTACK_TOKEN_MIN_BLOB", "has_attack_token"]

#: 橙色（HSV，OpenCV 的 H 是 0~179）
_HSV_LOW = np.array([8, 120, 150])
_HSV_HIGH = np.array([28, 255, 255])

#: 最大橙色连通域超过这个面积就认为有令牌
ATTACK_TOKEN_MIN_BLOB = 1000


def has_attack_token(image: np.ndarray, region: Rect) -> bool:
    """`region` 里有没有攻击令牌箭头。"""
    crop = image[region.y : region.y + region.h, region.x : region.x + region.w]
    if crop.size == 0:
        return False
    mask = cv2.inRange(cv2.cvtColor(crop, cv2.COLOR_BGR2HSV), _HSV_LOW, _HSV_HIGH)
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    largest = max((int(stats[i][4]) for i in range(1, count)), default=0)
    return largest >= ATTACK_TOKEN_MIN_BLOB
