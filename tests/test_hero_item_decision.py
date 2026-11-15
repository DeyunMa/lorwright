"""英雄道具奖励遵循偏好、品质、随机的独立规则。"""

from random import Random

from lorwright.core.champions.base import Preference
from lorwright.core.decide.rewards import RewardCandidate, pick_hero_item_reward


def test_preference_before_quality():
    choices = [RewardCandidate("preferred", "common"), RewardCandidate("other", "epic")]
    pick = pick_hero_item_reward(choices, (Preference(names=("preferred",), note=""),), Random(1))
    assert pick is not None and pick.candidate == choices[0]


def test_best_quality_tie_is_random():
    choices = [RewardCandidate("a", "rare"), RewardCandidate("b", "rare"),
               RewardCandidate("c", "common")]
    picks = {pick_hero_item_reward(choices, (), Random(seed)).candidate.name for seed in range(20)}
    assert picks == {"a", "b"}


def test_incomplete_candidates_abstain():
    assert pick_hero_item_reward([RewardCandidate("", "rare")], (), Random(1)) is None
    assert pick_hero_item_reward([RewardCandidate("a", "unknown")], (), Random(1)) is None
    assert pick_hero_item_reward([], (), Random(1)) is None
