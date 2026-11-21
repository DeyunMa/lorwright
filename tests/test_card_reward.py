"""战斗奖励的实机画面、排序和保守识别。"""


import cv2
import pytest

from lorwright.core.champions.base import Preference
from lorwright.core.champions.jinx.policy import pick_card_reward as pick_jinx_card_reward
from lorwright.core.decide.card import CardKind
from lorwright.core.decide.rewards import CardRewardCandidate, RewardCandidate, pick_card_reward
from lorwright.core.perceive.reward_screen import (
    _card_cost,
    _card_kind,
    card_reward_confirm_button,
    card_reward_selection,
    card_reward_target,
    is_card_reward_screen,
    recognize_card_rewards,
    same_card_reward_choices,
)
from tools.test_data import fixtures_root

FIXTURES = fixtures_root() / "card_rewards"


def _image(name):
    image = cv2.imread(str(FIXTURES / name))
    assert image is not None
    return image


def _candidate(name, quality, cost, *, item="其他", cost_certain=True, kind=CardKind.UNIT):
    return CardRewardCandidate(
        RewardCandidate(name, quality, cost), item, cost_certain, kind=kind
    )


def squirrel_reward():
    import numpy as np

    image = np.zeros((1080, 1920, 3), np.uint8)
    image[18:1050, 330:1580] = _image("f1-squirrel-reward-20261118.png")
    return image


def test_unknown_reward_locates_texture_inside_low_detail_art():
    image = squirrel_reward()
    candidates = recognize_card_rewards(image)
    assert [card.card.cost for card in candidates] == [2, 4, 3]
    assert pick_jinx_card_reward(candidates).candidate is candidates[0]
    assert card_reward_target(image, 0, "").center == (555, 363)


@pytest.mark.parametrize("damage", ["black_center", "flat_art", "cost", "title"])
def test_low_detail_reward_preserves_target_visibility_requirements(damage):
    image = squirrel_reward()
    if damage == "black_center":
        image[391:396, 553:558] = 0
    elif damage == "flat_art":
        image[343:433, 515:595] = 100
    elif damage == "cost":
        image[276:309, 428:464] = 0
    else:
        image[18:110, 760:1160] = 0
    assert card_reward_target(image, 0, "") is None


def remaining_first_reward():
    import numpy as np

    # 独立 JPEG 的奖励区 [18:1050, 330:1580]，已亲自查看，无账号信息。
    image = np.zeros((1080, 1920, 3), np.uint8)
    image[18:1050, 330:1580] = _image("f1-remaining-first-reward-20261118.png")
    return image


def test_remaining_first_reward_recognizes_preview_costs_and_target():
    image = remaining_first_reward()
    assert is_card_reward_screen(image)
    assert card_reward_selection(image) == -1
    candidates = recognize_card_rewards(image)
    assert candidates is not None
    assert [c.card.cost for c in candidates] == [3, 6, 4]
    assert [c.card.quality for c in candidates] == ["common", "rare", "rare"]
    assert all(c.preview_cost_verified for c in candidates)
    assert all(c.card.name == "" for c in candidates)
    assert pick_jinx_card_reward(candidates).candidate is candidates[0]
    assert card_reward_target(image, 0, "") is not None


@pytest.mark.parametrize("damage", ["missing", "dimmed", "partial"])
def test_remaining_first_reward_rejects_damaged_six_cost(damage):
    image = remaining_first_reward()
    if damage == "missing":
        image[276:309, 843:879] = 0
    elif damage == "dimmed":
        image[276:309, 843:879] //= 3
    else:
        image[278:291, 848:865] = 0
    assert _card_cost(image, 769) is None
    assert recognize_card_rewards(image) is None
    assert card_reward_target(image, 1, "") is None


def test_remaining_first_reward_six_cost_moves_with_glyph():
    image = remaining_first_reward()
    left, middle = image[276:309, 428:464].copy(), image[276:309, 843:879].copy()
    image[276:309, 428:464], image[276:309, 843:879] = middle, left
    candidates = recognize_card_rewards(image)
    assert candidates is not None
    assert [c.card.cost for c in candidates] == [6, 3, 4]
    assert pick_jinx_card_reward(candidates).candidate is candidates[1]
    assert card_reward_target(image, 1, "") is not None


def landmark_reward():
    import numpy as np

    image = np.zeros((1080, 1920, 3), np.uint8)
    image[18:1050, 330:1580] = _image("f1-landmark-reward-20261117.png")
    return image


