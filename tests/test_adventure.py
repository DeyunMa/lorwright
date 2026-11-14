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
from lorwright.perceive.adventure_scene import find_home_adventure_entry
from lorwright.perceive.mapnav import empty_point
from lorwright.perceive.ui_state import UIStateDetector

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


def test_support_map_without_next_node_stops_without_clicking(adventure):
    image = _img("1080p_jinx_support_map.jpg")
    loop, device, engine, saved, _ = adventure([image], [UIState.UNKNOWN])
    loop.pack = load("jinx")
    loop.run(max_nodes=1)
    assert device.taps == []
    assert saved == ["map_no_next"]
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


def test_healer_taps_once_and_stops_even_if_screen_does_not_change(adventure):
    image = cv2.imread(str(FIXTURES.parent / "healer" / "f1-full-health.png"))
    assert image is not None
    loop, device, engine, saved, _ = adventure([image, image], [UIState.UNKNOWN])
    loop.run(max_nodes=3)
    assert device.taps == [(1441, 1004)]
    assert saved == ["healer_unchanged"]
    assert engine.run_calls == []


def test_healer_does_not_click_when_selected_option_is_unclear(adventure):
    image = cv2.imread(str(FIXTURES.parent / "healer" / "f1-full-health.png"))
    assert image is not None
    image[754:814, 932:979] = 0
    loop, device, engine, saved, _ = adventure([image], [UIState.UNKNOWN])
    loop.run(max_nodes=3)
    assert device.taps == []
    assert saved == ["healer_unknown"]
    assert engine.run_calls == []


def test_healer_opened_from_node_panel_stops_after_one_heal(adventure):
    image = cv2.imread(str(FIXTURES.parent / "healer" / "f1-full-health.png"))
    assert image is not None
    loop, device, _, saved, _ = adventure([image, image], [UIState.UNKNOWN])
    assert not loop._handle_node_panel()
    assert device.taps == [(1441, 1004)]
    assert saved == ["healer_unchanged"]


def test_healer_records_return_to_real_map_and_stops(adventure):
    before = cv2.imread(str(FIXTURES.parent / "healer" / "f1-full-health.png"))
    after = cv2.imread(str(FIXTURES.parent / "healer" / "f1-after-heal.png"))
    assert before is not None and after is not None
    loop, device, _, saved, _ = adventure([before, after], [UIState.UNKNOWN])
    loop.pack = load("jinx")
    loop.run(max_nodes=1)
    assert device.taps == [(1441, 1004)]
    assert saved == ["healer_completed"]


def test_healer_continues_to_the_next_node_after_completion(adventure):
    before = cv2.imread(str(FIXTURES.parent / "healer" / "f1-full-health.png"))
    after = cv2.imread(str(FIXTURES.parent / "healer" / "f1-after-heal.png"))
    assert before is not None and after is not None
    loop, device, _, saved, _ = adventure([before, after, after, _blank()], [UIState.UNKNOWN])
    loop.pack = load("jinx")
    loop.run(max_nodes=2)
    assert device.taps[0] == (1441, 1004)
    assert len(device.taps) == 2
    x, y = device.taps[1]
    assert (x - 1166) ** 2 + (y - 444) ** 2 <= 35 ** 2
    assert saved == ["healer_completed", "panel_unknown"]


def test_healer_returning_to_map_without_completion_stops(adventure):
    before = cv2.imread(str(FIXTURES.parent / "healer" / "f1-full-health.png"))
    after = cv2.imread(str(FIXTURES.parent / "healer" / "f1-after-heal.png"))
    assert before is not None and after is not None
    after[500:560, 930:990] = 0
    loop, device, _, saved, _ = adventure([before, after], [UIState.UNKNOWN])
    loop.pack = load("jinx")
    loop.run(max_nodes=2)
    assert device.taps == [(1441, 1004)]
    assert saved == ["healer_map_unverified"]


def test_healer_stops_when_result_is_unknown(adventure):
    image = cv2.imread(str(FIXTURES.parent / "healer" / "f1-full-health.png"))
    assert image is not None
    loop, device, _, saved, _ = adventure([image, _blank()], [UIState.UNKNOWN])
    loop.run(max_nodes=3)
    assert device.taps == [(1441, 1004)]
    assert saved == ["healer_after_unknown"]


def _support_fixture(name: str) -> np.ndarray:
    image = cv2.imread(str(FIXTURES.parent / "support" / name))
    assert image is not None
    return image


