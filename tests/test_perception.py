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
    # TODO(T6): 还没采到 1080p 的起手界面，先拿 720p 旧图 + 旧坐标守住这条规则
    state = _parser(LEGACY_720P).parse(_load("720p_mulligan.png"))
    assert state.ui_state is UIState.MULLIGAN


def test_battle_turn2() -> None:
    state = _parser().parse(_load("1080p_battle_turn2.png"))
    assert state.ui_state is UIState.MY_TURN_IDLE
    assert state.mana == 2
    assert state.nexus_hp == 50
    assert state.enemy_nexus_hp == 30


def test_main_menu_is_not_a_battle() -> None:
    state = _parser(LEGACY_720P).parse(_load("720p_main_menu.png"))
    assert state.ui_state is UIState.UNKNOWN


@pytest.mark.parametrize(
    ("name", "rect", "expected"),
    [
        ("1080p_battle_turn2.png", Rect(215, 390, 56, 40), 30),
        ("1080p_battle_turn2.png", Rect(216, 646, 56, 40), 50),
        ("1080p_battle_turn2.png", Rect(1668, 388, 33, 36), 2),
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
