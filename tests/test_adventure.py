"""AdventureLoop 流程回归：假设备 + 假引擎，锁住地图循环的行为。

地图帧用 tests/fixtures/mapnav 的 1080p 实机截图；运行时与测试都在
1920×1080 设计空间，点击不再 ×2。
2026-11-06 建立：本测试抓到过 coords 字段名错配（first_option vs
rest_first_option），第一次进商店/休息面板就会 AttributeError。
"""

from pathlib import Path

import cv2
import numpy as np
import pytest

from lorwright.champions import load
from lorwright.config import load_settings
from lorwright.loop.adventure import AdventureLoop
from lorwright.models import UIState
from lorwright.perceive.mapnav import empty_point

FIXTURES = Path(__file__).parent / "fixtures" / "mapnav"


def _img(name: str) -> np.ndarray:
    img = cv2.imread(str(FIXTURES / name))
    assert img is not None, name
    return img


def _blank() -> np.ndarray:
    return np.zeros((1080, 1920, 3), np.uint8)


class FakeDevice:
    """按帧序返回截图，记录所有点击。"""

    def __init__(self, frames: list[np.ndarray]) -> None:
        self._frames = list(frames)
        self.taps: list[tuple[int, int]] = []

    def screencap(self):
        from lorwright.device.base import Frame

        img = self._frames.pop(0) if self._frames else self._frames[-1] if self._frames else _blank()
        return Frame(image=img)

    def tap(self, x: int, y: int) -> None:
        self.taps.append((x, y))


class FakeUI:
    """按调用序返回预设 UIState。"""

    def __init__(self, script: list[UIState]) -> None:
        self._script = list(script)

    def detect(self, image) -> UIState:
        return self._script.pop(0) if self._script else UIState.UNKNOWN


class FakeParser:
    def __init__(self, script: list[UIState]) -> None:
        self.ui = FakeUI(script)

    def load(self) -> None:
        pass


class FakeEngine:
    def __init__(self, script: list[UIState]) -> None:
        self.parser = FakeParser(script)
        self.run_calls: list[int | None] = []

    def run(self, max_ticks: int | None = None) -> None:
        self.run_calls.append(max_ticks)


@pytest.fixture
def adventure(monkeypatch):
    """构造 AdventureLoop，sleep 打桩、save_snapshot 记录。"""
    settings = load_settings()

    def make(frames, ui_script):
        device = FakeDevice(frames)
        engine = FakeEngine(ui_script)
        loop = AdventureLoop(settings, engine, device, pack=load(settings.champion))
        coords = settings.adventure.to_coords()
        monkeypatch.setattr("lorwright.loop.adventure.time.sleep", lambda _: None)
        saved = []
        monkeypatch.setattr(
            "lorwright.util.snapshot.save_snapshot",
            lambda image, out_dir, tag: saved.append(tag) or Path("/tmp/fake.png"),
        )
        return loop, device, engine, saved, coords

    return make


def test_no_next_node_saves_snapshot_and_stops(adventure):
    # 空白画面不能识别为地图 → 快照 + 停止，不点击任何东西
    loop, device, engine, saved, coords = adventure([_blank()], [UIState.UNKNOWN])
    loop.run(max_nodes=3)
    assert device.taps == []
    assert saved == ["unknown_scene"]
    assert engine.run_calls == []


def test_unknown_screen_with_blue_content_never_triggers_panel_close(adventure):
    # 蓝色内容本身不足以证明画面是地图面板。
    image = _blank()
    image[100:200, 100:200, 0] = 255
    loop, device, engine, saved, _ = adventure([image], [UIState.UNKNOWN])
    loop.run(max_nodes=1)
    assert device.taps == []
    assert saved
    assert engine.run_calls == []