def test_landmark_reward_reads_kind_and_quality_without_cataloguing_new_cards():
    image = landmark_reward()
    assert is_card_reward_screen(image)
    assert card_reward_selection(image) == -1
    candidates = recognize_card_rewards(image)
    assert candidates is not None
    assert [c.card.cost for c in candidates] == [3, 2, 3]
    assert [c.card.name for c in candidates] == ["", "", ""]
    assert [c.card.quality for c in candidates] == ["rare", "epic", "common"]
    assert [c.kind for c in candidates] == ["unit", "unit", "landmark"]
    assert all(c.preview_cost_verified for c in candidates)
    assert pick_jinx_card_reward(candidates).candidate == candidates[1]
    assert card_reward_target(image, 1, "") is not None
    assert card_reward_target(image, 2, "") is not None


@pytest.mark.parametrize("damage", ["dimmed", "cut", "recolored", "solid_color"])
def test_epic_badge_requires_color_and_complete_shape(damage):
    image = landmark_reward()
    badge = image[642:661, 950:973]
    if damage == "dimmed":
        badge //= 2
    elif damage == "cut":
        badge[9:] = 0
    elif damage == "recolored":
        hsv = cv2.cvtColor(badge, cv2.COLOR_BGR2HSV)
        hsv[:, :, 0] = 50
        badge[:] = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    else:
        badge[2:17, 3:20] = (230, 30, 230)
    candidates = recognize_card_rewards(image)
    assert candidates is not None
    assert candidates[1].card.quality == "unknown"
    assert candidates[1].kind == "unit"


@pytest.mark.parametrize("region", [
    (351, 228, 384, 255),      # 左侧候选外框
    (360, 300, 365, 780),      # 左侧外框纵边
    (1258, 276, 1294, 309),    # 地标费用
    (1329, 505, 1419, 550),    # 地标类型标签
    (1304, 487, 1484, 514),    # 地标标题
    (1314, 337, 1454, 450),    # 地标插画
])
def test_landmark_reward_rejects_missing_independent_evidence(region):
    image = landmark_reward()
    x1, y1, x2, y2 = region
    image[y1:y2, x1:x2] = 0
    assert recognize_card_rewards(image) is None
    assert card_reward_target(image, 2, "") is None


def narrow_one_reward():
    import numpy as np

    image = np.zeros((1080, 1920, 3), np.uint8)
    image[18:1050, 330:1580] = _image("f1-narrow-one-reward-20261117.png")
    return image


def test_narrow_one_reward_reads_one_cost_spell_but_prefers_epic_unit():
    image = narrow_one_reward()
    assert is_card_reward_screen(image)
    assert card_reward_selection(image) == -1
    assert [_card_cost(image, x) for x in (354, 769, 1184)] == [7, 1, 7]
    candidates = recognize_card_rewards(image)
    assert candidates is not None
    assert [c.card.cost for c in candidates] == [7, 1, 7]
    assert [c.kind for c in candidates] == [CardKind.UNIT, CardKind.SPELL, CardKind.UNIT]
    assert all(c.preview_cost_verified for c in candidates)
    assert pick_jinx_card_reward(candidates).candidate is candidates[0]
    assert card_reward_target(image, 1, candidates[1].card.name) is not None


@pytest.mark.parametrize("damage", ["missing", "dimmed", "partial"])
def test_narrow_one_reward_rejects_missing_or_damaged_cost(damage):
    image = narrow_one_reward()
    if damage == "missing":
        image[276:309, 843:879] = 0
    elif damage == "dimmed":
        image[276:309, 843:879] //= 3
    else:
        image[281:293, 851:862] = 0
    assert _card_cost(image, 769) is None
    assert recognize_card_rewards(image) is None
    assert card_reward_target(image, 1, "") is None


def ten_cost_reward():
    import numpy as np

    image = np.zeros((1080, 1920, 3), np.uint8)
    image[18:1050, 330:1580] = _image("f1-ten-cost-reward-20261121.png")
    return image


def test_ten_cost_reward_reads_two_digit_cost():
    # 会话 20261121T135009：哈洛威 10 费徽章的「1」对原型最高仅 0.757，
    # 但领先第二名 0.379；绝对下限拒掉后整场 card_reward_unknown。
    image = ten_cost_reward()
    assert is_card_reward_screen(image)
    assert [_card_cost(image, x) for x in (354, 769, 1184)] == [4, 10, 3]
    candidates = recognize_card_rewards(image)
    assert candidates is not None
    assert [c.card.cost for c in candidates] == [4, 10, 3]
    assert [c.kind for c in candidates] == [CardKind.SPELL, CardKind.SPELL, CardKind.UNIT]


