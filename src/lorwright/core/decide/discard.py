"""弃牌选择：优先重复牌，再按费用排序。"""

from lorwright.core.models import Action, ActionType, DiscardCandidates


def choose_discard(candidates: DiscardCandidates) -> Action | None:
    scores = candidates.similarities
    count = len(candidates.cards)
    if not count or len(candidates.costs) != count or len(scores) != count:
        return None
    if any(len(row) != count for row in scores):
        return None
    duplicates = {i for i in range(count) for j in range(count)
                  if i != j and scores[i][j] >= 0.55}
    eligible = sorted(duplicates) if duplicates else list(range(count))
    if any(candidates.costs[i] is None for i in eligible):
        return None
    index = max(eligible, key=lambda i: candidates.costs[i])
    return Action(ActionType.DISCARD_CARD, card_index=index,
                  raw={"duplicate": bool(duplicates), "cost": candidates.costs[index]})