def _support_middle_choice_frames() -> tuple[np.ndarray, np.ndarray]:
    """真实选中帧加费用合成：让已选的中间组成为唯一最低费。"""
    from lorwright.perceive.normalize import Normalizer

    normalizer = Normalizer((1920, 1080))
    before = normalizer.fit(_support_fixture("m3-travel.jpg"))[0]
    selected = normalizer.fit(_support_fixture("m3-supp1.jpg"))[0]
    six = before[584:614, 1264:1293].copy()
    for image in (before, selected):
        image[584:614, 328:357] = six
        image[512:542, 1264:1293] = six
    return before, selected


def test_support_wrong_group_is_not_confirmed(adventure):
    # 原图右侧英雄最便宜，而真实选中帧是中间组，不能点确认。
    before = _support_fixture("m3-travel.jpg")
    selected = _support_fixture("m3-supp1.jpg")
    loop, device, _, saved, _ = adventure([before, selected], [UIState.UNKNOWN])
    loop.run(max_nodes=1)
    assert device.taps == [(639, 264)]
    assert saved == ["support_selection_failed"]


def test_current_support_screen_chooses_elise_and_waits_for_selection(adventure):
    image = cv2.imread(str(FIXTURES.parent / "screens" / "1080p_jinx_support_selection.jpg"))
    assert image is not None
    loop, device, _, saved, _ = adventure([image, image], [UIState.UNKNOWN])
    loop.run(max_nodes=1)
    assert device.taps == [(342, 456)]
    assert saved == ["support_selection_failed"]


def test_native_1080_support_selection_confirms_after_real_selected_frame(adventure):
    before = _support_fixture("jinx-1080-before.jpg")
    selected = _support_fixture("jinx-1080-selected-left.jpg")
    # 后续地图来自历史素材，仅验证确认后的控制流。
    after = _support_fixture("m3-supp2.jpg")
    loop, device, _, saved, _ = adventure([before, selected, after], [UIState.UNKNOWN])
    loop.run(max_nodes=1)
    assert device.taps == [(342, 456), (960, 1003)]
    assert saved == ["support_reward_unverified"]


def test_already_selected_support_screen_does_not_guess_prior_choice(adventure):
    image = _support_fixture("m3-supp1.jpg")
    loop, device, _, saved, _ = adventure([image], [UIState.UNKNOWN])
    loop.run(max_nodes=1)
    assert device.taps == []
    assert saved == ["support_unknown"]


def test_support_selects_confirms_and_stops_when_reward_unverified(adventure):
    before, selected = _support_middle_choice_frames()
    after = _support_fixture("m3-supp2.jpg")
    loop, device, _, saved, _ = adventure([before, selected, after], [UIState.UNKNOWN])
    loop.run(max_nodes=2)
    assert device.taps == [(812, 599), (960, 1003)]
    assert saved == ["support_reward_unverified"]


def test_support_screen_after_travel_uses_same_selection_flow(adventure):
    before, selected = _support_middle_choice_frames()
    after = _support_fixture("m3-supp2.jpg")
    loop, device, _, saved, _ = adventure([before, selected, after], [UIState.UNKNOWN])
    assert not loop._handle_node_panel()
    assert device.taps == [(812, 599), (960, 1003)]
    assert saved == ["support_reward_unverified"]


def test_support_selection_or_confirmation_not_repeated(adventure):
    before, selected = _support_middle_choice_frames()
    loop, device, _, saved, _ = adventure([before, before], [UIState.UNKNOWN])
    loop.run(max_nodes=3)
    assert len(device.taps) == 1
    assert saved == ["support_selection_failed"]
    loop, device, _, saved, _ = adventure([before, selected, selected], [UIState.UNKNOWN])
    loop.run(max_nodes=3)
    assert len(device.taps) == 2
    assert saved == ["support_confirm_unchanged"]


def test_support_does_not_confirm_when_selected_cards_are_obscured(adventure):
    before, selected = _support_middle_choice_frames()
    selected[428:466, 800:1100] = 0
    loop, device, _, saved, _ = adventure([before, selected], [UIState.UNKNOWN])
    loop.run(max_nodes=1)
    assert device.taps == [(812, 599)]
    assert saved == ["support_selection_failed"]