def test_duplicate_pick_reward_reads_silhouette_spell_kind():
    # 会话 20261121T150717：复制牌奖励变体，右槽裂靈術剪影插画 7.8%
    # 近黑像素超过旧 0.06 遮挡阈值，三槽整体弃权 -> card_reward_unknown。
    import numpy as np

    image = np.zeros((1080, 1920, 3), np.uint8)
    image[18:1050, 330:1580] = _image("f1-duplicate-pick-reward-20261121.png")
    assert is_card_reward_screen(image)
    candidates = recognize_card_rewards(image)
    assert candidates is not None
    assert [c.card.cost for c in candidates] == [1, 6, 3]
    assert [c.kind for c in candidates] == [
        CardKind.UNIT, CardKind.SPELL, CardKind.SPELL]
    assert all(c.preview_cost_verified for c in candidates)


def test_duplicate_pick_champion_reads_occluded_corner_via_gold_edge():
    # 会话 20261121T153142：左槽英雄卡右缘叠挂四个道具六边形，
    # 英雄饰角模板被遮（0.721）；左缘整圈金框无遮挡兜底。
    import numpy as np

    image = np.zeros((1080, 1920, 3), np.uint8)
    image[18:1050, 330:1580] = _image("f1-duplicate-champion-reward-20261121.png")
    assert is_card_reward_screen(image)
    candidates = recognize_card_rewards(image)
    assert candidates is not None
    assert [c.card.cost for c in candidates] == [2, 0, 4]
    assert [c.kind for c in candidates] == [
        CardKind.CHAMPION, CardKind.UNIT, CardKind.SPELL]
    assert [c.card.quality for c in candidates] == ["champion", "common", "rare"]
    # 通用规则品质优先：英雄品质最高，选择左槽（与实机决策一致）。
    assert pick_card_reward(candidates).candidate is candidates[0]


def test_two_star_first_battle_reward_prefers_lower_cost_unit():
    image = _image("f1-two-star-first-reward-20261116.png")
    assert is_card_reward_screen(image)
    candidates = recognize_card_rewards(image)
    assert candidates is not None
    assert [candidate.card.cost for candidate in candidates] == [1, 3, 4]
    assert pick_jinx_card_reward(candidates).candidate is candidates[0]


@pytest.mark.parametrize("region", [(351, 228, 384, 255), (360, 300, 365, 780),
                                    (428, 276, 464, 309), (429, 533, 669, 554)])
def test_two_star_first_reward_rejects_obscured_candidate_evidence(region):
    image = _image("f1-two-star-first-reward-20261116.png")
    x1, y1, x2, y2 = region
    image[y1:y2, x1:x2] = 0
    assert recognize_card_rewards(image) is None


def test_fourth_weekly_reward_keeps_low_cost_choices_actionable():
    image = _image("f1-weekly-fourth-reward-20261116.png")
    assert is_card_reward_screen(image)
    assert card_reward_selection(image) == -1
    candidates = recognize_card_rewards(image)
    assert candidates is not None
    assert [candidate.card.cost for candidate in candidates] == [2, 2, 4]
    pick = pick_jinx_card_reward(candidates)
    assert pick is not None and pick.candidate in candidates[:2]


@pytest.mark.parametrize("damage", ["missing", "dimmed", "wrong_color"])
def test_fourth_reward_requires_visible_gold_title(damage):
    image = _image("f1-weekly-fourth-reward-20261116.png")
    if damage == "missing":
        image[18:110, 760:1160] = 0
    elif damage == "dimmed":
        image[18:110, 760:1160] //= 3
    else:
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        hsv[18:110, 760:1160, 0] = 100
        image = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    assert not is_card_reward_screen(image)
    assert recognize_card_rewards(image) is None


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


def lowered_champion_reward(stopped=False):
    import numpy as np

    # run 20261117T130056-d37f2d134f35 独立 observed JPEG 与原停止 PNG
    # card_reward_unknown_20261117_210115_874640.png 的 [18:1050, 330:1580]
    # 原尺寸安全裁剪，均已查看无账号；JPEG 解码保存不恢复丢失细节，补黑仅用于回放。
    image = np.zeros((1080, 1920, 3), np.uint8)
    suffix = "-stop" if stopped else ""
    image[18:1050, 330:1580] = _image(f"f1-lowered-champion-title{suffix}-20261117.png")
    return image


@pytest.mark.parametrize("stopped", [False, True])
def test_lowered_champion_title_keeps_all_reward_candidates(stopped):
    image = lowered_champion_reward(stopped)
    assert card_reward_selection(image) == -1
    candidates = recognize_card_rewards(image)
    assert candidates is not None
    assert [candidate.card.cost for candidate in candidates] == [4, 3, 3]
    assert candidates[0].card.name == ""


