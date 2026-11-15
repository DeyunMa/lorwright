"""奖励选择的通用规则（用户 2026-11-05 确认）。

优先级：**英雄包偏好 > 品质优先 > 费用优先**。
英雄偏好来自 `champions/base.py` 的 `Preference` 数据（四类节点各有
偏好表）；UI 自动化等遇到奖励节点再建，本模块先把决策链路定下来，
识别层拿到候选（名字 + 品质 + 费用）就能直接消费。
"""

from __future__ import annotations

from dataclasses import dataclass
from random import Random

from lorwright.core.champions.base import Preference

__all__ = [
    "QUALITY_RANK", "CardRewardCandidate", "CardRewardPick", "RewardCandidate",
    "pick_card_reward", "pick_hero_item_reward", "pick_reward",
]

#: 品质 → 排序权值（越大越好）。繁中键来自游戏本地化文本。
QUALITY_RANK: dict[str, int] = {
    # 无品质与未知品质不同：前者是已核实的卡牌枚举，排序时放在普通之下。
    "unranked": -1,
    "common": 0,
    "普通": 0,
    "rare": 1,
    "稀有": 1,
    "epic": 2,
    "史詩": 2,
    "legendary": 3,
    "傳說": 3,
    "champion": 4,
    "英雄": 4,
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


@dataclass(frozen=True)
class CardRewardCandidate:
    """一张奖励卡与附带道具；费用是预览显示值。"""

    card: RewardCandidate
    item_name: str
    cost_certain: bool


@dataclass(frozen=True)
class CardRewardPick:
    candidate: CardRewardCandidate
    reason: str


def pick_card_reward(
    candidates: list[CardRewardCandidate],
    card_preferences: tuple[Preference, ...] = (),
    item_preferences: tuple[Preference, ...] = (),
) -> CardRewardPick | None:
    """英雄偏好优先；否则按卡牌品质、有效费用排序。信息不足则弃权。"""
    if not candidates:
        return None

    def preference_hit(preferences, *, item: bool):
        for pref in preferences:
            names = {_norm(name) for name in pref.names}
            for candidate in candidates:
                name = candidate.item_name if item else candidate.card.name
                if _norm(name) in names:
                    return candidate, pref
        return None

    card_hit = preference_hit(card_preferences, item=False)
    item_hit = preference_hit(item_preferences, item=True)
    # 两张不同的卡同时命中不同类型的偏好时，现有规则没有指定先后。
    if card_hit and item_hit and card_hit[0] != item_hit[0]:
        return None
    hit = card_hit or item_hit
    if hit:
        return CardRewardPick(hit[0], f"英雄偏好 {hit[1].names[0]}：{hit[1].note}")

    if any(c.card.quality not in QUALITY_RANK for c in candidates):
        return None
    highest = max(QUALITY_RANK[c.card.quality] for c in candidates)
    best = [c for c in candidates if QUALITY_RANK[c.card.quality] == highest]
    # 只有最高品质并列时费用才影响选择。附带道具可能改变费用。
    if len(best) > 1 and any(c.card.cost is None or not c.cost_certain for c in best):
        return None
    chosen = min(best, key=lambda c: (c.card.cost if c.card.cost is not None else 1_000,
                                      c.card.name))
    return CardRewardPick(chosen, "默认规则：卡牌品质优先，同品质按费用排序")


def pick_hero_item_reward(
    candidates: list[RewardCandidate],
    preferences: tuple[Preference, ...],
    rng: Random,
) -> RewardPick | None:
    """英雄道具：偏好、品质，同级随机；名称或必要品质未知时弃权。"""
    if not candidates or any(not candidate.name.strip() for candidate in candidates):
        return None
    for preference in preferences:
        names = {_norm(name) for name in preference.names}
        matches = [candidate for candidate in candidates if _norm(candidate.name) in names]
        if matches:
            return RewardPick(rng.choice(matches), f"英雄偏好 {preference.names[0]}")
    if any(candidate.quality.strip() not in QUALITY_RANK for candidate in candidates):
        return None
    highest = max(QUALITY_RANK[candidate.quality.strip()] for candidate in candidates)
    best = [candidate for candidate in candidates if QUALITY_RANK[candidate.quality.strip()] == highest]
    return RewardPick(rng.choice(best), "默认规则：品质优先，同品质随机")


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
