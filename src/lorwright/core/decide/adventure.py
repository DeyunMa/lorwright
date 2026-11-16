"""每周冒险的纯语义选择；信息不全时不能证明最低难度。"""

import math
import random
from collections.abc import Sequence

from lorwright.core.decide.rewards import QUALITY_RANK, RewardCandidate
from lorwright.core.models import MapNodeKind


def pick_affordable_power(candidates: Sequence[RewardCandidate], gold: int) -> int | None:
    """占星家只比较可负担能力的品质；同品质优先便宜，不重抽。"""
    if gold < 0 or any(c.cost is None or c.cost < 0 or c.quality not in QUALITY_RANK
                       for c in candidates):
        return None
    affordable = [i for i, candidate in enumerate(candidates) if candidate.cost <= gold]
    return min(affordable, key=lambda i: (-QUALITY_RANK[candidates[i].quality],
                                        candidates[i].cost, i)) if affordable else None


def pick_map_node(kinds: Sequence[MapNodeKind | None], *, rng: random.Random) -> int | None:
    """已知分叉按事件、商店、道具/法术、金币排序，同级随机。"""
    if not kinds:
        return None
    priorities = {MapNodeKind.EVENT: 0, MapNodeKind.SHOP: 1,
                  MapNodeKind.ITEM: 2, MapNodeKind.SPELL: 2, MapNodeKind.GOLD: 3}
    known = [i for i, kind in enumerate(kinds) if kind in priorities]
    if not known:
        # 未知图标不猜类型，保留原先对已核实可达路线的随机选择。
        return rng.choice(range(len(kinds)))
    best = min(priorities[kinds[i]] for i in known)
    return rng.choice([i for i in known if priorities[kinds[i]] == best])


def pick_lowest_weekly(stars: Sequence[float | None], *, rng: random.Random) -> int | None:
    """返回最低星级索引，同星级随机；未知或越界则整组弃权。"""
    if not stars or any(
        value is None or not math.isfinite(value) or not 0.5 <= value <= 6.5
        or value * 2 != int(value * 2)
        for value in stars
    ):
        return None
    lowest = min(stars)
    return rng.choice([i for i, value in enumerate(stars) if value == lowest])