@pytest.mark.parametrize("stopped", [False, True])
def test_lowered_champion_title_keeps_unknown_card_target(stopped):
    image = lowered_champion_reward(stopped)
    target = card_reward_target(image, 0, "")
    assert target is not None
    assert target.center == (555, 393)


@pytest.fixture(params=["old", "observed", "stop"])
def champion_title_case(request):
    if request.param == "old":
        return _image("f1-weekly-second-reward-20261116.png"), 1, 769, (935, 398, 985, 423)
    return lowered_champion_reward(request.param == "stop"), 0, 354, (507, 452, 581, 478)


def test_champion_title_layouts_keep_public_candidates_and_targets(champion_title_case):
    image, index, _, _ = champion_title_case
    candidates = recognize_card_rewards(image)
    assert candidates is not None and candidates[index].card.name == ""
    assert card_reward_target(image, index, "") is not None


@pytest.mark.parametrize("damage", [
    "missing", "white_removed", "top_half", "left_character", "right_character",
    "bright_block", "bright_squares", "art_only",
])
def test_champion_title_requires_centered_complete_text_not_art(champion_title_case, damage):
    image, index, x, (x1, y1, x2, y2) = champion_title_case
    if damage == "missing":
        image[y1:y2, x1:x2] = 40
    elif damage == "white_removed":
        patch = image[y1:y2, x1:x2]
        gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
        patch[gray > 170] = (40, 40, 40)
    elif damage == "top_half":
        image[y1:(y1 + y2) // 2, x1:x2] = 40
    elif damage == "left_character":
        image[y1:y2, x1:x1 + 26] = 40
    elif damage == "right_character":
        image[y1:y2, x2 - 26:x2] = 40
    elif damage == "bright_block":
        image[y1:y2, x1:x2] = 255
    elif damage == "bright_squares":
        image[y1:y2, x1:x2] = 40
        center = x + 191
        for left in (center - 23, center + 2):
            image[y1 + 2:y1 + 23, left:left + 21] = 255
    else:
        # 标题搜索区只留下同一张卡的真实亮插画；亮像素数量不能代替文字。
        image[385:490, x + 75:x + 315] = image[280:385, x + 75:x + 315].copy()
    # 独立插画检查仍有足够证据，不能因为黑色遮挡插画而让文字反例虚假通过。
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    art = gray[337:450, x + 130:x + 270]
    assert float((art < 8).mean()) < 0.05 and float(art.std()) > 10
    assert recognize_card_rewards(image) is None
    assert card_reward_target(image, index, "") is None


def test_weekly_reward_with_champion_and_zero_cost_spell():
    image = _image("f1-weekly-second-reward-20261116.png")
    assert is_card_reward_screen(image)
    assert card_reward_selection(image) == -1
    candidates = recognize_card_rewards(image)
    assert candidates is not None
    assert [candidate.card.cost for candidate in candidates] == [0, 7, 5]
    assert [c.kind for c in candidates] == [CardKind.SPELL, CardKind.CHAMPION, CardKind.SPELL]
    assert all(candidate.preview_cost_verified for candidate in candidates)
    pick = pick_jinx_card_reward(candidates)
    assert pick is not None and pick.candidate is candidates[1]
    assert card_reward_target(image, 0, "") is not None


@pytest.mark.parametrize("region", [
    (276, 309, 428, 464),    # 零费费用
    (276, 309, 843, 879),    # 英雄费用
    (397, 430, 844, 1084),   # 英雄标题
    (337, 450, 899, 1039),   # 英雄插画
    (590, 640, 1234, 1269),  # 青绿色法术框
    (487, 514, 1304, 1484),  # 青绿色法术标题
])
def test_weekly_champion_reward_still_requires_visible_card_data(region):
    image = _image("f1-weekly-second-reward-20261116.png")
    y1, y2, x1, x2 = region
    image[y1:y2, x1:x2] = 0
    assert recognize_card_rewards(image) is None


def test_champion_corner_alone_falls_back_to_gold_left_edge():
    # 饰角被道具遮挡仍可凭左缘金框+居中标题判英雄（实机 20261121T153142）。
    image = _image("f1-weekly-second-reward-20261116.png")
    image[245:295, 1034:1089] = 0
    candidates = recognize_card_rewards(image)
    assert candidates is not None
    assert candidates[1].kind is CardKind.CHAMPION


def test_champion_corner_and_left_edge_together_lose_kind():
    # 饰角与左缘金框同时不可见时英雄证据不足，仍需弃权。
    image = _image("f1-weekly-second-reward-20261116.png")
    image[245:295, 1034:1089] = 0
    image[300:560, 817:831] = 0
    assert recognize_card_rewards(image) is None


def test_elise_gold_champion_reward_reads_candidates_and_picks_champion():
    # 金框英雄卡：框角为金色变体，深色插画自带约 5% 近黑像素。
    image = _image("f1-card-reward-elise-spells-20261121.png")
    assert is_card_reward_screen(image)
    assert card_reward_selection(image) == -1
    candidates = recognize_card_rewards(image)
    assert candidates is not None
    assert [c.card.cost for c in candidates] == [6, 3, 2]
    assert [c.kind for c in candidates] == [
        CardKind.CHAMPION, CardKind.SPELL, CardKind.SPELL]
    assert [c.card.quality for c in candidates] == ["champion", "common", "common"]
    pick = pick_card_reward(candidates)
    assert pick is not None and pick.candidate is candidates[0]
    assert card_reward_target(image, 0, "") is not None


@pytest.mark.parametrize("region", [
    (228, 255, 351, 384),   # 左槽金框角
    (385, 490, 429, 669),   # 左槽英雄标题
])
def test_gold_champion_reward_rejects_missing_independent_evidence(region):
    image = _image("f1-card-reward-elise-spells-20261121.png")
    y1, y2, x1, x2 = region
    image[y1:y2, x1:x2] = 0
    assert recognize_card_rewards(image) is None


def test_ten_cost_reward_reads_two_digit_cost_and_picks_epic():
    # 10 费两位费用：新增「1」原型；左槽框角为暗色风暴背景变体。
    image = _image("f1-card-reward-ten-cost-20261121.png")
    assert is_card_reward_screen(image)
    assert card_reward_selection(image) == -1
    candidates = recognize_card_rewards(image)
    assert candidates is not None
    assert [c.card.cost for c in candidates] == [3, 4, 10]
    assert [c.kind for c in candidates] == [
        CardKind.SPELL, CardKind.UNIT, CardKind.UNIT]
    assert [c.card.quality for c in candidates] == ["rare", "epic", "rare"]
    pick = pick_card_reward(candidates)
    assert pick is not None and pick.candidate is candidates[1]
    assert card_reward_target(image, 1, "") is not None


@pytest.mark.parametrize("region", [
    (228, 255, 351, 384),    # 左槽框角
    (276, 309, 1258, 1294),  # 右槽两位费用
])
def test_ten_cost_reward_rejects_missing_independent_evidence(region):
    image = _image("f1-card-reward-ten-cost-20261121.png")
    y1, y2, x1, x2 = region
    image[y1:y2, x1:x2] = 0
    assert recognize_card_rewards(image) is None


def test_tied_one_cost_reward_prefers_verified_quality():
    # 两侧徽记读不出（quality=unknown）：不再弃权，选已核验的 common。
    image = _image("f1-card-reward-tied-ones-20261121.png")
    assert is_card_reward_screen(image)
    candidates = recognize_card_rewards(image)
    assert candidates is not None
    assert [c.card.cost for c in candidates] == [1, 1, 1]
    assert [c.card.quality for c in candidates] == ["unknown", "common", "unknown"]
    pick = pick_card_reward(candidates)
    assert pick is not None and pick.candidate is candidates[1]
    assert card_reward_target(image, 1, "") is not None


def test_weekly_reward_frame_on_bright_map_fog():
    image = _image("f1-weekly-third-reward-20261116.png")
    assert card_reward_selection(image) == -1
    candidates = recognize_card_rewards(image)
    assert candidates is not None
    assert [c.card.cost for c in candidates] == [5, 2, 5]
    assert pick_jinx_card_reward(candidates).candidate is candidates[1]
    assert card_reward_target(image, 1, "") is not None


@pytest.mark.parametrize("region", [
    (228, 255, 351, 384),
    (300, 780, 360, 365),
    (276, 309, 843, 879),
    (533, 554, 844, 1084),
])
def test_bright_map_reward_still_requires_corner_edges_cost_and_title(region):
    image = _image("f1-weekly-third-reward-20261116.png")
    y1, y2, x1, x2 = region
    image[y1:y2, x1:x2] = 0
    assert recognize_card_rewards(image) is None


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
    # unknown 按最低档参与排序（低于 unranked），不弃权。
    assert pick_card_reward([low, _candidate("未知", "unknown", 0)]).candidate == low
    assert pick_card_reward([cheap, _candidate("费用变动", "rare", 1, cost_certain=False)]) is None
    assert pick_card_reward([low, _candidate("无品质", "unranked", 0)]).candidate == low


def test_jinx_prefers_units_then_lowest_cost_then_quality():
    common = _candidate("便宜优秀", "common", 1)
    rare = _candidate("昂贵稀有", "rare", 4)
    spell = _candidate("史诗法术", "epic", 0, kind=CardKind.SPELL)
    assert pick_jinx_card_reward([common, spell, rare]).candidate is common
    equally_cheap_rare = _candidate("便宜稀有", "rare", 1)
    assert pick_jinx_card_reward([common, spell, equally_cheap_rare]).candidate is equally_cheap_rare


def test_rewards_exclude_landmarks_even_if_they_are_preferred():
    landmark = _candidate("地标", "epic", 0, kind=CardKind.LANDMARK)
    spell = _candidate("法术", "common", 1, kind=CardKind.SPELL)
    unknown = _candidate("卡种不明", "epic", 0, kind=None)
    assert pick_jinx_card_reward([landmark, unknown]) is None
    assert pick_jinx_card_reward([landmark, unknown, spell]).candidate is spell
    assert pick_card_reward([landmark, spell], card_preferences=(Preference(("地标",)),)).candidate is spell
    assert pick_card_reward([landmark]) is None


def test_f1_reward_image_costs_support_jinx_priority():
    image = _image("f1-cost-rule-20261114.png")
    costs = [_card_cost(image, x) for x in (354, 769, 1184)]
    assert costs == [1, 4, 4]
    candidates = [_candidate(str(i), "unknown", cost) for i, cost in enumerate(costs)]
    assert pick_jinx_card_reward(candidates).candidate == candidates[0]
    image[276:309, 843:879] = 0
    assert _card_cost(image, 769) is None


def test_jinx_reward_requires_comparable_costs_and_only_uses_quality_for_ties():
    common = _candidate("普通", "common", 1)
    assert pick_jinx_card_reward([common, _candidate("未知费用", "rare", None)]) is None
    assert pick_jinx_card_reward([common, _candidate("费用变化", "rare", 4,
                                                     cost_certain=False)]) is None
    cheaper_unknown = _candidate("便宜未知品质", "unknown", 0)
    assert pick_jinx_card_reward([cheaper_unknown, common]).candidate is cheaper_unknown
    same_cost_unknown = _candidate("同费未知品质", "unknown", 1)
    assert pick_jinx_card_reward([same_cost_unknown, common]).candidate is common


def test_weekly_real_reward_page_and_unknown_candidates():
    image = _image("f1-weekly-reward-20261116.png")
    assert is_card_reward_screen(image)
    assert card_reward_selection(image) == -1
    assert card_reward_confirm_button(image) is None
    candidates = recognize_card_rewards(image)
    assert candidates is not None
    assert [(c.card.name, c.card.quality, c.card.cost) for c in candidates] == [
        ("", "rare", 5), ("", "unknown", 2), ("", "unknown", 2),
    ]
    assert all(c.item_name == "" and not c.cost_certain and c.preview_cost_verified
               for c in candidates)
    assert pick_jinx_card_reward(candidates).candidate is candidates[0]
    # 通用规则中缺失徽记按最低档排序，已核验 rare 仍胜出。
    assert pick_card_reward(candidates).candidate is candidates[0]
    assert all(card_reward_target(image, i, "") is not None for i in range(3))


@pytest.mark.parametrize("index", range(3))
def test_weekly_candidates_follow_the_unit_in_each_slot(index):
    image = _image("f1-weekly-reward-20261116.png")
    slots = (354, 769, 1184)
    unit = image[255:780, 409:684].copy()
    spell = image[255:780, 824:1099].copy()
    for i, x in enumerate(slots):
        image[255:780, x + 55:x + 330] = unit if i == index else spell
    candidates = recognize_card_rewards(image)
    assert candidates is not None
    assert [c.card.cost for c in candidates] == [5 if i == index else 2 for i in range(3)]
    assert [c.kind for c in candidates] == [CardKind.UNIT if i == index else CardKind.SPELL
                                            for i in range(3)]
    assert pick_jinx_card_reward(candidates).candidate is candidates[index]


@pytest.mark.parametrize("region", [
    (18, 110, 760, 1160), (130, 195, 590, 1330), (960, 1045, 800, 1120),
])
def test_weekly_page_still_requires_all_three_visible_anchors(region):
    image = _image("f1-weekly-reward-20261116.png")
    y1, y2, x1, x2 = region
    image[y1:y2, x1:x2] = 0
    assert not is_card_reward_screen(image)
    assert recognize_card_rewards(image) is None


@pytest.mark.parametrize("region", [
    (276, 309, 428, 464),  # 独立费用字形
    (487, 514, 889, 1069),  # 未知法术名
    (533, 554, 429, 669),  # 未知单位名
    (665, 690, 894, 1084),  # 未知道具名
    (337, 450, 899, 1039),  # 未知插画可见性
    (300, 780, 775, 780),  # 未选中的外框遮挡
])
def test_weekly_obscured_evidence_does_not_produce_candidates(region):
    image = _image("f1-weekly-reward-20261116.png")
    y1, y2, x1, x2 = region
    image[y1:y2, x1:x2] = 0
    assert recognize_card_rewards(image) is None


def test_weekly_dimmed_reward_is_not_actionable():
    image = _image("f1-weekly-reward-20261116.png") // 2
    assert not is_card_reward_screen(image)
    assert recognize_card_rewards(image) is None
    assert card_reward_target(image, 1, "") is None


def test_weekly_unknown_target_requires_visible_click_point_and_card_frame():
    image = _image("f1-weekly-reward-20261116.png")
    target = card_reward_target(image, 1, "")
    assert target is not None
    cx, cy = target.center
    image[cy - 2:cy + 3, cx - 2:cx + 3] = 0
    assert card_reward_target(image, 1, "") is None
    assert card_reward_target(_image("f1-weekly-reward-20261116.png"), 1, "猜测牌名") is None


@pytest.mark.parametrize("change", ["missing", "wrong_color"])
def test_weekly_badge_absence_or_wrong_color_remains_unknown(change):
    image = _image("f1-weekly-reward-20261116.png")
    if change == "missing":
        image[635:668, 520:570] = 0
    else:
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        hsv[635:668, 520:570, 0] = 145
        image = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    candidates = recognize_card_rewards(image)
    assert candidates is not None
    assert all(c.card.quality == "unknown" for c in candidates)


def test_real_choice_identity_survives_selected_card_scaling():
    before, selected = (_image(name) for name in ("before.png", "selected-left.png"))
    assert same_card_reward_choices(before, selected, 0)
    assert not same_card_reward_choices(before, selected, 1)
    assert not same_card_reward_choices(before, before, 0)
    selected[337:425, 899:1019] = 0
    assert not same_card_reward_choices(before, selected, 0)


def test_weekly_synthetic_selection_is_unique_and_keeps_choice_identity():
    # 选中态是合成回放，当前实拍只提供未选图，不能当作该奖励实机选中证据。
    image = _image("f1-weekly-reward-20261116.png")
    selected = image.copy()
    old_selected = _image("selected-left.png")
    selected[968:1030, 810:1110] = old_selected[968:1030, 810:1110]
    selected[300:780, 775:780] = old_selected[300:780, 360:365]
    assert card_reward_selection(selected) == 1
    assert card_reward_confirm_button(selected) is not None
    assert same_card_reward_choices(image, selected, 1)
    assert card_reward_target(selected, 1, "") is None
    selected[300:780, 1190:1195] = old_selected[300:780, 360:365]
    assert card_reward_selection(selected) is None
    assert card_reward_confirm_button(selected) is None
    assert not same_card_reward_choices(image, selected, 1)


def _bonus_reward(name):
    import numpy as np

    image = np.zeros((1080, 1920, 3), np.uint8)
    image[18:1050, 330:1580] = _image(name)
    return image


def test_bonus_reward_with_map_art_corner_recognizes_candidates():
    """20261121T022550 停止帧（附赠 +14生命值）：槽0 外框角下是地图红岩，
    旧四个角模板最高 0.478 < 0.75 致 selection None。"""
    image = _bonus_reward("f1-bonus-hp-20261121.png")
    assert card_reward_selection(image) == -1
    candidates = recognize_card_rewards(image)
    assert [c.card.cost for c in candidates] == [2, 6, 3]
    assert [c.card.quality for c in candidates] == ["common", "epic", "common"]
    assert all(c.kind is CardKind.UNIT for c in candidates)
    assert pick_jinx_card_reward(candidates).candidate is candidates[0]
    # 遮住槽0 外框角后所有角模板都不匹配，仍不能当作未选中。
    masked = image.copy()
    masked[228:255, 351:384] = 0
    assert card_reward_selection(masked) is None


def test_bonus_reward_foil_badge_cost_reads_by_margin():
    """20261120T101930 停止帧（附赠 金幣+100）：槽3 镀层费用徽记的清晰「6」
    只得 0.909 < 0.92；领先第二名 0.35，按领先幅度读出。"""
    image = _bonus_reward("f1-bonus-gold-20261120.png")
    assert card_reward_selection(image) == -1
    candidates = recognize_card_rewards(image)
    assert [c.card.cost for c in candidates] == [3, 5, 6]
    assert [c.kind for c in candidates] == [CardKind.SPELL, CardKind.UNIT, CardKind.SPELL]
    assert pick_jinx_card_reward(candidates).candidate is candidates[1]


def test_weekly_slot3_reward_frame_corner_on_dark_and_statue_art():
    """20261121T040821 停止帧（周常第三槽，附赠 金幣+100）：中、右槽外框角
    叠在深色与石像地图画上，五种角模板最高 0.489/0.518 < 0.75，
    selection 弃权致 recognize 停止。"""
    image = _bonus_reward("f1-weekly-slot3-reward-20261121.png")
    assert card_reward_selection(image) == -1
    candidates = recognize_card_rewards(image)
    assert candidates is not None
    assert [c.card.cost for c in candidates] == [2, 1, 3]
    assert [c.card.quality for c in candidates] == ["common", "rare", "unknown"]
    assert [c.card.name for c in candidates] == ["", "", ""]
    assert all(c.kind is CardKind.UNIT for c in candidates)
    assert all(c.preview_cost_verified for c in candidates)
    pick = pick_jinx_card_reward(candidates)
    assert pick is not None and pick.candidate is candidates[1]
    # 遮住中槽外框角后所有角模板都不匹配，仍不能当作未选中。
    masked = image.copy()
    masked[228:255, 766:799] = 0
    assert card_reward_selection(masked) is None


def test_cost_eight_reward_reads_epic_badge_digit():
    """20261121T031753 停止帧（附赠 +14生命值）：中槽史詩徽记上的清晰「8」
    完整切出，但奖励字库没有 8 原型，最佳分 0.554，整页弃权。"""
    image = _bonus_reward("f1-cost-eight-reward-20261121.png")
    assert card_reward_selection(image) == -1
    candidates = recognize_card_rewards(image)
    assert candidates is not None
    assert [c.card.cost for c in candidates] == [6, 8, 2]
    assert [c.card.quality for c in candidates] == ["common", "epic", "common"]
    assert [c.kind for c in candidates] == [CardKind.SPELL, CardKind.UNIT, CardKind.SPELL]
    assert all(c.card.name == "" for c in candidates)
    assert pick_jinx_card_reward(candidates).candidate is candidates[1]


@pytest.mark.parametrize("damage", ["missing", "dimmed", "partial"])
def test_cost_eight_reward_rejects_damaged_eight(damage):
    image = _bonus_reward("f1-cost-eight-reward-20261121.png")
    if damage == "missing":
        image[276:309, 843:879] = 0
    elif damage == "dimmed":
        image[276:309, 843:879] //= 3
    else:
        image[278:304, 848:866] = 0
    assert _card_cost(image, 769) is None
    assert recognize_card_rewards(image) is None
    assert card_reward_target(image, 1, "") is None


def test_lowered_unit_title_across_keywordless_and_split_glyphs():
    """20261121T043240 停止帧（附赠 金幣+100）：槽3 佐恩小乞丐无关键字行，
    卡名下移至 553-572，固定窗只得 107 < 120；「小」撇捺断成两段，
    逐窗方字核验也串不成链。费用 2/1/1、卡种侍从×3、品质普通×3。"""
    image = _bonus_reward("f1-lowered-title-reward-20261121.png")
    assert card_reward_selection(image) == -1
    candidates = recognize_card_rewards(image)
    assert candidates is not None
    assert [c.card.cost for c in candidates] == [2, 1, 1]
    assert [c.card.quality for c in candidates] == ["common", "common", "common"]
    assert all(c.kind is CardKind.UNIT for c in candidates)
    pick = pick_jinx_card_reward(candidates)
    assert pick is not None and pick.candidate is candidates[1]


@pytest.mark.parametrize("damage", ["title", "rules_keep_title"])
def test_lowered_unit_title_still_requires_centered_square_glyphs(damage):
    image = _bonus_reward("f1-lowered-title-reward-20261121.png")
    if damage == "title":
        # 抹掉下移卡名后，下方小一号规则文字不能顶替。
        image[550:578, 1236:1355] = 0
    else:
        image[583:598, 1236:1355] = 0
        assert recognize_card_rewards(image) is not None
        return
    assert _card_kind(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), 1184) is None
    assert recognize_card_rewards(image) is None
    assert card_reward_target(image, 2, "") is None