@pytest.mark.parametrize("name", [
    "1080p_login_splash.png",
    "1080p_login_form.png",
    "1080p_hand_expanded.png",
    "1080p_targeting.png",
])
def test_unknown_non_map_screens_never_trigger_a_tap(adventure, name):
    image = cv2.imread(str(FIXTURES.parent / "screens" / name))
    assert image is not None
    loop, device, _, saved, _ = adventure([image], [UIState.UNKNOWN])
    loop.run(max_nodes=1)
    assert device.taps == []
    assert saved == ["unknown_scene"]


def test_unknown_after_panel_close_is_not_clicked_again(adventure):
    loop, device, _, saved, _ = adventure(
        [_img("1080p_panel.png"), _blank()], [UIState.UNKNOWN, UIState.UNKNOWN],
    )
    loop.run(max_nodes=1)
    assert device.taps == [empty_point(_img("1080p_panel.png"))]
    assert saved == ["panel_no_empty_point"]


def test_battle_takeover_runs_engine(adventure):
    # 主循环帧直接是战斗画面（进入战斗节点后）→ 引擎接管，不点任何东西
    loop, device, engine, _, coords = adventure(
        [_img("1080p_zoommax.png")],
        [UIState.MULLIGAN, UIState.UNKNOWN],
    )
    loop.run(max_nodes=1)
    assert engine.run_calls == [400]  # settings.adventure.battle_max_ticks
    assert device.taps == []


def test_battle_end_taps_recognized_continue(adventure):
    # 已知结算状态下，点截图里识别到的位置。
    image = cv2.imread(str(FIXTURES.parent / "continue" / "vault_experience.png"))
    assert image is not None
    image = cv2.resize(image, (1920, 1080), interpolation=cv2.INTER_AREA)
    loop, device, engine, _, coords = adventure(
        [image, _blank()],
        [UIState.BATTLE_END, UIState.UNKNOWN],
    )
    loop.run(max_nodes=2)
    assert len(device.taps) == 1
    assert abs(device.taps[0][0] - 1272) < 15
    assert abs(device.taps[0][1] - 990) < 15
    assert engine.run_calls == []


def test_battle_end_without_continue_does_not_tap(adventure):
    loop, device, _, saved, _ = adventure([_blank()], [UIState.BATTLE_END])
    loop.run(max_nodes=1)
    assert device.taps == []
    assert saved == ["continue_missing"]


def test_unknown_screen_with_continue_does_not_tap(adventure):
    image = cv2.imread(str(FIXTURES.parent / "continue" / "challenge_result.png"))
    assert image is not None
    image = cv2.resize(image, (1920, 1080), interpolation=cv2.INTER_AREA)
    loop, device, _, saved, _ = adventure([image], [UIState.UNKNOWN])
    loop.run(max_nodes=1)
    assert device.taps == []
    assert saved == ["unknown_scene"]


def test_battle_end_with_unchanged_continue_does_not_tap_twice(adventure):
    image = cv2.imread(str(FIXTURES.parent / "continue" / "challenge_result.png"))
    assert image is not None
    image = cv2.resize(image, (1920, 1080), interpolation=cv2.INTER_AREA)
    loop, device, _, saved, _ = adventure(
        [image, image], [UIState.BATTLE_END, UIState.BATTLE_END],
    )
    loop.run(max_nodes=2)
    assert len(device.taps) == 1
    assert saved == ["continue_unchanged"]


def test_different_result_pages_can_have_continue_in_same_place(adventure):
    images = [
        cv2.imread(str(FIXTURES.parent / "continue" / name))
        for name in ("challenge_result.png", "challenge_experience.png")
    ]
    assert all(image is not None for image in images)
    images = [cv2.resize(image, (1920, 1080), interpolation=cv2.INTER_AREA)
              for image in images]
    loop, device, _, saved, _ = adventure(
        images, [UIState.BATTLE_END, UIState.BATTLE_END],
    )
    loop.run(max_nodes=2)
    assert len(device.taps) == 2
    assert abs(device.taps[0][0] - device.taps[1][0]) < 40
    assert saved == []