@pytest.mark.parametrize("name", ["1080p_home_adventure_entry.png", "720p_main_menu.png"])
def test_home_adventure_entry_taps_once_and_saves_next_frame(adventure, name):
    image = cv2.imread(str(FIXTURES.parent / "screens" / name))
    assert image is not None
    # 复用相同帧模拟网络慢或未切换，必须只点一次并停止。
    loop, device, engine, saved, _ = adventure([image, image], [UIState.UNKNOWN])
    loop.pack = load("jinx")
    loop.run(max_nodes=3)
    height, width = image.shape[:2]
    assert len(device.taps) == 1
    x, y = device.taps[0]
    assert abs(x - width * 0.855) < 20 * width / 1920
    assert abs(y - height * 0.805) < 20 * height / 1080
    assert saved == ["home_entry_after"]
    assert engine.run_calls == []


@pytest.mark.parametrize("name", ["1080p_home_adventure_entry.png", "720p_main_menu.png"])
def test_home_entry_reaches_tap_with_real_ui_detector(adventure, name):
    image = cv2.imread(str(FIXTURES.parent / "screens" / name))
    assert image is not None
    loop, device, engine, saved, _ = adventure([image, image], [])
    engine.parser.ui = UIStateDetector(
        threshold=loop.settings.perception.match_threshold,
        action_button=loop.settings.layout.to_layout().end_turn,
    )
    engine.parser.ui.load()
    loop.run(max_nodes=1)
    assert len(device.taps) == 1
    assert saved == ["home_entry_after"]
    assert engine.run_calls == []


def test_home_entry_ignores_service_error_overlay(adventure):
    image = cv2.imread(str(FIXTURES.parent / "screens" / "1080p_home_service_error.png"))
    assert image is not None
    assert find_home_adventure_entry(image) is None
    loop, device, _, saved, _ = adventure([image], [UIState.UNKNOWN])
    loop.run(max_nodes=1)
    assert device.taps == []
    assert saved == ["unknown_scene"]


def test_home_entry_rejects_partially_dimmed_label():
    image = cv2.imread(str(FIXTURES.parent / "screens" / "1080p_home_adventure_entry.png"))
    assert image is not None
    # 模拟遮罩仅盖住最后一个字，余下金色文字仍清晰。
    image[857:884, 1760:1770] //= 2
    assert find_home_adventure_entry(image) is None


def test_home_entry_clicks_visible_label_when_card_center_is_covered(adventure):
    image = cv2.imread(str(FIXTURES.parent / "screens" / "1080p_home_adventure_entry.png"))
    assert image is not None
    # 卡片中间可能被覆盖，但标签仍可见；点击必须落在已识别的标签上。
    image[650:820, 1450:1830] = 20
    label = find_home_adventure_entry(image)
    assert label is not None
    loop, device, _, saved, _ = adventure([image, image], [UIState.UNKNOWN])
    loop.run(max_nodes=1)
    assert device.taps == [label.center]
    assert saved == ["home_entry_after"]


def test_resume_adventure_clicks_once_and_accepts_map(adventure):
    image = cv2.imread(str(FIXTURES.parent / "screens/f1-adventure-resume-20261114.png"))
    assert image is not None
    loop, device, engine, saved, _ = adventure([image, _img("1080p_map.png")], [])
    loop.pack = load("jinx")
    engine.parser.ui = UIStateDetector(
        threshold=loop.settings.perception.match_threshold,
        action_button=loop.settings.layout.to_layout().end_turn,
    )
    engine.parser.ui.load()
    loop.run(max_nodes=1)
    assert len(device.taps) == 1
    assert 1500 < device.taps[0][0] < 1650 and 950 < device.taps[0][1] < 1010
    assert saved == []


def test_resume_adventure_does_not_repeat_on_unchanged_page(adventure):
    image = cv2.imread(str(FIXTURES.parent / "screens/f1-adventure-resume-20261114.png"))
    assert image is not None
    loop, device, _, saved, _ = adventure([image] * 7, [UIState.UNKNOWN])
    loop.pack = load("jinx")
    loop.run(max_nodes=3)
    assert len(device.taps) == 1
    assert saved == ["resume_transition_unverified"]


@pytest.mark.parametrize("champion", ["jinx", "elise"])
def test_resume_adventure_stops_if_selected_hero_is_unverified(adventure, champion):
    image = cv2.imread(str(FIXTURES.parent / "screens/f1-adventure-resume-20261114.png"))
    assert image is not None
    if champion == "jinx":
        image[946:991, 320:485] = 0
    loop, device, _, saved, _ = adventure([image], [UIState.UNKNOWN])
    loop.pack = load(champion)
    loop.run(max_nodes=1)
    assert device.taps == []
    assert saved == ["resume_hero_unknown"]


