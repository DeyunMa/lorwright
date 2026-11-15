"""战斗奖励的实机画面、排序和保守识别。"""

from pathlib import Path

import cv2
import pytest

from lorwright.core.champions.base import Preference
from lorwright.core.champions.jinx.policy import pick_card_reward as pick_jinx_card_reward
from lorwright.core.decide.rewards import CardRewardCandidate, RewardCandidate, pick_card_reward
from lorwright.core.perceive.reward_screen import (
    _card_cost,
    card_reward_confirm_button,
    card_reward_selection,
    card_reward_target,
    is_card_reward_screen,
    recognize_card_rewards,
)

FIXTURES = Path(__file__).parent / "fixtures" / "card_rewards"


def _image(name):
    image = cv2.imread(str(FIXTURES / name))
    assert image is not None
    return image


def _candidate(name, quality, cost, *, item="其他", cost_certain=True):
    return CardRewardCandidate(
        RewardCandidate(name, quality, cost), item, cost_certain
    )


def test_real_reward_candidates_keep_card_quality_separate_from_item():
    image = _image("before.png")
    candidates = recognize_card_rewards(image)
    assert candidates is not None
    assert [(c.card.name, c.card.quality, c.card.cost, c.item_name, c.cost_certain)
            for c in candidates] == [
        ("普羅大砲", "common", 1, "帝王的恩賜", True),
        ("排山倒海", "unranked", 3, "腦蟲", True),
        ("生物編目員", "rare", 1, "光輝板甲", False),
    ]
    # 无英雄偏好时是卡牌品质优先；右卡的道具品质不参与卡牌品质排序。
    pick = pick_card_reward(candidates)
    assert pick is not None and pick.candidate.card.name == "生物編目員"


def test_new_reward_frame_ranks_cards_by_verified_card_quality_and_cost():
    candidates = recognize_card_rewards(_image("f1-reward-20261113.jpg"))
    assert candidates is not None
    assert [(c.card.name, c.card.quality, c.card.cost) for c in candidates] == [
        ("普羅大砲", "common", 1), ("穿針引線", "common", 2),
        ("靈魂黑矛", "common", 3),
    ]
    assert pick_card_reward(candidates).candidate.card.name == "普羅大砲"


def test_real_selected_state_and_confirm_button():
    before, selected, after = (_image(name) for name in ("before.png", "selected-left.png", "after.png"))
    assert card_reward_selection(before) == -1
    assert card_reward_confirm_button(before) is None
    assert card_reward_selection(selected) == 0
    button = card_reward_confirm_button(selected)
    assert button is not None
    assert abs(button.center[0] - 960) < 10 and abs(button.center[1] - 1003) < 10
    assert not is_card_reward_screen(after)


@pytest.mark.parametrize("region", [
    (487, 514, 493, 592),   # 卡名
    (337, 450, 485, 625),   # 卡面及点击区域
    (664, 692, 478, 610),   # 道具名
    (276, 309, 428, 464),   # 显示费用
])
def test_reward_with_obscured_card_data_abstains(region):
    image = _image("before.png")
    y1, y2, x1, x2 = region
    image[y1:y2, x1:x2] = 0
    assert recognize_card_rewards(image) is None


def test_dimmed_or_partially_selected_reward_abstains():
    image = _image("before.png")
    assert not is_card_reward_screen(image // 2)
    selected = _image("selected-left.png")
    # 按钮仍亮但选中框无法核实，不能确认。
    selected[300:780, 360:365] = 0
    assert card_reward_selection(selected) is None
    assert card_reward_confirm_button(selected) is None


def test_click_target_must_not_be_partially_obscured():
    image = _image("before.png")
    assert card_reward_target(image, 0, "普羅大砲").center == (555, 393)
    image[391:396, 553:558] = 0
    assert card_reward_target(image, 0, "普羅大砲") is None


def test_incomplete_catalog_abstains(monkeypatch):
    import lorwright.core.perceive.reward_screen as reward_screen

    monkeypatch.setattr(reward_screen, "_card_catalog", lambda: {"cards": [{}], "items": [{}]})
    assert recognize_card_rewards(_image("before.png")) is None


def test_invalid_catalog_json_abstains(monkeypatch, tmp_path):
    import lorwright.core.perceive.reward_screen as reward_screen

    (tmp_path / "card_rewards.json").write_text("{bad json", encoding="utf-8")
    monkeypatch.setattr(reward_screen, "_ASSETS", tmp_path)
    reward_screen._card_catalog.cache_clear()
    try:
        assert reward_screen._card_catalog() == {}
    finally:
        reward_screen._card_catalog.cache_clear()


def test_reward_hero_preference_precedes_quality_and_cost():
    a = _candidate("法术", "common", 5, item="偏好道具")
    b = _candidate("单位", "rare", 1)
    assert pick_card_reward([a, b], item_preferences=(Preference(("偏好道具",)),)).candidate == a
    assert pick_card_reward([a, b], card_preferences=(Preference(("法术",)),)).candidate == a
    assert pick_card_reward([a, b], card_preferences=(Preference(("单位",)),)).candidate == b
    # 同时命中不同类型偏好，尚无优先关系，不擅自选择。
    assert pick_card_reward(
        [a, b], card_preferences=(Preference(("法术",)),),
        item_preferences=(Preference(("其他",)),),
    ) is None


def test_reward_quality_then_cost_and_unknowns():
    low = _candidate("普通", "common", 1)
    expensive = _candidate("稀有贵", "rare", 5)
    cheap = _candidate("稀有便宜", "rare", 2)
    assert pick_card_reward([low, expensive, cheap]).candidate == cheap
    assert pick_card_reward([low, _candidate("未知", "unknown", 0)]) is None
    assert pick_card_reward([cheap, _candidate("费用变动", "rare", 1, cost_certain=False)]) is None
    assert pick_card_reward([low, _candidate("无品质", "unranked", 0)]).candidate == low


def test_jinx_prefers_lower_cost_then_higher_quality():
    common = _candidate("便宜普通", "common", 1)
    rare = _candidate("昂贵稀有", "rare", 4)
    assert pick_jinx_card_reward([common, rare]).candidate == common
    assert pick_card_reward([common, rare]).candidate == rare
    equally_cheap_rare = _candidate("便宜稀有", "rare", 1)
    assert pick_jinx_card_reward([common, equally_cheap_rare, rare]).candidate == equally_cheap_rare


def test_f1_reward_image_costs_support_jinx_priority():
    image = _image("f1-cost-rule-20261114.png")
    costs = [_card_cost(image, x) for x in (354, 769, 1184)]
    assert costs == [1, 4, 4]
    candidates = [_candidate(str(i), "unknown", cost) for i, cost in enumerate(costs)]
    assert pick_jinx_card_reward(candidates).candidate == candidates[0]
    image[276:309, 843:879] = 0
    assert _card_cost(image, 769) is None


def test_jinx_reward_waits_when_cost_or_required_tiebreak_is_uncertain():
    common = _candidate("普通", "common", 1)
    assert pick_jinx_card_reward([common, _candidate("未知费用", "rare", None)]) is None
    assert pick_jinx_card_reward([common, _candidate("费用变化", "rare", 4,
                                                     cost_certain=False)]) is None
    assert pick_jinx_card_reward([common, _candidate("未知品质", "unknown", 1)]) is None
    # 最低费用唯一时，其他候选品质不影响排序。
    assert pick_jinx_card_reward([common, _candidate("未知品质", "unknown", 4)]).candidate == common
