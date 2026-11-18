"""感知层回归：用真实截图验证解析结果。

fixtures 分两代：
- `1080p_*.png`：当前目标分辨率（Pie64 + `wm size 1920x1080`），跟 config 一致
- `720p_*.png`：模拟器原生分辨率时代的旧图，只用来做字形泛化回归，
  跑它们必须配 `LEGACY_720P` 坐标（下面写死），不能用当前 config

换分辨率时：重采 fixtures + 重标 config/settings.yaml，这个文件跟着改。
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from lorwright.core.config import load_settings
from lorwright.core.models import Layout, Rect, UIState
from lorwright.core.perceive.digits import DigitReader
from lorwright.core.perceive.state import StateParser
from lorwright.core.perceive.ui_state import UIStateDetector
from tools.test_data import fixtures_root

SCREENS = fixtures_root() / "screens"

#: 1280×720 时代的标定值。只服务于 `720p_*.png` 这批旧 fixture。
LEGACY_720P = Layout(
    end_turn=Rect(1120, 315, 88, 88),
    enemy_nexus=Rect(60, 230, 95, 90),
    play_area=Rect(520, 330, 240, 160),
    hand_region=Rect(940, 580, 340, 140),
    enemy_hp=Rect(145, 262, 45, 23),
    my_hp=Rect(147, 433, 45, 23),
    mana=Rect(1112, 259, 22, 24),
)


def _parser(layout: Layout | None = None) -> StateParser:
    settings = load_settings()
    layout = layout or settings.layout.to_layout()
    parser = StateParser(
        layout=layout,
        ui=UIStateDetector(
            threshold=settings.perception.match_threshold,
            action_button=layout.end_turn,
        ),
        digits=DigitReader(),
        threshold=settings.perception.match_threshold,
    )
    parser.load()
    return parser


def _load(name: str):
    img = cv2.imread(str(SCREENS / name))
    assert img is not None, f"缺截图 {name}"
    return img


def test_real_pass_successor_exposes_new_opponent_unit_for_routing():
    from dataclasses import replace

    from lorwright.core.loop.outcome import ActionOutcome, OutcomeStatus
    from lorwright.core.models import Action, ActionType, Reading

    after = _parser().parse(_load("f1-pass-new-opponent-20261116.png"))
    assert after.ui_state is UIState.MY_TURN_IDLE
    assert after.mana == 4 and after.has_fresh_readings("mana")
    assert after.enemy_nexus_hp == 2
    assert len(after.enemy_units) == 1
    # 前态按运行日志合成；未保留该次输入前的原始截图。
    before = replace(after, enemy_units=[], readings={
        **after.readings, "enemy_units_visible": Reading(),
    })
    outcome = ActionOutcome(Action(ActionType.END_TURN), before, 8).observe(after, 1)
    assert outcome.status is OutcomeStatus.NEEDS_INPUT
    assert outcome.reason == "opponent_unit_appeared"


def test_optional_choice_is_not_an_idle_turn():
    state = _parser().parse(_load("f1-optional-choice-20261116.png"))
    assert state.ui_state.value == "optional_choice"


class _BlockingUI:
    def load(self) -> None:
        pass

    def detect(self, image) -> UIState:
        return UIState.BLOCKING


def test_blocking_reads_enemy_attackers_from_enemy_combat() -> None:
    """BLOCKING 时只把攻击行里的敌人放进 enemy_attackers。"""
    image = np.zeros((1080, 1920, 3), np.uint8)
    cv2.rectangle(image, (600, 320), (662, 364), (0, 165, 255), -1)
    parser = StateParser(
        layout=Layout(enemy_combat=Rect(520, 300, 900, 180)),
        ui=_BlockingUI(),
        digits=DigitReader(),
    )
    state = parser.parse(image)
    assert state.ui_state is UIState.BLOCKING
    assert len(state.enemy_attackers) == 1
    assert state.enemy_attackers[0].rect.center == (631, 342)


def test_state_parser_reads_unit_attack_values() -> None:
    state = _parser().parse(_load("1080p_units_idle.png"))
    assert [unit.attack for unit in state.my_units] == [4, 6]
    assert [unit.attack for unit in state.enemy_units] == [8, 2]
    assert state.readings["my_units_visible"].value == 2
    assert state.readings["enemy_units_visible"].value == 2
    assert state.has_fresh_readings("my_units_visible", "enemy_units_visible")


def test_unit_observations_do_not_turn_zero_detections_into_confirmed_empty():
    parser = _parser()
    image = _load("1080p_units_idle.png")
    assert parser.parse(image).has_fresh_readings("my_units_visible", "enemy_units_visible")
    # 保留完整 UI，只覆盖单位区域；空白画布也不能证明游戏中的真实空场。
    for region in (parser.layout.my_board, parser.layout.my_combat,
                   parser.layout.enemy_board, parser.layout.enemy_combat):
        if region is not None:
            image[region.y:region.y + region.h, region.x:region.x + region.w] = 0
    state = parser.parse(image)
    assert state.my_units == state.enemy_units == []
    for name in ("my_units_visible", "enemy_units_visible"):
        assert state.readings[name].value is None
        assert not state.readings[name].fresh


def test_white_mana_ignores_orange_attack_token_effect() -> None:
    from lorwright.core.loop.outcome import ActionOutcome, OutcomeStatus
    from lorwright.core.models import Action, ActionType, GameState, Reading

    image = _load("f1-weekly-mana-token-20261116.png")
    parser = _parser()
    parser._mana = 1
    parser._readings["mana"] = Reading(1, 0)
    before = GameState(ui_state=UIState.MY_TURN_IDLE, mana=1,
                       readings={"mana": Reading(1, 0)})
    after = parser.parse(image)
    assert after.mana == 4 and after.has_fresh_readings("mana")
    outcome = ActionOutcome(Action(ActionType.END_TURN), before, 20)
    assert outcome.observe(after, 4).status is OutcomeStatus.SUCCEEDED
    roi = parser.layout.mana
    image[roi.y:roi.y + roi.h, roi.x:roi.x + roi.w] = (0, 165, 255)
    obscured = parser.parse(image)
    assert not obscured.has_fresh_readings("mana")
    assert outcome.observe(obscured, 4).status is OutcomeStatus.WAITING


def test_confirmation_to_stack_commit_is_visible_progress() -> None:
    from lorwright.core.loop.outcome import ActionOutcome, OutcomeStatus
    from lorwright.core.models import Action, ActionType

    parser = _parser()
    before = parser.parse(_load("1080p_confirm_phase.png"))
    after = parser.parse(_load("f1-weekly-combat-stack-20261116.png"))
    assert before.ui_state is after.ui_state is UIState.COMBAT_RESOLVING
    # 两张实拍不是同一段录像；隔离按钮阶段变化，排除法力与单位变化。
    from dataclasses import replace
    after = replace(after, mana=before.mana, readings=before.readings,
                    my_units=before.my_units, has_attack_token=before.has_attack_token)
    outcome = ActionOutcome(Action(ActionType.CONFIRM), before, 8).observe(after, 1)
    assert (before.action_prompt, after.action_prompt) == ("action_confirm", "action_commit")
    assert outcome.status is OutcomeStatus.NEEDS_INPUT
    assert outcome.reason == "confirmation_prompt_changed"


def test_confirmation_prompt_is_not_carried_across_obscured_frames() -> None:
    parser = _parser()
    image = _load("f1-weekly-combat-stack-20261116.png")
    assert parser.parse(image).action_prompt == "action_commit"
    image[460:625, 1640:1840] = 0
    assert parser.parse(image).action_prompt is None


def test_assets_exist() -> None:
    """模板和字形库必须在仓库里，否则真机上会静默失效。"""
    assert (Path("assets/buttons") / "mulligan.png").exists()
    reader = DigitReader()
    reader.load()
    assert reader.digits >= set(range(0, 10)), f"缺字形：{reader.digits}"


def test_mulligan_is_not_my_turn() -> None:
    """起手换牌的「確定」和动作按钮同位置同颜色，必须先判掉。"""
    state = _parser().parse(_load("1080p_mulligan.png"))
    assert state.ui_state is UIState.MULLIGAN


def test_battle_turn2() -> None:
    """右侧有两个法力指示器：上排是对手，下排是我们。

    这张截图是对手 2 费、我方 3 费（第 3 回合）。早先的 layout 指到上排，
    读到 2 却「看起来对」，实战里会让 bot 以为没费而整局空过。
    """
    state = _parser().parse(_load("1080p_battle_turn2.png"))
    assert state.ui_state is UIState.MY_TURN_IDLE
    assert state.mana == 3
    assert state.nexus_hp == 50
    assert state.enemy_nexus_hp == 30


def test_ten_mana_is_fresh_in_real_battle() -> None:
    state = _parser().parse(_load("f1-karma-ten-mana-20261114.png"))
    assert state.ui_state is UIState.MY_TURN_IDLE
    assert state.mana == 10
    assert state.readings["mana"].fresh


@pytest.mark.parametrize(("name", "expected"), [
    ("1080p_jinx_mulligan_20261114.png", 1),
    ("1080p_confirm_phase.png", 2),
    ("1080p_battle_turn2.png", 3),
    ("1080p_hand_fan.png", 4),
    ("1080p_targeting.png", 6),
    ("f1-karma-seven-mana-20261114.png", 7),
    ("f1-karma-eight-mana-20261114.png", 8),
])
def test_mana_region_keeps_single_digit_readings(name, expected) -> None:
    parser = _parser()
    assert parser.digits.read(_load(name), parser.layout.mana) == expected


@pytest.mark.parametrize(("name", "side", "expected"), [
    ("f1-karma-ten-mana-20261114.png", "enemy_nexus_hp", 25),
    ("f1-karma-seven-mana-20261114.png", "enemy_nexus_hp", 17),
    ("f1-karma-eight-mana-20261114.png", "enemy_nexus_hp", 18),
    ("1080p_mulligan.png", "nexus_hp", 50),
])
def test_high_resolution_nexus_health(name, side, expected) -> None:
    state = _parser().parse(_load(name))
    assert getattr(state, side) == expected
    assert state.readings[side].fresh


@pytest.mark.parametrize("shade", (0, 80, 160))
def test_partially_obscured_ten_mana_is_not_fresh(shade) -> None:
    image = _load("f1-karma-ten-mana-20261114.png")
    image[650:689, 1695:1712] = shade
    state = _parser().parse(image)
    assert not state.readings["mana"].fresh


def test_collapsed_hand_reads_costs_from_live_frame() -> None:
    """实战截图里的 6 张手牌费用必须全读对。

    这条盯的是「徽章抠图」：数字是白字、徽章底是蓝色、外环是青色。
    用灰度或 max 通道会在 1080p 把青环并进数字，6 张里错 4 张；
    改判据为 min(R,G,B)（三通道都亮才算白）后全对。
    """
    state = _parser().parse(_load("1080p_hand_fan.png"))
    assert state.hand_expanded is False
    assert [c.cost for c in state.hand] == [3, 2, 5, 2, 6, 3]


def test_expanded_hand_is_detected_as_expanded() -> None:
    """展开态卡片大、位置明确、能拖；收起态只露左边缘、拖不动。

    两套徽章模板（48px / 56px）互不匹配，所以「哪套认出来」就等于「哪个状态」。
    """
    state = _parser().parse(_load("1080p_hand_expanded.png"))
    assert state.hand_expanded is True
    assert len(state.hand) == 6
    # 展开态徽章 56px、字形比收起态粗，且 0 费卡的数字是**绿色**的。
    # `_tilt` 语义错（返回主轴角 86° 而不是倾角 -3.7°）时只能读出 1/6。
    assert [c.cost for c in state.hand] == [1, 4, 3, 3, 2, 0]


def test_block_phase_recognizes_elusive_attackers_and_skips_illegal_blocks() -> None:
    from dataclasses import replace

    from lorwright.core.decide.generic import BlockingPolicy, plan_blocks
    from lorwright.core.models import ActionType

    state = _parser().parse(_load("1080p_block_phase.png"))
    # 「略過格擋」和回合按钮同为蓝色，此时不能出牌。
    assert state.ui_state is UIState.BLOCKING
    assert len(state.enemy_attackers) == 6
    assert all("Elusive" in unit.keywords for unit in state.enemy_attackers)
    assert all("Overwhelm" in unit.keywords for unit in state.enemy_attackers)
    assert len(state.my_units) == 3
    assert all("Elusive" not in unit.keywords for unit in state.my_units)
    assert plan_blocks(state.my_units, state.enemy_attackers) == []
    assert BlockingPolicy().decide(state).type is ActionType.CONFIRM
    # 锐目仅在规则层注入：现有截图没有锐目正例，尚不能验证视觉识别。
    sharpsight = replace(state.my_units[0], keywords=frozenset({"BlockElusive"}))
    assert plan_blocks([sharpsight], state.enemy_attackers)


def test_overwhelm_icon_in_other_frame_and_ordinary_units() -> None:
    positive = _parser().parse(_load("1080p_commit_phase.png"))
    # 原四个定位保留，补回 9/11；5/7 仍缺失，不能把生命 7 当成第六个单位。
    assert len(positive.enemy_units) == 5
    assert [unit.rect.center[0] for unit in positive.enemy_units] == [517, 688, 1005, 1210, 1350]
    assert all("Overwhelm" in unit.keywords for unit in positive.enemy_units)
    negative = _parser().parse(_load("1080p_units_combat.png"))
    assert all("Overwhelm" not in unit.keywords for unit in negative.enemy_units)


def test_commit_phase_is_not_my_turn() -> None:
    """「結算」= 提交格挡/攻击声明，同样不能出牌。"""
    state = _parser().parse(_load("1080p_commit_phase.png"))
    assert state.ui_state is UIState.COMBAT_RESOLVING


def test_confirm_phase_is_not_my_turn() -> None:
    """2026-11-07 实机：结算按钮文案是「確認」（旧图是「結算」）。"""
    state = _parser().parse(_load("1080p_confirm_phase.png"))
    assert state.ui_state is UIState.COMBAT_RESOLVING


def test_staged_jinx_spell_has_a_confirmation_button() -> None:
    state = _parser().parse(_load("1080p_jinx_spell_confirm_20261113.jpg"))
    assert state.ui_state is UIState.COMBAT_RESOLVING


def test_main_menu_is_not_a_battle() -> None:
    state = _parser(LEGACY_720P).parse(_load("720p_main_menu.png"))
    assert state.ui_state is UIState.UNKNOWN


def test_full_bleed_blue_background_is_not_mistaken_for_my_turn_idle() -> None:
    """整屏蓝色过渡画面（如英雄之路星球入场）覆盖按钮区时，不能误判为我方行动回合。"""
    detector = UIStateDetector(action_button=Rect(1680, 470, 132, 132))
    detector.load()
    blue_planet = np.zeros((1080, 1920, 3), dtype=np.uint8)
    # 下半屏高饱和亮蓝模拟星球地平线覆盖按钮及下方区域（BGR 对应 HSV H≈105, S=220, V=220）
    blue_planet[440:, :] = (220, 145, 30)
    assert detector.detect(blue_planet) is UIState.UNKNOWN

    # 独立圆形蓝色按钮（上下边界外无大块同色背景）仍识别为 MY_TURN_IDLE
    isolated_button = np.zeros((1080, 1920, 3), dtype=np.uint8)
    cv2.circle(isolated_button, (1746, 536), 64, (220, 145, 30), -1)
    assert detector.detect(isolated_button) is UIState.MY_TURN_IDLE


@pytest.mark.parametrize(
    ("name", "rect", "expected"),
    [
        ("1080p_battle_turn2.png", Rect(215, 390, 56, 40), 30),
        ("1080p_battle_turn2.png", Rect(216, 646, 56, 40), 50),
        ("1080p_battle_turn2.png", Rect(1650, 640, 50, 45), 3),   # 我方法力（下排）
        ("720p_battle_turn2.png", Rect(145, 262, 45, 23), 30),
        ("720p_battle_turn2.png", Rect(147, 433, 45, 23), 50),
        ("720p_battle_turn2.png", Rect(1112, 259, 22, 24), 2),
        ("720p_battle_turn2.png", Rect(1112, 434, 22, 25), 3),
        ("720p_battle_turn2.png", Rect(1145, 232, 16, 20), 0),
        ("720p_mulligan.png", Rect(666, 234, 16, 22), 6),
        ("720p_mulligan.png", Rect(876, 233, 17, 21), 4),
        ("720p_mulligan.png", Rect(247, 232, 12, 22), 1),
    ],
)
def test_read_numbers(name: str, rect: Rect, expected: int) -> None:
    reader = DigitReader()
    reader.load()
    assert reader.read(_load(name), rect) == expected


def test_small_glyph_generalizes() -> None:
    """同一数字存了多个原型后，小字号也能认对。"""
    reader = DigitReader()
    reader.load()
    # 地图血条上的 6 只有 14px，靠起手卡费（18px）那个原型认出来
    assert reader.read(_load("720p_map.png"), Rect(375, 670, 16, 20)) == 6
    # 1080p 的 7 也能识别主菜单金币中的小字号。
    assert reader.read(_load("720p_main_menu.png"), Rect(395, 18, 85, 28)) == 155753


def test_targeting_button_is_detected() -> None:
    """「選擇目標」按钮是深色半透明的（蓝色占比 <0.45），只能靠文字认出来。

    实机栽过：文字判断被套在「蓝色占比 ≥0.45」里面，这个按钮永远进不去，
    整个状态落到 UNKNOWN，策略按「状态不明不点击」空转到引擎停。
    """
    from lorwright.core.perceive.ui_state import UIStateDetector

    detector = UIStateDetector(action_button=Rect(1680, 470, 132, 132))
    detector.load()
    frame = cv2.imread(str(fixtures_root() / "screens/1080p_targeting.png"))
    assert frame is not None
    assert detector.detect(frame) is UIState.TARGETING


def test_scholar_mana_rejects_partial_glyph_without_overwriting_last_reading():
    crop = _load("f1-scholar-nine-mana-10cards-20261118.png")
    image = np.zeros((1080, 1920, 3), np.uint8)
    image[:, 320:] = crop
    parser = _parser()
    assert parser.parse(image).mana == 9

    image[674:685, 1671:1693] = 0
    state = parser.parse(image)
    assert state.ui_state is UIState.MY_TURN_IDLE
    assert state.mana == 9
    assert not state.has_fresh_readings("mana")
    assert state.spell_mana == 3


def test_scholar_nine_mana_and_ten_card_expanded_hand() -> None:
    from lorwright.cli.app import _battle_layers
    from lorwright.core.champions import load
    from lorwright.core.decide.router import Router
    from lorwright.core.models import ActionType

    crop = _load("f1-scholar-nine-mana-10cards-20261118.png")
    image = np.zeros((1080, 1920, 3), np.uint8)
    image[:, 320:1920] = crop
    pack = load("jinx")
    parser = _parser()
    parser.card_recognizer = pack.recognize_hand
    parser.my_unit_recognizer = pack.recognize_my_units
    state = parser.parse(image)
    assert state.ui_state is UIState.MY_TURN_IDLE
    assert state.mana == 9 and state.has_fresh_readings("mana")
    assert state.spell_mana == 3 and state.has_fresh_readings("spell_mana")
    assert state.hand_expanded is True
    assert len(state.hand) == 10
    assert [c.cost for c in state.hand] == [1, 2, 2, 3, 3, 2, 1, 1, 1, 2]
    assert all(c.drag_point_valid for c in state.hand)
    assert state.hand[4].name == "吉茵珂絲"
    assert state.hand[5].name == "勤奮的學徒"
    assert state.my_units == []
    assert not state.readings["my_units_visible"].fresh
    router = Router(_battle_layers(pack))
    decision = router.decide(state)
    assert decision.action.type is ActionType.PLAY_CARD
    assert decision.action.card_index in (4, 5)
