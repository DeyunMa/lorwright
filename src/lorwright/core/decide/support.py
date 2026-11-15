"""辅助英雄援军的通用费用选择规则。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SupportGroup:
    """一组辅助英雄和另外两种卡牌的有效费用；未知费用用 None。"""

    hero_cost: int | None
    card_costs: tuple[int | None, int | None]


def pick_support_group(groups: list[SupportGroup]) -> int | None:
    """先比英雄费用，同费再比另两种卡的平均费用；全部相同选最左组。

    比较的是页面展示的另两种卡牌费用之和。现有截图中每种各两张，
    此时与按张数加权的平均费用排序一致；其他数量尚未核实。仅在
    参与比较的信息不完整时弃权。
    """
    if not groups or any(g.hero_cost is None or g.hero_cost < 0 for g in groups):
        return None
    cheapest = min(g.hero_cost for g in groups if g.hero_cost is not None)
    tied = [i for i, group in enumerate(groups) if group.hero_cost == cheapest]
    if len(tied) == 1:
        return tied[0]
    if any(
        cost is None or cost < 0
        for index in tied for cost in groups[index].card_costs
    ):
        return None
    return min(tied, key=lambda index: (sum(groups[index].card_costs), index))
