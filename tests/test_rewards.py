"""奖励决策：偏好 > 品质 > 费用。数据来自英雄包，核心不认识具体英雄。"""

from lorwright.champions import load
from lorwright.decide.rewards import RewardCandidate, pick_reward


def test_preference_beats_quality():
    pack = load("jinx")
    candidates = [
        RewardCandidate(name="傳說聖物", quality="legendary"),
        RewardCandidate(name="闇影圖騰", quality="rare"),
    ]
    pick = pick_reward(candidates, pack.relic_preferences)
    assert pick.candidate.name == "闇影圖騰"
    assert "偏好" in pick.reason


def test_english_alias_matches_too():
    pack = load("elise")
    candidates = [
        RewardCandidate(name="某遺物", quality="epic"),
        RewardCandidate(name="Heavy Hands", quality="rare"),
    ]
    pick = pick_reward(candidates, pack.relic_preferences)
    assert pick.candidate.name == "Heavy Hands"


def test_default_quality_then_cost():
    candidates = [
        RewardCandidate(name="乙", quality="rare", cost=3),
        RewardCandidate(name="甲", quality="epic", cost=5),
        RewardCandidate(name="丙", quality="rare", cost=1),
        RewardCandidate(name="丁", quality="未知品質"),
    ]
    pick = pick_reward(candidates, ())
    assert pick.candidate.name == "甲"


def test_cost_tiebreak_within_quality():
    candidates = [
        RewardCandidate(name="贵的", quality="epic", cost=6),
        RewardCandidate(name="便宜的", quality="epic", cost=2),
    ]
    pick = pick_reward(candidates, ())
    assert pick.candidate.name == "便宜的"


def test_empty_candidates():
    assert pick_reward([], ()) is None


def test_unknown_quality_sorts_last():
    candidates = [
        RewardCandidate(name="谜", quality="???"),
        RewardCandidate(name="普", quality="common"),
    ]
    pick = pick_reward(candidates, ())
    assert pick.candidate.name == "普"