def test_node_panel_travel_then_fight(adventure):
    # 节点面板「旅行」→ 战斗详情「戰鬥」→ 引擎接管。
    loop, device, engine, saved, _ = adventure(
        [
            _img("1080p_zoommax.png"),  # 地图：找下一节点
            _img("1080p_node_panel.png"),  # 节点面板：旅行 (817,485)
            _img("1080p_battle_detail.png"),  # 战斗详情：戰鬥 (1581,1010)
            _img("1080p_zoommax.png"),  # 战斗帧
        ],
        [
            UIState.UNKNOWN,
            UIState.UNKNOWN,
            UIState.UNKNOWN,
            UIState.MULLIGAN,
            UIState.MULLIGAN,
        ],
    )
    loop.run(max_nodes=2)
    assert device.taps == [(1189, 370), (817, 485), (1581, 1010)]
    assert engine.run_calls == [400]
    assert saved == []


def test_ability_select_recommends_then_stops_without_blind_taps(adventure, monkeypatch):
    # 识别三项并调用奖励规则；尚无选中后的截图，不盲点卡片/确认。
    from lorwright.champions.base import Preference
    from lorwright.decide.rewards import pick_reward

    selected = []

    def record(candidates, preferences):
        pick = pick_reward(candidates, preferences)
        selected.append(pick.candidate.name)
        return pick

    monkeypatch.setattr("lorwright.loop.adventure.pick_reward", record)
    loop, device, engine, saved, _ = adventure(
        [_img("1080p_zoommax.png"), _img("1080p_ability_select.png")],
        [UIState.UNKNOWN, UIState.UNKNOWN],
    )
    loop.pack = type("Pack", (), {
        "power_preferences": (Preference(("準備過度",)),),
    })()
    loop.run(max_nodes=1)
    assert device.taps == [(1189, 370)]
    assert selected == ["準備過度"]  # 英雄偏好压过其他两项稀有品质
    assert saved == ["power_choice"]
    assert engine.run_calls == []


def test_node_click_that_stays_on_map_does_not_tap_travel(adventure):
    # 节点点击没打开面板（坐标/动画/网络问题）：仍能看到地图节点，禁止盲点旅行。
    loop, device, engine, saved, coords = adventure(
        [_img("1080p_zoommax.png"), _img("1080p_zoommax.png")],
        [UIState.UNKNOWN, UIState.UNKNOWN],
    )
    loop.run(max_nodes=1)
    assert device.taps == [(1189, 370)]
    assert saved == ["map_panel_not_open"]
    assert engine.run_calls == []


def test_jinx_map_taps_next_node_and_checks_the_result(adventure):
    image = _img("1080p_jinx_map.png")
    loop, device, _, saved, _ = adventure([image, image], [UIState.UNKNOWN, UIState.UNKNOWN])
    loop.pack = load("jinx")
    loop.run(max_nodes=1)
    assert len(device.taps) == 1
    assert abs(device.taps[0][0] - 982) <= 20
    assert abs(device.taps[0][1] - 334) <= 20
    # 下一帧仍是地图，不能猜面板已打开或盲点旅行。
    assert saved == ["map_panel_not_open"]


def test_jinx_node_opens_travel_then_battle_panel(adventure):
    # 不同来源截图拼接，只验证程序分支，不宣称真实连续操作。
    loop, device, engine, saved, _ = adventure(
        [_img("1080p_jinx_map.png"), _img("1080p_node_panel.png"),
         _img("1080p_battle_detail.png"), _img("1080p_zoommax.png")],
        [UIState.UNKNOWN, UIState.UNKNOWN, UIState.UNKNOWN, UIState.MULLIGAN, UIState.MULLIGAN],
    )
    loop.pack = load("jinx")
    loop.run(max_nodes=2)
    assert len(device.taps) == 3
    assert abs(device.taps[0][0] - 982) <= 20
    assert abs(device.taps[0][1] - 334) <= 20
    assert device.taps[1:] == [(817, 485), (1581, 1010)]
    assert engine.run_calls == [400]
    assert saved == []


