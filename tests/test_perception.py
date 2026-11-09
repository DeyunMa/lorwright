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

from lorwright.config import load_settings
from lorwright.models import Layout, Rect, UIState
from lorwright.perceive.digits import DigitReader
from lorwright.perceive.state import StateParser
from lorwright.perceive.ui_state import UIStateDetector

SCREENS = Path("tests/fixtures/screens")

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


def test_assets_exist() -> None:
    """模板和字形库必须在仓库里，否则真机上会静默失效。"""
    assert (Path("assets/buttons") / "mulligan.png").exists()
    reader = DigitReader()
    reader.load()
    # 7/8/9 还没采到大字号样本（血量 50/30 里没这三个数）。
    # 没样本时读数返回 None（不猜），比读成错的强。
    assert reader.digits >= set(range(0, 7)), f"缺字形：{reader.digits}"


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


def test_hand_costs_from_live_frame() -> None:
    """实战截图里的 6 张手牌费用必须全读对。

    这条盯的是「徽章抠图」：数字是白字、徽章底是蓝色、外环是青色。
    用灰度或 max 通道会在 1080p 把青环并进数字，6 张里错 4 张；
    改判据为 min(R,G,B)（三通道都亮才算白）后全对。
    """
    state = _parser().parse(_load("1080p_hand_fan.png"))
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


def test_collapsed_hand_is_not_expanded() -> None:
    state = _parser().parse(_load("1080p_hand_fan.png"))
    assert state.hand_expanded is False
    assert len(state.hand) == 6


def test_block_phase_is_not_my_turn() -> None:
    """「略過格擋」也是同一块蓝色按钮，但这时手牌拖不动。

    只靠颜色判定会把格挡阶段当成我方回合，策略每帧都试着出牌、每帧都失败
    （表现为「拖拽没反应」，实际是游戏根本不接受）。
    """
    state = _parser().parse(_load("1080p_block_phase.png"))
    assert state.ui_state is UIState.BLOCKING


def test_block_phase_recognizes_elusive_attackers_and_skips_illegal_blocks() -> None:
    from dataclasses import replace

    from lorwright.decide.generic import BlockingPolicy, plan_blocks
    from lorwright.models import ActionType

    state = _parser().parse(_load("1080p_block_phase.png"))
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
    # 现有定位只找回其中 4 个；不能将缺失的两个说成识别成功。
    assert len(positive.enemy_units) == 4
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


def test_main_menu_is_not_a_battle() -> None:
    state = _parser(LEGACY_720P).parse(_load("720p_main_menu.png"))
    assert state.ui_state is UIState.UNKNOWN


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


def test_small_glyph_generalizes_or_refuses() -> None:
    """同一数字存了多个原型后，小字号也能认对；没原型就返回 None，不猜。"""
    reader = DigitReader()
    reader.load()
    # 地图血条上的 6 只有 14px，靠起手卡费（18px）那个原型认出来
    assert reader.read(_load("720p_map.png"), Rect(375, 670, 16, 20)) == 6
    # 主菜单金币 155753 里有 7，字形库里没有 7 → 整串拒读
    assert reader.read(_load("720p_main_menu.png"), Rect(395, 18, 85, 28)) is None


def test_targeting_button_is_detected() -> None:
    """「選擇目標」按钮是深色半透明的（蓝色占比 <0.45），只能靠文字认出来。

    实机栽过：文字判断被套在「蓝色占比 ≥0.45」里面，这个按钮永远进不去，
    整个状态落到 UNKNOWN，策略按「状态不明不点击」空转到引擎停。
    """
    from lorwright.perceive.ui_state import UIStateDetector

    detector = UIStateDetector(action_button=Rect(1680, 470, 132, 132))
    detector.load()
    frame = cv2.imread("tests/fixtures/screens/1080p_targeting.png")
    assert frame is not None
    assert detector.detect(frame) is UIState.TARGETING