@pytest.mark.parametrize("name", [
    "1080p_login_splash.png",
    "1080p_login_form.png",
    "1080p_hand_expanded.png",
    "1080p_targeting.png",
    "1080p_home_service_error.png",
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


def test_shop_leaves_once_and_waits_if_result_is_not_map(adventure):
    shop = _img("f1-shop-20261114.png")
    loop, device, _, saved, _ = adventure([shop, shop], [])
    loop.run(max_nodes=2)
    assert device.taps == [(691, 1004)]
    assert saved == ["shop_leave_unverified"]


def test_shop_does_not_click_when_title_or_leave_is_obscured(adventure):
    shop = _img("f1-shop-20261114.png")
    from lorwright.perceive.adventure_scene import shop_leave_button

    assert shop_leave_button(shop) is not None
    assert shop_leave_button(shop // 2) is None
    shop[984:1025, 648:735] = 0
    assert shop_leave_button(shop) is None
    loop, device, _, _, _ = adventure([shop], [UIState.UNKNOWN])
    loop.run(max_nodes=1)
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


def test_node_transitions_wait_for_recognized_scenes_without_repeated_taps(adventure):
    # 载入和换牌为 f1 实拍；面板来源于既有素材，拼接仅用于验证流程。
    screens = FIXTURES.parent / "screens"
    loading = cv2.imread(str(screens / "1080p_battle_loading_20261114.png"))
    mulligan = cv2.imread(str(screens / "1080p_jinx_mulligan_20261114.png"))
    assert loading is not None and mulligan is not None
    loop, device, engine, saved, _ = adventure(
        [_img("1080p_jinx_map.png"), _img("1080p_node_panel.png"),
         loading, _img("1080p_battle_detail.png"), loading, mulligan, mulligan], [],
    )
    loop.pack = load("jinx")
    engine.parser.ui = UIStateDetector(
        threshold=loop.settings.perception.match_threshold,
        action_button=loop.settings.layout.to_layout().end_turn,
    )
    engine.parser.ui.load()
    loop.run(max_nodes=2)
    assert device.taps == [(982, 334), (817, 485), (1581, 1010)]
    assert engine.run_calls == [400]
    assert saved == []


def test_node_transition_timeout_stops_without_repeating_battle(adventure):
    loading = cv2.imread(str(
        FIXTURES.parent / "screens" / "1080p_battle_loading_20261114.png"
    ))
    assert loading is not None
    loop, device, engine, saved, _ = adventure(
        [_img("1080p_battle_detail.png"), *([loading] * 11)], [],
    )
    engine.parser.ui = UIStateDetector(
        threshold=loop.settings.perception.match_threshold,
        action_button=loop.settings.layout.to_layout().end_turn,
    )
    engine.parser.ui.load()
    assert not loop._handle_node_panel()
    assert device.taps == [(1581, 1010)]
    assert engine.run_calls == []
    assert saved == ["panel_transition_timeout"]


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


def test_card_reward_stops_after_confirmation_until_reward_is_verified(adventure):
    from lorwright.champions.base import Preference

    reward = FIXTURES.parent / "card_rewards"
    before, selected, after = (cv2.imread(str(reward / name)) for name in (
        "before.png", "selected-left.png", "after.png",
    ))
    loop, device, engine, saved, _ = adventure(
        [before, selected, after, _img("1080p_jinx_map.png")], []
    )
    loop.pack = type("Pack", (), {
        "card_preferences": (Preference(("普羅大砲",)),),
        "item_preferences": (),
        "recognize_map_hero": staticmethod(load("jinx").recognize_map_hero),
    })()
    engine.parser.ui = UIStateDetector(
        threshold=loop.settings.perception.match_threshold,
        action_button=loop.settings.layout.to_layout().end_turn,
    )
    engine.parser.ui.load()
    loop.run(max_nodes=2)
    assert device.taps == [(555, 393), (960, 1003)]
    assert saved == ["card_reward_unverified"]
    assert engine.run_calls == []


def test_jinx_card_reward_uses_champion_cost_rule_before_default(adventure):
    from lorwright.decide.rewards import CardRewardCandidate, RewardCandidate
    from lorwright.models import Rect

    before = cv2.imread(str(FIXTURES.parent / "card_rewards" / "before.png"))
    selected = cv2.imread(str(FIXTURES.parent / "card_rewards" / "selected-left.png"))
    after = cv2.imread(str(FIXTURES.parent / "card_rewards" / "after.png"))
    loop, device, _, saved, _ = adventure([before, selected, after], [])
    loop.pack = load("jinx")
    candidates = [
        CardRewardCandidate(RewardCandidate("普通", "common", 1), "", True),
        CardRewardCandidate(RewardCandidate("稀有", "rare", 4), "", True),
        CardRewardCandidate(RewardCandidate("普通", "common", 4), "", True),
    ]
    # 保留真实选中帧和按钮检查，仅隔离候选识别。
    from unittest.mock import patch

    with patch("lorwright.loop.adventure.recognize_card_rewards", return_value=candidates), \
            patch("lorwright.loop.adventure.card_reward_target", return_value=Rect(551, 389, 8, 8)):
        loop.run(max_nodes=1)
    assert device.taps == [(555, 393), (960, 1003)]
    assert saved == ["card_reward_unverified"]


def test_card_reward_does_not_confirm_when_wrong_card_is_highlighted(adventure):
    reward = FIXTURES.parent / "card_rewards"
    before = cv2.imread(str(reward / "before.png"))
    left_selected = cv2.imread(str(reward / "selected-left.png"))
    loop, device, _, saved, _ = adventure([before, left_selected], [])
    loop.pack = type("Pack", (), {"card_preferences": (), "item_preferences": ()})()
    loop.run(max_nodes=1)
    # 默认选右侧稀有卡；若下一帧却显示左侧高亮，绝不能点确认。
    assert device.taps == [(1375, 393)]
    assert saved == ["card_reward_selection_failed"]


def test_card_reward_confirmation_is_not_repeated(adventure):
    from lorwright.champions.base import Preference

    reward = FIXTURES.parent / "card_rewards"
    before = cv2.imread(str(reward / "before.png"))
    selected = cv2.imread(str(reward / "selected-left.png"))
    loop, device, _, saved, _ = adventure([before, selected, selected], [])
    loop.pack = type("Pack", (), {
        "card_preferences": (Preference(("普羅大砲",)),), "item_preferences": (),
    })()
    loop.run(max_nodes=3)
    assert device.taps == [(555, 393), (960, 1003)]
    assert saved == ["card_reward_confirm_unchanged"]


def test_card_reward_does_not_click_an_obscured_target(adventure):
    from lorwright.champions.base import Preference

    before = cv2.imread(str(FIXTURES.parent / "card_rewards" / "before.png"))
    before[391:396, 553:558] = 0
    loop, device, _, saved, _ = adventure([before], [])
    loop.pack = type("Pack", (), {
        "card_preferences": (Preference(("普羅大砲",)),), "item_preferences": (),
    })()
    loop.run(max_nodes=1)
    assert device.taps == []
    assert saved == ["card_reward_target_obscured"]


def test_card_reward_does_not_treat_blue_unknown_scene_as_battle(adventure):
    from lorwright.champions.base import Preference

    reward = FIXTURES.parent / "card_rewards"
    before = cv2.imread(str(reward / "before.png"))
    selected = cv2.imread(str(reward / "selected-left.png"))
    unknown = _blank()
    loop, device, engine, saved, _ = adventure([before, selected, unknown, unknown], [])
    loop.pack = type("Pack", (), {
        "card_preferences": (Preference(("普羅大砲",)),), "item_preferences": (),
    })()
    button = loop.settings.layout.to_layout().end_turn
    unknown[button.y:button.y + button.h, button.x:button.x + button.w] = (255, 100, 0)
    engine.parser.ui = UIStateDetector(
        threshold=loop.settings.perception.match_threshold, action_button=button,
    )
    engine.parser.ui.load()
    assert engine.parser.ui.detect(unknown) is UIState.MY_TURN_IDLE
    loop.run(max_nodes=2)
    assert device.taps == [(555, 393), (960, 1003)]
    assert saved == ["card_reward_after_unknown"]
    assert engine.run_calls == []


def test_already_selected_card_reward_never_confirms_without_a_pending_choice(adventure):
    selected = cv2.imread(str(FIXTURES.parent / "card_rewards" / "selected-left.png"))
    loop, device, _, saved, _ = adventure([selected], [])
    loop.run(max_nodes=1)
    assert device.taps == []
    assert saved == ["card_reward_unknown"]


@pytest.mark.parametrize("frame", ["after.png", "map-bright.png"])
def test_map_after_card_reward_stops_if_no_verified_next_path(adventure, frame):
    # 同一地图的暗、亮两帧：当前节点光环不能被当作下一条路径。
    image = cv2.imread(str(FIXTURES.parent / "card_rewards" / frame))
    assert image is not None
    loop, device, _, saved, _ = adventure([image], [])
    loop.pack = load("jinx")
    loop.run(max_nodes=1)
    assert device.taps == []
    assert saved == ["map_no_next"]


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
