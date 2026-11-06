"""奖励选择的通用规则（用户 2026-11-05 确认）。

优先级：**英雄包偏好 > 品质优先 > 费用优先**。
英雄偏好来自 `champions/base.py` 的 `Preference` 数据（四类节点各有
偏好表）；UI 自动化等遇到奖励节点再建，本模块先把决策链路定下来，
识别层拿到候选（名字 + 品质 + 费用）就能直接消费。
"""

from __future__ import annotations

from dataclasses import dataclass

from lorwright.champions.base import Preference

__all__ = ["QUALITY_RANK", "RewardCandidate", "pick_reward"]

#: 品质 → 排序权值（越大越好）。繁中键来自游戏本地化文本。
QUALITY_RANK: dict[str, int] = {
    "common": 0,
    "普通": 0,
    "rare": 1,
    "稀有": 1,
    "epic": 2,
    "史詩": 2,
    "legendary": 3,
    "傳說": 3,
}


def _norm(name: str) -> str:
    return name.strip().casefold()


@dataclass(frozen=True)
class RewardCandidate:
    """一个候选奖励（识别层的输出契约）。"""

    name: str
    quality: str
    cost: int | None = None


@dataclass(frozen=True)
class RewardPick:
    """选择结果：选了谁、为什么。"""

    candidate: RewardCandidate
    reason: str


def _preference_hit(candidates: list[RewardCandidate], prefs: tuple[Preference, ...]) -> RewardPick | None:
    for pref in prefs:
        wanted = {_norm(n) for n in pref.names}
        for cand in candidates:
            if _norm(cand.name) in wanted:
                return RewardPick(cand, f"英雄偏好 {pref.names[0]}：{pref.note}")
    return None


def pick_reward(
    candidates: list[RewardCandidate],
    preferences: tuple[Preference, ...] = (),
) -> RewardPick | None:
    """按「偏好 > 品质 > 费用」从候选里选一个。空列表返回 None。"""
    if not candidates:
        return None

    hit = _preference_hit(candidates, preferences)
    if hit is not None:
        return hit

    def sort_key(c: RewardCandidate) -> tuple[int, int, str]:
        rank = QUALITY_RANK.get(c.quality.strip(), -1)  # 未知品质排最后
        cost = c.cost if c.cost is not None else 1_000
        return (-rank, cost, c.name)

    ordered = sorted(candidates, key=sort_key)
    best = ordered[0]
    return RewardPick(best, f"默认规则：品质优先、费用次之（{best.quality}）")