def test_jinx_sharpshooter_node_travel_and_battle(adventure):
    # 同一地图和敌人的三个截图；最终战斗 UI 状态由假引擎模拟。
    loop, device, engine, saved, _ = adventure(
        [_img("1080p_jinx_map.png"), _img("1080p_jinx_travel.png"),
         _img("1080p_jinx_battle_detail.png"), _img("1080p_zoommax.png")],
        [UIState.UNKNOWN, UIState.UNKNOWN, UIState.UNKNOWN, UIState.MULLIGAN, UIState.MULLIGAN],
    )
    loop.pack = load("jinx")
    loop.run(max_nodes=2)
    assert device.taps == [(982, 334), (978, 482), (1581, 1010)]
    assert engine.run_calls == [400]
    assert saved == []


@pytest.mark.parametrize("panel, button", [
    ("1080p_node_panel.png", (817, 485)),
    ("1080p_battle_detail.png", (1581, 1010)),
])
def test_panel_that_does_not_transition_is_not_clicked_twice(adventure, panel, button):
    image = _img(panel)
    loop, device, engine, saved, _ = adventure(
        [_img("1080p_jinx_map.png"), image, image],
        [UIState.UNKNOWN, UIState.UNKNOWN, UIState.UNKNOWN],
    )
    loop.pack = load("jinx")
    loop.run(max_nodes=1)
    assert device.taps == [(982, 334), button]
    assert saved == ["panel_no_action_button"]
    assert engine.run_calls == []


def test_battle_button_returning_to_map_stops(adventure):
    image = _img("1080p_jinx_map.png")
    loop, device, engine, saved, _ = adventure(
        [image, _img("1080p_battle_detail.png"), image],
        [UIState.UNKNOWN, UIState.UNKNOWN, UIState.UNKNOWN],
    )
    loop.pack = load("jinx")
    loop.run(max_nodes=2)
    assert device.taps == [(982, 334), (1581, 1010)]
    assert saved == ["panel_no_action_button"]
    assert engine.run_calls == []


def test_jinx_unrecognized_panel_does_not_navigate(adventure):
    image = _img("1080p_jinx_map.png").copy()
    # 合成深色面板：仍能看到头像及路径，但不应再点地图。
    cv2.rectangle(image, (1050, 180), (1550, 400), (28, 28, 28), -1)
    loop, device, _, saved, _ = adventure([image], [UIState.UNKNOWN])
    loop.pack = load("jinx")
    loop.run(max_nodes=1)
    assert device.taps == []
    assert saved == ["map_no_next"]


def test_jinx_unrecognized_map_avatar_does_not_navigate(adventure):
    loop, device, _, saved, _ = adventure([_img("1080p_zoommax.png")], [UIState.UNKNOWN])
    loop.pack = load("jinx")
    loop.run(max_nodes=1)
    assert device.taps == []
    assert saved == ["map_no_next"]


def test_open_panel_is_closed_by_clicking_empty_map(adventure):
    # 能力/详情面板打开：没有可走节点，点右下空白处关闭，不把它当旅行面板。
    loop, device, engine, saved, coords = adventure(
        [_img("1080p_panel.png"), _img("1080p_map.png")],
        [UIState.UNKNOWN, UIState.UNKNOWN],
    )
    loop.run(max_nodes=1)
    assert device.taps == [empty_point(_img("1080p_panel.png"))]
    assert saved == []
    assert engine.run_calls == []


def test_panel_close_retries_once_if_animation_is_slow(adventure):
    # 第一次点击后仍看到面板（关闭动画/未命中），再点一次 A 点。
    loop, device, engine, saved, coords = adventure(
        [_img("1080p_panel.png"), _img("1080p_panel.png"), _img("1080p_map.png")],
        [UIState.UNKNOWN, UIState.UNKNOWN, UIState.UNKNOWN],
    )
    loop.run(max_nodes=1)
    expected = empty_point(_img("1080p_panel.png"))
    assert device.taps == [expected, expected]
    assert saved == []
