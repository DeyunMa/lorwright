"""每周冒险的纯语义选择；信息不全时不能证明最低难度。"""

import math
from collections.abc import Sequence


def pick_lowest_weekly(stars: Sequence[float | None]) -> int | None:
    """返回最低星级索引；并列按观察顺序，未知或越界则整组弃权。"""
    if not stars or any(
        value is None or not math.isfinite(value) or not 0.5 <= value <= 6.5
        or value * 2 != int(value * 2)
        for value in stars
    ):
        return None
    return min(range(len(stars)), key=lambda index: stars[index])
