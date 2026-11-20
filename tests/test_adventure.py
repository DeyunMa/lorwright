"""AdventureLoop 流程回归：假设备 + 假引擎，锁住地图循环的行为。

地图帧用库外 fixtures/mapnav 的 1080p 实机截图；运行时与测试都在
1920×1080 设计空间，点击不再 ×2。
2026-11-06 建立：本测试抓到过 coords 字段名错配（first_option vs
rest_first_option），第一次进商店/休息面板就会 AttributeError。
"""

from pathlib import Path

import cv2
import numpy as np
import pytest

from lorwright.core.champions import load
from lorwright.core.config import load_settings
from lorwright.core.device.base import Frame
from lorwright.core.loop.adventure import AdventureLoop
from lorwright.core.loop.outcome import LoopResult
from lorwright.core.models import Rect, UIState
from lorwright.core.perceive.adventure_scene import (
    find_home_adventure_entry,
    is_battle_loading,
    is_globe_loading,
    is_loading_screen,
    is_portal_loading,
    service_error_confirm,
)
from lorwright.core.perceive.mapnav import empty_point, locate_map_hero
from lorwright.core.perceive.ui_state import UIStateDetector
from tools.test_data import fixtures_root

FIXTURES = fixtures_root() / "mapnav"


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

    def run(self, max_ticks: int | None = None, *, close_device: bool = True) -> LoopResult:
        self.run_calls.append(max_ticks)
        return LoopResult("completed", "battle_end")


@pytest.fixture
def adventure(monkeypatch):
    """构造 AdventureLoop，sleep 打桩、save_snapshot 记录。"""
    settings = load_settings()

    def make(frames, ui_script):
        device = FakeDevice(frames)
        engine = FakeEngine(ui_script)
        loop = AdventureLoop(settings, engine, device, pack=load(settings.champion))
        # 直接调用私有节点处理器的用例从假设备已提供首帧的边界开始。
        loop._latest_frame = Frame(image=frames[0] if frames else _blank())
        coords = settings.adventure.to_coords()
        monkeypatch.setattr("lorwright.core.loop.adventure.time.sleep", lambda _: None)
        saved = []
        monkeypatch.setattr(
            "lorwright.core.util.snapshot.save_snapshot",
            lambda image, out_dir, tag: saved.append(tag) or Path("/tmp/fake.png"),
        )
        return loop, device, engine, saved, coords

    return make



def _record_map_localizations(monkeypatch):
    frames = []

    def locate(image):
        frames.append(id(image))
        return locate_map_hero(image)

    monkeypatch.setattr("lorwright.core.loop.adventure.locate_map_hero", locate)
    return frames

@pytest.mark.parametrize("moved", [False, True])
def test_bottom_map_target_is_revealed_once_before_click(adventure, monkeypatch, moved):
    before = _img("f1-weekly-after-hero-reward-20261116.png")
    # 原图与平移后的停止实拍，非逐帧录像；后继还包含一次无效果图标点击。
    after = _img("f1-weekly-panned-gold-20261116.png")
    frames = [before, after if moved else before] + [before] * 6
    loop, device, _, saved, _ = adventure(frames, [UIState.UNKNOWN])
    loop.pack = load("jinx")
    drags = []
    localized = _record_map_localizations(monkeypatch)
    monkeypatch.setattr(device, "drag", lambda *args: drags.append(args), raising=False)
    monkeypatch.setattr(loop, "_handle_node_panel", lambda: True)
    loop.run(max_nodes=1)
    expected_frames = [before, after] if moved else [before] * 7
    assert localized == [id(frame) for frame in expected_frames]
    assert len(drags) == 1
    if moved:
        assert len(device.taps) == 1
        assert 985 < device.taps[0][1] < 1025
        assert saved == []
    else:
        assert device.taps == []
        assert saved == ["map_pan_unverified"]


def test_adventure_never_clicks_an_expired_input_frame(adventure, monkeypatch):
    home = cv2.imread(str(FIXTURES.parent / "reward_timeout" / "f1-after-home.png"))
    loop, device, _, saved, _ = adventure([home], [UIState.UNKNOWN])
    monkeypatch.setattr(loop, "capture_frame", lambda: Frame(home, ts=100.0))
    monkeypatch.setattr("lorwright.core.loop.adventure.time.time", lambda: 103.0)

    assert loop.run(max_nodes=1) == LoopResult("stopped", "adventure_input_frame_expired")
    assert device.taps == []
    assert saved == ["adventure_input_frame_expired"]


def test_home_transition_ignores_a_frame_that_returns_after_deadline(adventure, monkeypatch):
    home = cv2.imread(str(FIXTURES.parent / "reward_timeout" / "f1-after-home.png"))
    resume = cv2.imread(str(FIXTURES.parent / "screens/f1-adventure-resume-20261114.png"))
    loop, device, _, _, _ = adventure([home, resume], [UIState.UNKNOWN])
    clock = [0.0]
    monkeypatch.setattr("lorwright.core.loop.adventure.time.monotonic", lambda: clock[0])
    monkeypatch.setattr(loop, "_wait", lambda seconds, **kwargs: clock.__setitem__(0, clock[0] + seconds))

    def capture_frame():
        frame = device.screencap()
        if frame.image is resume:
            clock[0] += 29
        return frame

    monkeypatch.setattr(loop, "capture_frame", capture_frame)
    recorded = []
    monkeypatch.setattr("lorwright.core.loop.adventure.record_event",
                        lambda event, **fields: recorded.append((event, fields)))
    written = []
    monkeypatch.setattr("lorwright.core.util.snapshot.save_snapshot",
                        lambda image, out_dir, tag: written.append(image) or Path("/tmp/fake.png"))

    assert loop.run(max_nodes=2) == LoopResult("stopped", "home_entry_after")
    assert device.taps == [find_home_adventure_entry(home).center]
    assert len(written) == 1 and written[0] is resume
    assert recorded[-1] == ("adventure_transition_deadline", {
        "reason": "home_entry_transition", "wait_s": 30, "elapsed_s": 31.0,
    })


def test_home_transition_accepts_observed_slow_world_load(adventure, monkeypatch):
    # f1 上 2026-11-19 的主页进入耗时 10.2–15.5 秒；载入画面以空帧代替。
    home = cv2.imread(str(FIXTURES.parent / "reward_timeout" / "f1-after-home.png"))
    resume = cv2.imread(str(FIXTURES.parent / "screens/f1-adventure-resume-20261114.png"))
    loop, device, _, saved, _ = adventure([home] + [_blank()] * 6 + [resume], [UIState.UNKNOWN])
    clock = [0.0]
    monkeypatch.setattr("lorwright.core.loop.adventure.time.monotonic", lambda: clock[0])
    monkeypatch.setattr(loop, "_wait", lambda seconds, **kwargs: clock.__setitem__(0, clock[0] + seconds))

    def capture_frame():
        clock[0] += 0.6
        return device.screencap()

    monkeypatch.setattr(loop, "capture_frame", capture_frame)
    assert loop.run(max_nodes=1) == LoopResult("stopped", "iteration_limit")
    assert clock[0] > 15
    assert device.taps == [find_home_adventure_entry(home).center]
    assert saved == []


GLOBE_LOADING_SAMPLES = ("f1-globe-loading-20261119.png", "f1-globe-loading-20261120.png")


def _globe(name=GLOBE_LOADING_SAMPLES[1]):
    image = cv2.imread(str(FIXTURES.parent / "screens" / name))
    if image is None:
        pytest.skip(f"missing fixture {name}")
    return image


@pytest.mark.parametrize("name", GLOBE_LOADING_SAMPLES)
def test_globe_loading_screen_is_recognized(name):
    assert is_globe_loading(_globe(name))


@pytest.mark.parametrize("path", [
    "reward_timeout/f1-after-home.png",
    "screens/f1-adventure-resume-20261114.png",
    "screens/1080p_home_service_error.png",
    "continue/f1-silver-relic-chest.png",
    "screens/1080p_hand_expanded.png",
])
def test_globe_loading_rejects_other_screens(path):
    image = cv2.imread(str(FIXTURES.parent / path))
    if image is None:
        pytest.skip(f"missing fixture {path}")
    assert not is_globe_loading(image)
    assert not is_globe_loading(_blank())


def _clocked(loop, device, monkeypatch, per_capture):
    clock = [0.0]
    monkeypatch.setattr("lorwright.core.loop.adventure.time.monotonic", lambda: clock[0])
    monkeypatch.setattr(loop, "_wait", lambda seconds, **kwargs: clock.__setitem__(0, clock[0] + seconds))

    def capture_frame():
        clock[0] += per_capture
        return device.screencap()

    monkeypatch.setattr(loop, "capture_frame", capture_frame)
    return clock


def test_home_transition_extends_while_globe_loading_persists(adventure, monkeypatch):
    # 20261120T044919 的载入画面在 30 秒窗口末仍在，随后实时画面为继续冒险页；时序为合成。
    home = cv2.imread(str(FIXTURES.parent / "reward_timeout" / "f1-after-home.png"))
    resume = cv2.imread(str(FIXTURES.parent / "screens/f1-adventure-resume-20261114.png"))
    globe = _globe()
    loop, device, _, saved, _ = adventure([home] + [globe] * 20 + [resume], [UIState.UNKNOWN])
    clock = _clocked(loop, device, monkeypatch, 0.5)
    assert loop.run(max_nodes=1) == LoopResult("stopped", "iteration_limit")
    assert clock[0] > 30
    assert device.taps == [find_home_adventure_entry(home).center]
    assert saved == []


def test_home_transition_globe_loading_extension_is_bounded(adventure, monkeypatch):
    home = cv2.imread(str(FIXTURES.parent / "reward_timeout" / "f1-after-home.png"))
    globe = _globe()
    loop, device, _, saved, _ = adventure([home] + [globe] * 200, [UIState.UNKNOWN])
    clock = _clocked(loop, device, monkeypatch, 0.5)
    assert loop.run(max_nodes=2) == LoopResult("stopped", "home_entry_after")
    assert 30 + AdventureLoop.LOADING_EXTENSION_S - 5 <= clock[0] <= 30 + AdventureLoop.LOADING_EXTENSION_S + 5
    assert device.taps == [find_home_adventure_entry(home).center]
    assert saved == ["home_entry_after"]


def test_home_transition_leaves_time_for_the_last_capture(adventure, monkeypatch):
    home = cv2.imread(str(FIXTURES.parent / "reward_timeout" / "f1-after-home.png"))
    resume = cv2.imread(str(FIXTURES.parent / "screens/f1-adventure-resume-20261114.png"))
    loop, device, _, saved, _ = adventure([home] + [_blank()] * 5 + [resume], [UIState.UNKNOWN])
    clock = [0.0]
    monkeypatch.setattr("lorwright.core.loop.adventure.time.monotonic", lambda: clock[0])
    monkeypatch.setattr(loop, "_wait", lambda seconds, **kwargs: clock.__setitem__(0, clock[0] + seconds))

    def capture_frame():
        clock[0] += 0.1
        return device.screencap()

    monkeypatch.setattr(loop, "capture_frame", capture_frame)
    assert loop.run(max_nodes=1) == LoopResult("stopped", "iteration_limit")
    assert device.taps == [find_home_adventure_entry(home).center]
    assert saved == []


def test_battle_reward_timeout_transition_returns_to_adventure(adventure, monkeypatch):
    home = cv2.imread(str(FIXTURES.parent / "reward_timeout" / "f1-after-home.png"))
    resume = cv2.imread(str(FIXTURES.parent / "screens/f1-adventure-resume-20261114.png"))
    loop, device, engine, _, _ = adventure([_blank(), home, resume], [UIState.MY_TURN_IDLE])
    monkeypatch.setattr(engine, "run", lambda **kwargs: LoopResult("stopped", "reward_timeout_transition"))
    loop.run(max_nodes=2)
    assert device.taps == [find_home_adventure_entry(home).center]


def test_reward_timeout_waits_for_known_scene_without_repeating(adventure):
    image = cv2.imread(str(FIXTURES.parent / "reward_timeout" / "f1.png"))
    assert image is not None
    loop, device, _, saved, _ = adventure([image, image, _blank()], [UIState.MY_TURN_IDLE])
    loop.run(max_nodes=1)
    assert device.taps == [(960, 757)]
    assert saved == []


def test_reward_timeout_transitions_to_home_and_enters_adventure(adventure):
    timeout = cv2.imread(str(FIXTURES.parent / "reward_timeout" / "f1.png"))
    home = cv2.imread(str(FIXTURES.parent / "reward_timeout" / "f1-after-home.png"))
    resume = cv2.imread(str(FIXTURES.parent / "screens/f1-adventure-resume-20261114.png"))
    assert timeout is not None and home is not None and resume is not None
    entry = find_home_adventure_entry(home)
    assert entry is not None
    loop, device, _, saved, _ = adventure([timeout, timeout, home, resume], [])
    loop.run(max_nodes=2)
    assert device.taps == [(960, 757), entry.center]
    assert saved == []


def test_reward_timeout_does_not_accept_obscured_home(adventure):
    timeout = cv2.imread(str(FIXTURES.parent / "reward_timeout" / "f1.png"))
    home = cv2.imread(str(FIXTURES.parent / "reward_timeout" / "f1-after-home.png"))
    assert timeout is not None and home is not None
    home[835:904, 1485:1799] = 0
    loop, device, _, saved, _ = adventure([timeout] + [home] * 6, [])
    loop.run(max_nodes=2)
    assert device.taps == [(960, 757)]
    assert saved == ["reward_timeout_transition_unverified"]


def test_reward_timeout_unknown_transition_stops_without_repeating(adventure):
    image = cv2.imread(str(FIXTURES.parent / "reward_timeout" / "f1.png"))
    assert image is not None
    loop, device, _, saved, _ = adventure([image] + [_blank()] * 6, [])
    loop.run(max_nodes=1)
    assert device.taps == [(960, 757)]
    assert saved == ["reward_timeout_transition_unverified"]


@pytest.mark.parametrize("awaiting_reward", [False, True])
def test_optional_task_reward_clicks_once_then_resumes(adventure, awaiting_reward):
    task = cv2.imread(str(FIXTURES.parent / "continue/f1-task-completed-20261116.png"))
    victory = cv2.imread(str(FIXTURES.parent / "continue/f1-adventure-victory-20261116.png"))
    assert task is not None and victory is not None
    home = cv2.imread(str(FIXTURES.parent / "reward_timeout/f1-after-home.png"))
    loop, device, engine, saved, _ = adventure(
        [task, task, victory, victory, home], [UIState.UNKNOWN] * 3,
    )
    loop._awaiting_battle_reward = awaiting_reward
    result = loop.run(max_nodes=2)
    assert result == LoopResult("completed", "adventure_victory")
    assert len(device.taps) == 2
    assert abs(device.taps[0][0] - 960) < 15
    assert abs(device.taps[0][1] - 954) < 15
    assert engine.run_calls == []
    assert saved == ["adventure_victory"]


@pytest.mark.parametrize("unchanged", [False, True])
def test_task_reward_unknown_or_unchanged_successor_does_not_repeat(adventure, unchanged):
    task = cv2.imread(str(FIXTURES.parent / "continue/f1-task-completed-20261116.png"))
    assert task is not None
    loop, device, _, saved, _ = adventure([task] + [task if unchanged else _blank()] * 6, [])
    loop.run(max_nodes=2)
    assert len(device.taps) == 1
    assert saved == ["task_reward_transition_unverified"]


def test_task_reward_without_button_does_not_tap(adventure):
    task = cv2.imread(str(FIXTURES.parent / "continue/f1-task-completed-20261116.png"))
    assert task is not None
    task[900:] = 0
    loop, device, _, saved, _ = adventure([task], [])
    loop.run(max_nodes=1)
    assert device.taps == []
    assert saved == ["task_reward_continue_missing"]


@pytest.mark.parametrize("successor", ["unchanged", "unknown", "map"])
def test_final_victory_unverified_successor_never_repeats(adventure, successor):
    victory = cv2.imread(str(FIXTURES.parent / "continue/f1-adventure-victory-20261116.png"))
    after = {"unchanged": victory, "unknown": _blank(),
             "map": _img("f1-weekly-after-hero-reward-20261116.png")}[successor]
    loop, device, _, saved, _ = adventure([victory, victory] + [after] * 6, [])
    result = loop.run(max_nodes=1)
    assert device.taps == [(953, 939)]
    assert result == LoopResult("stopped", "adventure_victory_transition_unverified")
    assert loop._details["settlement_closed"] is False
    assert saved == ["adventure_victory", "adventure_victory_transition_unverified"]


def test_final_victory_successor_after_deadline_is_not_completed(adventure, monkeypatch):
    victory = cv2.imread(str(FIXTURES.parent / "continue/f1-adventure-victory-20261116.png"))
    home = cv2.imread(str(FIXTURES.parent / "reward_timeout/f1-after-home.png"))
    loop, device, _, _, _ = adventure([victory, victory, home], [])
    clock = [0.0]
    monkeypatch.setattr("lorwright.core.loop.adventure.time.monotonic", lambda: clock[0])
    monkeypatch.setattr(loop, "_wait", lambda *args, **kwargs: clock.__setitem__(0, 13.0))
    assert loop.run(max_nodes=1).reason == "adventure_victory_transition_unverified"
    assert device.taps == [(953, 939)]
    assert loop._details["settlement_closed"] is False


def test_final_victory_missing_continue_never_taps(adventure):
    victory = cv2.imread(str(FIXTURES.parent / "continue/f1-adventure-victory-20261116.png"))
    victory[900:] = 0
    loop, device, _, _, _ = adventure([victory], [])
    assert loop.run(max_nodes=1).reason == "adventure_victory_continue_missing"
    assert device.taps == []


def test_final_settlement_handles_optional_task_before_outer_screen(adventure):
    victory = cv2.imread(str(FIXTURES.parent / "continue/f1-adventure-victory-20261116.png"))
    task = cv2.imread(str(FIXTURES.parent / "continue/f1-task-completed-20261116.png"))
    home = cv2.imread(str(FIXTURES.parent / "reward_timeout/f1-after-home.png"))
    loop, device, _, _, _ = adventure([victory, victory, task, home], [])
    assert loop.run(max_nodes=1).reason == "adventure_victory"
    assert len(device.taps) == 2
    assert loop._details["settlement_closed"] is True


def test_relic_animation_waits_for_continue_before_single_input(adventure):
    reward = cv2.imread(str(FIXTURES.parent / "continue/f1-silver-relic-converted.png"))
    animation = reward.copy()
    animation[900:] = 0
    home = cv2.imread(str(FIXTURES.parent / "reward_timeout/f1-after-home.png"))
    loop, device, _, _, _ = adventure([animation, animation, reward, reward, home], [])
    assert loop.run(max_nodes=1).reason == "reward_settlement_closed"
    assert len(device.taps) == 1


@pytest.mark.parametrize("unchanged", [False, True])
def test_resume_relic_reward_closes_without_claiming_victory(adventure, unchanged):
    reward = cv2.imread(str(FIXTURES.parent / "continue/f1-silver-relic-converted.png"))
    home = cv2.imread(str(FIXTURES.parent / "reward_timeout/f1-after-home.png"))
    after = [reward] * 6 if unchanged else [home]
    loop, device, _, _, _ = adventure([reward, reward] + after, [])
    result = loop.run(max_nodes=1)
    assert result.reason == ("adventure_victory_transition_unverified" if unchanged
                             else "reward_settlement_closed")
    assert len(device.taps) == 1
    assert loop._details["outcome"] == "unverified"


def test_final_reward_chain_opens_relic_and_closes_converted_reward(adventure):
    victory = cv2.imread(str(FIXTURES.parent / "continue/f1-adventure-victory-20261116.png"))
    rewards = victory.copy()
    rewards[250:] = 0
    rewards[350:1020, 350:1500] = cv2.imread(
        str(FIXTURES.parent / "continue/f1-adventure-rewards-content.png"),
    )
    chest = cv2.imread(str(FIXTURES.parent / "continue/f1-silver-relic-chest.png"))
    converted = cv2.imread(str(FIXTURES.parent / "continue/f1-silver-relic-converted.png"))
    home = cv2.imread(str(FIXTURES.parent / "reward_timeout/f1-after-home.png"))
    loop, device, _, _, _ = adventure(
        [victory, victory, rewards, rewards, chest, chest, converted, converted, home], [],
    )
    assert loop.run(max_nodes=1) == LoopResult("completed", "adventure_victory")
    assert len(device.taps) == 4
    assert loop._details["settlement_closed"] is True


@pytest.mark.parametrize("resume_rewards", [False, True])
def test_final_victory_closes_reward_summary_before_completing(adventure, resume_rewards):
    victory = cv2.imread(str(FIXTURES.parent / "continue/f1-adventure-victory-20261116.png"))
    rewards = victory.copy()
    rewards[250:] = 0
    rewards[350:1020, 350:1500] = cv2.imread(
        str(FIXTURES.parent / "continue/f1-adventure-rewards-content.png"),
    )
    home = cv2.imread(str(FIXTURES.parent / "reward_timeout/f1-after-home.png"))
    frames = [rewards, rewards, home] if resume_rewards else [victory, victory, rewards, rewards, home]
    loop, device, _, _, _ = adventure(frames, [])
    assert loop.run(max_nodes=1) == LoopResult("completed", "adventure_victory")
    assert len(device.taps) == (1 if resume_rewards else 2)
    assert loop._details["settlement_closed"] is True


def test_resume_silver_vault_closes_settlement(adventure):
    vault = cv2.imread(str(FIXTURES.parent / "continue/f1-silver-vault-20261118.png"))
    home = cv2.imread(str(FIXTURES.parent / "reward_timeout/f1-after-home.png"))
    assert vault is not None and home is not None
    loop, device, _, _, _ = adventure([vault, vault, home], [])
    assert loop.run(max_nodes=1) == LoopResult("completed", "reward_settlement_closed")
    assert loop._details["settlement_closed"] is True
    assert device.taps == [(959, 955)]


def test_silver_vault_verifies_revealed_shards_then_exits(adventure):
    vault = cv2.imread(str(FIXTURES.parent / "continue/f1-silver-vault-20261118.png"))
    shards = cv2.imread(str(FIXTURES.parent / "continue/f1-silver-vault-reward-20261118.png"))
    home = cv2.imread(str(FIXTURES.parent / "reward_timeout/f1-after-home.png"))
    assert vault is not None and shards is not None and home is not None
    loop, device, _, _, _ = adventure([vault, vault, shards, shards, home], [])
    assert loop.run(max_nodes=1) == LoopResult("completed", "reward_settlement_closed")
    assert device.taps == [(959, 955), (959, 955)]


def test_final_victory_continues_once_and_verifies_outer_screen(adventure):
    from lorwright.core.perceive.buttons import find_continue_button

    victory = cv2.imread(str(FIXTURES.parent / "continue/f1-adventure-victory-20261116.png"))
    home = cv2.imread(str(FIXTURES.parent / "reward_timeout/f1-after-home.png"))
    loop, device, engine, saved, _ = adventure([victory, victory, home], [])
    result = loop.run(max_nodes=1)
    assert device.taps == [find_continue_button(victory).center]
    assert result == LoopResult("completed", "adventure_victory")
    assert loop._details["settlement_closed"] is True
    assert engine.run_calls == []
    assert saved == ["adventure_victory"]


@pytest.mark.parametrize("awaiting_reward", [False, True])
def test_adventure_victory_completes_instead_of_waiting_for_reward(adventure, awaiting_reward):
    image = cv2.imread(str(FIXTURES.parent / "continue/f1-adventure-victory-20261116.png"))
    assert image is not None
    home = cv2.imread(str(FIXTURES.parent / "reward_timeout/f1-after-home.png"))
    loop, device, engine, saved, _ = adventure([image, image, home], [UIState.UNKNOWN] * 7)
    loop._awaiting_battle_reward = awaiting_reward
    result = loop.run(max_nodes=1)
    assert result == LoopResult("completed", "adventure_victory")
    assert device.taps == [(953, 939)]
    assert engine.run_calls == []
    assert saved == ["adventure_victory"]


def test_final_victory_is_readable_through_cli(adventure, tmp_path):
    import json

    from typer.testing import CliRunner

    from lorwright.cli.sessions import app
    from lorwright.core.runtime.session import RunSession

    image = cv2.imread(str(FIXTURES.parent / "continue/f1-adventure-victory-20261116.png"))
    assert image is not None
    home = cv2.imread(str(FIXTURES.parent / "reward_timeout/f1-after-home.png"))
    loop, device, _, _, _ = adventure([image, image, home], [UIState.UNKNOWN])
    with RunSession(tmp_path, mode="adventure", champion="jinx", device="fake") as run:
        result = loop.run(max_nodes=1)
        run.finish(result.status, result.reason)
    response = CliRunner().invoke(app, ["status", run.run_id, "--root", str(tmp_path), "--json"])
    assert response.exit_code == 0, response.output
    status = json.loads(response.stdout)
    assert status["status"] == "completed"
    assert status["reason"] == "adventure_victory"
    assert status["details"]["outcome"] == "victory"
    assert status["last_snapshot"] == str(Path("/tmp/fake.png"))
    assert "最终胜利结算页" in status["message"]
    assert "是否全程无人介入" in status["message"]
    assert status["details"]["settlement_closed"] is True
    assert device.taps == [(953, 939)]


@pytest.mark.parametrize("source", ["reward_wait", "missions", "vault"])
def test_final_victory_is_a_recognized_post_battle_destination(adventure, source):
    victory = cv2.imread(str(FIXTURES.parent / "continue/f1-adventure-victory-20261116.png"))
    assert victory is not None
    if source == "reward_wait":
        frames, script = [_blank(), victory], [UIState.UNKNOWN]
    else:
        name = "f1-missions-20261115.png" if source == "missions" else "vault_experience.png"
        before = cv2.imread(str(FIXTURES.parent / "continue" / name))
        assert before is not None
        before = cv2.resize(before, (1920, 1080))
        frames, script = [before, victory], [UIState.BATTLE_END, UIState.UNKNOWN]
    home = cv2.imread(str(FIXTURES.parent / "reward_timeout/f1-after-home.png"))
    loop, device, engine, saved, _ = adventure(frames + [victory, home], script)
    loop._awaiting_battle_reward = source == "reward_wait"
    result = loop.run(max_nodes=2)
    assert result == LoopResult("completed", "adventure_victory")
    assert len(device.taps) == (1 if source == "reward_wait" else 2)
    assert engine.run_calls == []
    assert saved == ["adventure_victory"]


def test_missions_clicks_once_and_accepts_recognized_vault(adventure):
    mission = cv2.imread(str(FIXTURES.parent / "continue" / "f1-missions-20261115.png"))
    vault = cv2.imread(str(FIXTURES.parent / "continue" / "vault_experience.png"))
    assert mission is not None and vault is not None
    vault = cv2.resize(vault, (1920, 1080))
    loop, device, _, saved, _ = adventure([mission, mission, vault], [UIState.BATTLE_END])
    loop.run(max_nodes=1)
    assert device.taps == [(1850, 1020)]
    assert saved == []


def test_missions_transition_timeout_never_repeats_click(adventure):
    mission = cv2.imread(str(FIXTURES.parent / "continue" / "f1-missions-20261115.png"))
    assert mission is not None
    loop, device, _, saved, _ = adventure([mission] * 7, [UIState.BATTLE_END])
    loop.run(max_nodes=1)
    assert device.taps == [(1850, 1020)]
    assert saved == ["missions_transition_unverified"]


def test_missions_unknown_transition_stops_without_another_click(adventure):
    mission = cv2.imread(str(FIXTURES.parent / "continue" / "f1-missions-20261115.png"))
    assert mission is not None
    loop, device, _, saved, _ = adventure([mission] + [_blank()] * 6, [UIState.BATTLE_END])
    loop.run(max_nodes=1)
    assert device.taps == [(1850, 1020)]
    assert saved == ["missions_transition_unverified"]


def test_missions_transition_obeys_stop(adventure, monkeypatch):
    from lorwright.core.runtime.session import StopRequested

    mission = cv2.imread(str(FIXTURES.parent / "continue" / "f1-missions-20261115.png"))
    assert mission is not None
    loop, device, _, _, _ = adventure([mission], [UIState.BATTLE_END])
    monkeypatch.setattr(loop, "_wait", lambda *args, **kwargs: (_ for _ in ()).throw(StopRequested()))
    with pytest.raises(StopRequested):
        loop.run(max_nodes=1)
    assert device.taps == [(1850, 1020)]


@pytest.mark.parametrize("swapped", [False, True])
def test_weekly_fork_prefers_event_icon_over_gold_at_either_position(adventure, swapped):
    image = _img("f1-weekly-after-second-reward-20261116.png")
    if swapped:
        event = image[111:191, 649:729].copy()
        gold = image[193:273, 870:950].copy()
        image[111:191, 649:729] = gold
        image[193:273, 870:950] = event
    loop, _, _, _, _ = adventure([image], [])
    loop.pack = load("jinx")
    expected = (910, 233) if swapped else (689, 151)
    for seed in range(6):
        loop.rng.seed(seed)
        node = loop._find_next(image, locate_map_hero(image))
        assert node is not None
        assert (node.x - expected[0]) ** 2 + (node.y - expected[1]) ** 2 < 15 ** 2


@pytest.mark.parametrize("success", [True, False])
def test_field_cook_heals_once_and_verifies_completed_map(adventure, success):
    image = cv2.imread(str(FIXTURES.parent / "screens/f1-field-cook-20261116.png"))
    assert image is not None
    after = cv2.imread(str(FIXTURES.parent / "healer/f1-after-heal.png")) if success else image
    assert after is not None
    loop, device, _, saved, _ = adventure([after] * 8, [])
    loop.pack = load("jinx")
    assert loop._recognized_after_home(image)
    assert loop._handle_node_panel(image) is success
    assert device.taps == [(1441, 1004)]
    assert saved == (["healer_completed"] if success else ["healer_unchanged"])


def test_astrologer_is_a_recognized_adventure_successor(adventure):
    image = cv2.imread(str(FIXTURES.parent / "screens/f1-astrologer-20261116.png"))
    assert image is not None
    loop, _, _, _, _ = adventure([image], [])
    assert loop._recognized_after_home(image)


@pytest.mark.parametrize("transition", [True, False])
def test_astrologer_buys_once_and_requires_exact_payment_before_leaving(adventure, transition):
    from test_astrologer import image, paid_frame, selected_frame

    before, selected = image(), selected_frame()
    after = paid_frame() if transition else selected
    map_image = _img("f1-weekly-after-second-reward-20261116.png")
    frames = [selected, after, map_image] if transition else [selected] * 7
    loop, device, _, saved, _ = adventure(frames, [])
    assert loop._handle_astrologer(before) is transition
    assert device.taps[:2] == [(1764, 350), (1440, 1005)]
    if transition:
        assert device.taps[2:] == [(752, 953)]
        assert saved == []
    else:
        assert len(device.taps) == 2
        assert saved == ["astrologer_purchase_unverified"]


@pytest.mark.parametrize("balance", [550, 950, 500, None])
def test_astrologer_purchase_can_return_directly_to_map(adventure, balance):
    from test_astrologer import selected_frame

    after = cv2.imread(str(FIXTURES.parent / "screens/f1-astrologer-purchased-map-20261116.png"))
    assert after is not None
    if balance == 950:
        before = selected_frame()
        after[1012:1031, 483:496] = cv2.resize(before[984:1023, 1068:1094], (13, 19))
    elif balance == 500:
        after[1012:1031, 500:512] = after[1012:1031, 516:528].copy()
    elif balance is None:
        after[1003:1038, 477:542] = 0
    loop, device, _, saved, _ = adventure([after] * 6, [])
    assert loop._handle_astrologer(selected_frame()) is (balance == 550)
    assert device.taps == [(1440, 1005)]
    assert saved == ([] if balance == 550 else ["astrologer_purchase_unverified"])


def test_astrologer_unknown_selection_never_purchases(adventure):
    from test_astrologer import image

    before = image()
    loop, device, _, saved, _ = adventure([before], [])
    assert not loop._handle_astrologer(before)
    assert device.taps == [(1764, 350)]
    assert saved == ["astrologer_selection_unverified"]


def test_no_next_node_saves_snapshot_and_stops(adventure):
    # 空白画面不能识别为地图 → 快照 + 停止，不点击任何东西
    loop, device, engine, saved, coords = adventure([_blank()], [UIState.UNKNOWN])
    loop.run(max_nodes=3)
    assert device.taps == []
    assert saved == ["unknown_scene"]
    assert engine.run_calls == []


def test_map_waits_for_confirmed_node_before_clicking(adventure, monkeypatch):
    initial, unknown, stable = (_blank() for _ in range(3))
    loop, device, _, saved, _ = adventure([initial, unknown, stable], [])
    monkeypatch.setattr("lorwright.core.loop.adventure.is_map", lambda image: image is not unknown)
    monkeypatch.setattr("lorwright.core.loop.adventure.is_completed_panel", lambda _: False)
    from types import SimpleNamespace

    monkeypatch.setattr(loop, "_find_next", lambda image, hero: SimpleNamespace(
        x=100, y=200, radius=40, needs_reveal=False)
                        if image is stable else None)
    monkeypatch.setattr(loop, "_handle_node_panel", lambda: False)
    loop.run(max_nodes=1)
    assert device.taps == [(100, 200)]
    assert saved == []


def test_map_wait_obeys_stop_without_clicking(adventure, monkeypatch):
    from lorwright.core.runtime.session import StopRequested

    image = _img("1080p_jinx_support_map.jpg")
    loop, device, _, _, _ = adventure([image], [])
    monkeypatch.setattr(loop, "_find_next", lambda image, hero: None)
    monkeypatch.setattr(loop, "_wait", lambda *args, **kwargs: (_ for _ in ()).throw(StopRequested()))
    with pytest.raises(StopRequested):
        loop.run(max_nodes=1)
    assert device.taps == []


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
    loop, device, engine, saved, _ = adventure([image] * 8, [UIState.UNKNOWN])
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
    loop, device, _, saved, _ = adventure([image] * 8, [UIState.UNKNOWN])
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
    loop, device, _, saved, _ = adventure([before] + [after] * 7, [UIState.UNKNOWN])
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
    from lorwright.core.perceive.normalize import Normalizer

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
    assert saved == []


def test_already_selected_support_screen_does_not_guess_prior_choice(adventure):
    image = _support_fixture("m3-supp1.jpg")
    loop, device, _, saved, _ = adventure([image], [UIState.UNKNOWN])
    loop.run(max_nodes=1)
    assert device.taps == []
    assert saved == ["support_unknown"]


def test_support_selects_confirms_and_verifies_map_transition(adventure):
    before, selected = _support_middle_choice_frames()
    after = _support_fixture("m3-supp2.jpg")
    loop, device, _, saved, _ = adventure([before, selected, after], [UIState.UNKNOWN])
    loop.run(max_nodes=1)
    assert device.taps == [(812, 599), (960, 1003)]
    assert saved == []


def test_support_screen_after_travel_uses_same_selection_flow(adventure):
    before, selected = _support_middle_choice_frames()
    after = _support_fixture("m3-supp2.jpg")
    loop, device, _, saved, _ = adventure([before, selected, after], [UIState.UNKNOWN])
    assert loop._handle_node_panel()
    assert device.taps == [(812, 599), (960, 1003)]
    assert saved == []


def test_support_selection_or_confirmation_not_repeated(adventure):
    before, selected = _support_middle_choice_frames()
    loop, device, _, saved, _ = adventure([before, before], [UIState.UNKNOWN])
    loop.run(max_nodes=3)
    assert len(device.taps) == 1
    assert saved == ["support_selection_failed"]
    loop, device, _, saved, _ = adventure([before] + [selected] * 7, [UIState.UNKNOWN])
    loop.run(max_nodes=3)
    assert len(device.taps) == 2
    assert saved == ["support_confirm_unchanged"]


@pytest.mark.parametrize("transition", ["delayed", "unknown"])
def test_support_transition_is_bounded_and_confirmation_not_repeated(adventure, transition):
    before, selected = _support_middle_choice_frames()
    frames = [before, selected] + [_blank()] * (2 if transition == "delayed" else 6)
    if transition == "delayed":
        frames.append(_support_fixture("m3-supp2.jpg"))
    loop, device, _, saved, _ = adventure(frames, [])
    loop.run(max_nodes=1)
    assert device.taps == [(812, 599), (960, 1003)]
    assert saved == ([] if transition == "delayed" else ["support_after_unknown"])


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


def test_home_entry_waits_for_resume_screen_and_continues(adventure):
    home = cv2.imread(str(FIXTURES.parent / "screens/1080p_home_adventure_entry.png"))
    resume = cv2.imread(str(FIXTURES.parent / "screens/f1-adventure-resume-20261114.png"))
    assert home is not None and resume is not None
    loop, device, engine, saved, _ = adventure(
        [home, _blank(), _blank(), resume, _img("1080p_map.png")], [],
    )
    loop.pack = load("jinx")
    result = loop.run(max_nodes=2)
    assert len(device.taps) == 2
    assert 1500 < device.taps[1][0] < 1650
    assert saved == []
    assert engine.run_calls == []
    assert result.reason == "iteration_limit"


def test_home_entry_ignores_transient_battle_ui_before_resume(adventure):
    home = cv2.imread(str(FIXTURES.parent / "screens/1080p_home_adventure_entry.png"))
    resume = cv2.imread(str(FIXTURES.parent / "screens/f1-adventure-resume-20261115.png"))
    assert home is not None and resume is not None
    transition = _blank()
    loop, device, engine, saved, _ = adventure(
        [home, transition, resume, _img("1080p_map.png")], [],
    )
    engine.parser.ui.detect = lambda image: (
        UIState.MY_TURN_IDLE if image is transition else UIState.UNKNOWN
    )
    loop.pack = load("jinx")
    loop.run(max_nodes=2)
    assert len(device.taps) == 2
    assert engine.run_calls == []
    assert saved == []


def test_home_entry_persistent_battle_probe_times_out_without_entering_battle(adventure):
    home = cv2.imread(str(FIXTURES.parent / "screens/1080p_home_adventure_entry.png"))
    assert home is not None
    transition = _blank()
    loop, device, engine, saved, _ = adventure([home] + [transition] * 6, [])
    engine.parser.ui.detect = lambda image: (
        UIState.MY_TURN_IDLE if image is transition else UIState.UNKNOWN
    )
    result = loop.run(max_nodes=2)
    assert len(device.taps) == 1
    assert engine.run_calls == []
    assert saved == ["home_entry_after"]
    assert result.reason == "home_entry_after"


def test_home_entry_unknown_transition_times_out_with_wait_report(adventure, monkeypatch):
    home = cv2.imread(str(FIXTURES.parent / "screens/1080p_home_adventure_entry.png"))
    assert home is not None
    loop, device, _, saved, _ = adventure([home] + [_blank()] * 14, [])
    reports = []
    monkeypatch.setattr(
        "lorwright.core.loop.adventure.report",
        lambda phase, reason=None, **kwargs: reports.append((phase, reason, kwargs)),
    )
    result = loop.run(max_nodes=3)
    waits = [data for phase, reason, data in reports
             if phase == "waiting" and reason == "home_entry_transition"]
    remaining = [data["wait_s"] for data in waits]
    assert len(remaining) == 14
    assert 0 < remaining[-1] <= remaining[0] <= 30
    assert remaining == sorted(remaining, reverse=True)
    assert len(device.taps) == 1
    assert saved == ["home_entry_after"]
    assert result.reason == "home_entry_after"


def test_home_entry_stop_during_transition_does_not_tap_again(adventure, monkeypatch):
    from lorwright.core.runtime.session import StopRequested

    home = cv2.imread(str(FIXTURES.parent / "screens/1080p_home_adventure_entry.png"))
    assert home is not None
    loop, device, _, saved, _ = adventure([home, _blank()], [])

    def stop_on_transition_frame():
        if device.taps:
            raise StopRequested()

    monkeypatch.setattr("lorwright.core.loop.adventure.checkpoint", stop_on_transition_frame)
    with pytest.raises(StopRequested):
        loop.run(max_nodes=3)
    assert len(device.taps) == 1
    assert saved == []


SERVICE_ERROR_SAMPLES = ("1080p_home_service_error.png", "f1-home-service-error-20261120.png")


def _service_error(name):
    image = cv2.imread(str(FIXTURES.parent / "screens" / name))
    if image is None:
        pytest.skip(f"missing fixture {name}")
    return image


@pytest.mark.parametrize("name", SERVICE_ERROR_SAMPLES)
def test_service_error_dialog_is_recognized_without_home_entry(name):
    image = _service_error(name)
    assert find_home_adventure_entry(image) is None
    assert service_error_confirm(image) == Rect(850, 655, 220, 65)


@pytest.mark.parametrize("name", SERVICE_ERROR_SAMPLES)
def test_service_error_confirms_once_then_enters_adventure(adventure, name):
    error = _service_error(name)
    home = cv2.imread(str(FIXTURES.parent / "reward_timeout" / "f1-after-home.png"))
    resume = cv2.imread(str(FIXTURES.parent / "screens/f1-adventure-resume-20261114.png"))
    assert home is not None and resume is not None
    entry = find_home_adventure_entry(home)
    assert entry is not None
    loop, device, _, saved, _ = adventure([error, error, home, resume], [])
    loop.run(max_nodes=2)
    assert device.taps == [(960, 687), entry.center]
    assert saved == []


def test_service_error_that_stays_stops_without_repeating(adventure):
    error = _service_error(SERVICE_ERROR_SAMPLES[0])
    loop, device, _, saved, _ = adventure([error] * 12, [])
    loop.run(max_nodes=3)
    assert device.taps == [(960, 687)]
    assert saved == ["service_error_transition_unverified"]


def test_service_error_unknown_transition_stops_without_repeating(adventure):
    error = _service_error(SERVICE_ERROR_SAMPLES[0])
    loop, device, _, saved, _ = adventure([error] + [_blank()] * 10, [])
    loop.run(max_nodes=1)
    assert device.taps == [(960, 687)]
    assert saved == ["service_error_transition_unverified"]


def test_service_error_recurring_beyond_limit_stops(adventure):
    error = _service_error(SERVICE_ERROR_SAMPLES[0])
    loop, device, _, saved, _ = adventure([error], [])
    loop._service_errors = AdventureLoop.SERVICE_ERROR_LIMIT
    loop.run(max_nodes=1)
    assert device.taps == []
    assert saved == ["service_error_repeated"]


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


def test_resume_then_revive_clicks_each_once_and_processes_map(adventure, monkeypatch):
    resume = cv2.imread(str(FIXTURES.parent / "screens/f1-adventure-resume-20261114.png"))
    revive = cv2.imread(str(FIXTURES.parent / "screens/f1-revive-20261115.png"))
    assert resume is not None and revive is not None
    loop, device, engine, saved, _ = adventure(
        [resume, revive, _blank(), _img("1080p_map.png")], [],
    )
    loop.pack = load("jinx")
    monkeypatch.setattr(loop, "_find_next", lambda image, hero: None)
    result = loop.run(max_nodes=3)
    assert len(device.taps) == 2
    assert device.taps[1] == (960, 912)
    assert saved == ["map_no_next"]
    assert result.reason == "map_no_next"
    assert engine.run_calls == []


@pytest.mark.parametrize("after", ["unchanged", "unknown"])
def test_revive_transition_timeout_never_repeats_click(adventure, after):
    revive = cv2.imread(str(FIXTURES.parent / "screens/f1-revive-20261115.png"))
    assert revive is not None
    frame = revive if after == "unchanged" else _blank()
    loop, device, engine, saved, _ = adventure([revive] + [frame] * 6, [])
    result = loop.run(max_nodes=3)
    assert device.taps == [(960, 912)]
    assert result.reason == "revive_transition_unverified"
    assert saved == ["revive_transition_unverified"]
    assert engine.run_calls == []


def test_revive_obscured_button_does_not_click(adventure):
    revive = cv2.imread(str(FIXTURES.parent / "screens/f1-revive-20261115.png"))
    assert revive is not None
    revive[858:967, 960:1116] = 0
    loop, device, _, saved, _ = adventure([revive], [])
    loop.run(max_nodes=1)
    assert device.taps == []
    assert saved == ["unknown_scene"]


def test_revive_stop_during_transition(adventure, monkeypatch):
    from lorwright.core.runtime.session import StopRequested

    revive = cv2.imread(str(FIXTURES.parent / "screens/f1-revive-20261115.png"))
    assert revive is not None
    loop, device, _, saved, _ = adventure([revive, _blank()], [])

    def stop_on_transition_frame():
        if device.taps:
            raise StopRequested()

    monkeypatch.setattr("lorwright.core.loop.adventure.checkpoint", stop_on_transition_frame)
    with pytest.raises(StopRequested):
        loop.run(max_nodes=3)
    assert device.taps == [(960, 912)]
    assert saved == []


def test_resume_adventure_does_not_repeat_on_unchanged_page(adventure):
    image = cv2.imread(str(FIXTURES.parent / "screens/f1-adventure-resume-20261114.png"))
    assert image is not None
    loop, device, _, saved, _ = adventure([image] * 7, [UIState.UNKNOWN])
    loop.pack = load("jinx")
    loop.run(max_nodes=3)
    assert len(device.taps) == 1
    assert saved == ["resume_transition_unverified"]


@pytest.mark.parametrize("name", ["f1-portal-loading-20261120.png", "f1-portal-loading-dim-20261120.png"])
def test_portal_loading_screen_is_recognized(name):
    portal = cv2.imread(str(FIXTURES.parent / "screens" / name))
    if portal is None:
        pytest.skip(f"missing fixture {name}")
    assert is_portal_loading(portal)
    assert is_loading_screen(portal)
    for path in ("screens/f1-adventure-resume-20261114.png", "continue/f1-task-completed-20261116.png",
                 "screens/weekly-start-animation-20261115.png", "continue/f1-silver-relic-chest.png",
                 "continue/f1-silver-relic-converted.png"):
        other = cv2.imread(str(FIXTURES.parent / path))
        if other is not None:
            assert not is_portal_loading(other)
    assert not is_portal_loading(_blank())


def test_resume_adventure_waits_through_slow_portal_loading(adventure, monkeypatch):
    # 20261120T045638 的传送门载入画面在 12 秒窗口末仍在；载入持续与后继地图为合成时序。
    resume = cv2.imread(str(FIXTURES.parent / "screens/f1-adventure-resume-20261114.png"))
    portal = cv2.imread(str(FIXTURES.parent / "screens/f1-portal-loading-20261120.png"))
    if portal is None:
        pytest.skip("missing fixture f1-portal-loading-20261120.png")
    map_image = _img("f1-weekly-after-hero-reward-20261116.png")
    loop, device, _, saved, _ = adventure([resume] + [portal] * 12 + [map_image], [UIState.UNKNOWN])
    loop.pack = load("jinx")
    clock = _clocked(loop, device, monkeypatch, 0.5)
    loop.run(max_nodes=1)
    assert clock[0] > 12
    assert len(device.taps) == 1
    assert saved == []


def test_resume_adventure_portal_loading_extension_is_bounded(adventure, monkeypatch):
    resume = cv2.imread(str(FIXTURES.parent / "screens/f1-adventure-resume-20261114.png"))
    portal = cv2.imread(str(FIXTURES.parent / "screens/f1-portal-loading-20261120.png"))
    if portal is None:
        pytest.skip("missing fixture f1-portal-loading-20261120.png")
    loop, device, _, saved, _ = adventure([resume] + [portal] * 200, [UIState.UNKNOWN])
    loop.pack = load("jinx")
    clock = _clocked(loop, device, monkeypatch, 0.5)
    loop.run(max_nodes=1)
    assert clock[0] <= 12 + AdventureLoop.LOADING_EXTENSION_S + 5
    assert len(device.taps) == 1
    assert saved == ["resume_transition_unverified"]


def test_any_transition_keeps_observing_while_portal_loading_persists(adventure, monkeypatch):
    # 20261120T051452 战斗结算「繼續」后 12 秒仍为传送门载入画面；后继帧为合成时序。
    portal = cv2.imread(str(FIXTURES.parent / "screens/f1-portal-loading-dim-20261120.png"))
    if portal is None:
        pytest.skip("missing fixture f1-portal-loading-dim-20261120.png")
    map_image = _img("f1-weekly-after-hero-reward-20261116.png")
    loop, device, _, _, _ = adventure([portal] * 20 + [map_image], [])
    clock = _clocked(loop, device, monkeypatch, 0.5)
    seen = next(f for f in loop._transition_frames("continue_transition") if f is map_image)
    assert seen is map_image
    assert clock[0] > 12
    assert device.taps == []


def test_transition_does_not_extend_for_non_loading_frames(adventure, monkeypatch):
    loop, device, _, _, _ = adventure([_blank()] * 100, [])
    clock = _clocked(loop, device, monkeypatch, 0.5)
    list(loop._transition_frames("continue_transition"))
    assert clock[0] <= 13


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


def test_resume_adventure_does_not_merge_evidence_across_frames(adventure):
    image = cv2.imread(str(FIXTURES.parent / "screens/f1-adventure-resume-20261114.png"))
    assert image is not None
    button_only = image.copy()
    button_only[885:1020, 65:240] = 0
    hero_only = image.copy()
    hero_only[965:1000, 1535:1560] = 0
    loop, device, _, saved, _ = adventure([button_only, hero_only], [UIState.UNKNOWN])
    loop.pack = load("jinx")
    loop.run(max_nodes=1)
    assert device.taps == []
    assert saved == ["resume_hero_unknown"]


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


@pytest.mark.parametrize("ui", [UIState.MULLIGAN, UIState.DISCARD])
def test_battle_takeover_runs_engine(adventure, ui):
    # 主循环帧直接是战斗画面（进入战斗节点后）→ 引擎接管，不点任何东西
    loop, device, engine, _, coords = adventure(
        [_img("1080p_zoommax.png")],
        [ui, UIState.UNKNOWN],
    )
    loop.run(max_nodes=1)
    assert engine.run_calls == [400]  # settings.adventure.battle_max_ticks
    assert device.taps == []


def test_battle_safety_stop_is_propagated_without_restarting(adventure, monkeypatch):
    loop, device, engine, _, _ = adventure(
        [_blank(), _blank()], [UIState.MULLIGAN, UIState.MULLIGAN],
    )
    calls = []
    result = LoopResult("stopped", "action_timeout")

    def stop_battle(*, max_ticks, close_device):
        calls.append((max_ticks, close_device))
        return result

    monkeypatch.setattr(engine, "run", stop_battle)
    assert loop.run(max_nodes=4) == result
    assert calls == [(400, False)]
    assert device.taps == []


def test_iteration_limit_does_not_claim_completed_nodes(adventure):
    loop, _, _, _, _ = adventure([], [])
    assert loop.run(max_nodes=0) == LoopResult("stopped", "iteration_limit")


def test_adventure_stop_reports_snapshot_to_session(adventure, tmp_path):
    from lorwright.core.runtime.session import RunSession, read_status

    loop, _, _, _, _ = adventure([_blank()], [UIState.UNKNOWN])
    with RunSession(tmp_path, mode="adventure", champion="test", device="synthetic") as session:
        assert loop.run(max_nodes=2) == LoopResult("stopped", "unknown_scene")
        status = read_status(tmp_path, session.run_id)
        assert status["reason"] == "unknown_scene"
        assert status["details"]["snapshot"] == str(Path("/tmp/fake.png"))
        assert status["details"]["iteration"] == 1


@pytest.mark.parametrize("entry", ["run", "panel", "travel"])
def test_gold_chest_collects_once_and_verifies_map(adventure, entry, monkeypatch):
    reports = []
    monkeypatch.setattr("lorwright.core.loop.adventure.report",
                        lambda phase, reason=None, **details: reports.append((reason, details)))
    chest = _img("f1-gold-chest-20261117.png")
    stable = _img("1080p_jinx_map.png")
    frames = [chest, stable] if entry in {"run", "travel"} else [stable]
    loop, device, _, saved, _ = adventure(frames, [])
    if entry == "run":
        loop.run(max_nodes=1)
    else:
        first = _img("1080p_node_panel.png") if entry == "travel" else chest
        assert loop._handle_node_panel(first)
    assert len(device.taps) == (2 if entry == "travel" else 1)
    assert 1360 <= device.taps[-1][0] <= 1525
    assert 980 <= device.taps[-1][1] <= 1030
    assert saved == []
    verified = [details for reason, details in reports if reason == "gold_chest_map_transition"]
    assert len(verified) == 1
    assert verified[0]["reward_credited_verified"] is False


@pytest.mark.parametrize("damage", ["title", "collect", "partial_title", "partial_collect", "dimmed"])
def test_gold_chest_requires_visible_title_and_collect(adventure, damage):
    from lorwright.core.perceive.adventure_scene import gold_chest_collect_button

    image = _img("f1-gold-chest-20261117.png")
    assert gold_chest_collect_button(image) is not None
    if damage == "title":
        image[345:430, 545:805] = 0
    elif damage == "collect":
        image[960:1050, 1320:1565] = 0
    elif damage == "partial_title":
        image[362:415, 562:605] = 0
    elif damage == "partial_collect":
        image[984:1026, 1356:1398] = 0
    else:
        image //= 2
    assert gold_chest_collect_button(image) is None
    loop, device, _, _, _ = adventure([image], [])
    assert not loop._collect_gold_chest(image)
    assert device.taps == []


@pytest.mark.parametrize("successor", ["chest", "unknown", "panel"])
def test_gold_chest_does_not_repeat_collection_without_verified_map(adventure, successor):
    image = {"chest": _img("f1-gold-chest-20261117.png"), "unknown": _blank(),
             "panel": _img("1080p_node_panel.png")}[successor]
    loop, device, _, saved, _ = adventure([image] * 6, [])
    assert not loop._collect_gold_chest(_img("f1-gold-chest-20261117.png"))
    assert len(device.taps) == 1
    assert device._frames == []
    assert saved == ["gold_chest_transition_unverified"]


def test_gold_chest_identity_rejects_other_nodes_and_sizes():
    from lorwright.core.perceive.adventure_scene import gold_chest_collect_button

    for name in ("1080p_jinx_map.png", "f1-shop-20261114.png", "f1-gold-travel-panel-20261117.png"):
        assert gold_chest_collect_button(_img(name)) is None
    assert gold_chest_collect_button(_img("f1-gold-chest-20261117.png")[:540, :960]) is None


def _item_chest_panel(hero=False):
    image = _blank()
    name = ("f1-hero-item-chest-panel-20261118.png" if hero
            else "f1-item-chest-panel-20261117.png")
    image[340:1025, 530:975] = _img(name)
    return image


@pytest.mark.parametrize("hero", [False, True])
@pytest.mark.parametrize("entry", ["run", "panel", "travel"])
def test_item_chest_leaves_once_and_verifies_map(adventure, entry, hero):
    chest = _item_chest_panel(hero)
    stable = _img("1080p_jinx_map.png")
    frames = [chest, stable] if entry == "run" else [stable]
    if entry == "travel":
        frames = [chest, stable]
    loop, device, _, saved, _ = adventure(frames, [])
    if entry == "run":
        loop.run(max_nodes=1)
    else:
        first = _img("1080p_node_panel.png") if entry == "travel" else chest
        assert loop._handle_node_panel(first)
    assert len(device.taps) == (2 if entry == "travel" else 1)
    assert 645 <= device.taps[-1][0] <= 740
    assert 930 <= device.taps[-1][1] <= 980
    assert saved == []


@pytest.mark.parametrize("hero", [False, True])
@pytest.mark.parametrize("damage", ["title", "leave", "partial_title", "partial_leave", "dimmed"])
def test_item_chest_requires_visible_title_and_leave(adventure, damage, hero):
    from lorwright.core.perceive.adventure_scene import item_chest_leave_button

    image = _item_chest_panel(hero)
    assert item_chest_leave_button(image) is not None
    if damage == "title":
        image[345:430, 545:805] = 0
    elif damage == "leave":
        image[920:990, 630:760] = 0
    elif damage == "partial_title":
        image[361:414, 563:605] = 0
    elif damage == "partial_leave":
        image[929:970, 648:690] = 0
    else:
        image //= 2
    assert item_chest_leave_button(image) is None
    loop, device, _, _, _ = adventure([image], [UIState.UNKNOWN])
    assert not loop._leave_item_chest(image)
    assert device.taps == []


@pytest.mark.parametrize("left", [563, 619, 675, 731, 787, 843])
def test_hero_item_chest_requires_entire_six_character_title(left):
    from lorwright.core.perceive.adventure_scene import item_chest_leave_button

    image = _item_chest_panel(hero=True)
    image[361:414, left:left + 56] = 0
    assert item_chest_leave_button(image) is None


@pytest.mark.parametrize("hero", [False, True])
@pytest.mark.parametrize("successor", ["chest", "unknown", "panel"])
def test_item_chest_leave_stops_without_repeating_input(adventure, successor, hero):
    image = {"chest": _item_chest_panel(hero), "unknown": _blank(),
             "panel": _img("1080p_node_panel.png")}[successor]
    loop, device, _, saved, _ = adventure([image] * 6, [])
    assert not loop._leave_item_chest(_item_chest_panel(hero))
    assert len(device.taps) == 1
    assert device._frames == []
    assert saved == ["item_chest_leave_unverified"]


def test_item_chest_identity_does_not_match_other_nodes():
    from lorwright.core.perceive.adventure_scene import item_chest_leave_button

    assert item_chest_leave_button(_img("f1-shop-20261114.png")) is None
    assert item_chest_leave_button(_img("1080p_jinx_map.png")) is None
    assert item_chest_leave_button(_item_chest_panel()[:540, :960]) is None


def _remaining_shop():
    image = _blank()
    image[340:1060, 530:975] = _img("f1-shop-20261118.png")
    return image


def test_shop_with_different_merchant_leaves_and_verifies_map(adventure):
    from lorwright.core.perceive.adventure_scene import shop_leave_button

    shop = _remaining_shop()
    assert shop_leave_button(shop) is not None
    loop, device, _, saved, _ = adventure(
        [_img("f1-shop-leave-stable-20261116.jpg")], [],
    )
    assert loop._handle_shop(shop)
    assert device.taps == [(691, 1004)]
    assert saved == []


@pytest.mark.parametrize("damage", ["title", "leave", "dimmed", "partial_title"])
def test_remaining_shop_requires_visible_title_and_leave(damage):
    from lorwright.core.perceive.adventure_scene import shop_leave_button

    shop = _remaining_shop()
    if damage == "title":
        shop[345:430, 545:715] = 0
    elif damage == "leave":
        shop[984:1025, 648:735] = 0
    elif damage == "partial_title":
        shop[362:415, 620:675] = 0
    else:
        shop //= 2
    assert shop_leave_button(shop) is None


@pytest.mark.parametrize("missing", [None, "map_back", "astrologer_buy", "shop_leave"])
def test_node_vendor_leaves_only_with_visible_panel_and_exit(adventure, missing):
    from lorwright.core.perceive.adventure_scene import _template, shop_leave_button

    image = _blank()
    for name, x, y in (("map_back", 80, 65), ("astrologer_buy", 1395, 983), ("shop_leave", 648, 929)):
        if name != missing:
            template = _template(name)
            h, w = template.shape
            image[y:y + h, x:x + w] = template[:, :, None]
    button = shop_leave_button(image)
    if missing is not None:
        assert button is None
        return
    assert button.center == (691, 949)
    loop, device, _, saved, _ = adventure([_img("f1-shop-leave-stable-20261116.jpg")], [])
    assert loop._handle_node_panel(image)
    assert device.taps == [(691, 949)]
    assert saved == []


def test_shop_leaves_once_and_waits_if_result_is_not_map(adventure):
    shop = _img("f1-shop-20261114.png")
    loop, device, _, saved, _ = adventure([shop, shop], [])
    loop.run(max_nodes=2)
    assert device.taps == [(691, 1004)]
    assert saved == ["shop_leave_unverified"]


def test_shop_leave_waits_for_visible_map_after_fade(adventure):
    from lorwright.core.perceive.adventure_scene import is_map

    fading = _img("f1-shop-leave-fading-20261116.png")
    stable = _img("f1-shop-leave-stable-20261116.jpg")
    assert not is_map(fading) and is_map(stable)
    # 两张独立实拍按观察顺序回放，不代表精确动画时长。
    loop, device, _, saved, _ = adventure([fading, stable], [])
    assert loop._handle_shop(_img("f1-shop-20261114.png"))
    assert device.taps == [(691, 1004)]
    assert saved == []


@pytest.mark.parametrize("successor", ["f1-shop-20261114.png",
                                       "f1-shop-leave-fading-20261116.png", None])
def test_shop_leave_stops_after_bounded_observations(adventure, successor):
    image = _img(successor) if successor is not None else _blank()
    loop, device, _, saved, _ = adventure([image] * 6, [])
    assert not loop._handle_shop(_img("f1-shop-20261114.png"))
    assert device.taps == [(691, 1004)]
    assert device._frames == []
    assert saved == ["shop_leave_unverified"]


def test_shop_does_not_click_when_title_or_leave_is_obscured(adventure):
    shop = _img("f1-shop-20261114.png")
    from lorwright.core.perceive.adventure_scene import shop_leave_button

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
    image[96:146, 205:288] = 0  # 合成未知页：保留按钮，去掉最终胜利证据。
    loop, device, _, saved, _ = adventure([image], [UIState.UNKNOWN])
    loop.run(max_nodes=1)
    assert device.taps == []
    assert saved == ["unknown_scene"]


def test_battle_end_with_unchanged_continue_does_not_tap_twice(adventure):
    image = cv2.imread(str(FIXTURES.parent / "continue" / "challenge_result.png"))
    assert image is not None
    image = cv2.resize(image, (1920, 1080), interpolation=cv2.INTER_AREA)
    image[96:146, 205:288] = 0  # 合成普通结算页，不满足最终胜利条件。
    loop, device, _, saved, _ = adventure(
        [image, image], [UIState.BATTLE_END, UIState.BATTLE_END],
    )
    loop.run(max_nodes=2)
    assert len(device.taps) == 1
    assert saved == ["continue_transition_unverified"]


def test_continue_waits_through_unknown_until_recognized_scene(adventure, monkeypatch):
    image = cv2.imread(str(FIXTURES.parent / "continue" / "vault_experience.png"))
    assert image is not None
    image = cv2.resize(image, (1920, 1080))
    transition, destination = _blank(), _blank()
    loop, device, _, saved, _ = adventure(
        [image, transition, destination], [UIState.BATTLE_END],
    )
    monkeypatch.setattr(loop, "_recognized_after_home", lambda frame: frame is destination)
    loop.run(max_nodes=1)
    assert len(device.taps) == 1
    assert saved == []


def test_continue_unknown_transition_stops_without_another_click(adventure):
    image = cv2.imread(str(FIXTURES.parent / "continue" / "vault_experience.png"))
    assert image is not None
    image = cv2.resize(image, (1920, 1080))
    loop, device, _, saved, _ = adventure([image] + [_blank()] * 6, [UIState.BATTLE_END])
    loop.run(max_nodes=2)
    assert len(device.taps) == 1
    assert saved == ["continue_transition_unverified"]


def test_continue_transition_obeys_stop(adventure, monkeypatch):
    from lorwright.core.runtime.session import StopRequested

    image = cv2.imread(str(FIXTURES.parent / "continue" / "vault_experience.png"))
    assert image is not None
    image = cv2.resize(image, (1920, 1080))
    loop, device, _, _, _ = adventure([image], [UIState.BATTLE_END])
    monkeypatch.setattr(loop, "_wait", lambda *args, **kwargs: (_ for _ in ()).throw(StopRequested()))
    with pytest.raises(StopRequested):
        loop.run(max_nodes=1)
    assert len(device.taps) == 1


def test_different_result_pages_can_have_continue_in_same_place(adventure):
    images = [
        cv2.imread(str(FIXTURES.parent / "continue" / name))
        for name in ("challenge_result.png", "challenge_experience.png")
    ]
    assert all(image is not None for image in images)
    images = [cv2.resize(image, (1920, 1080), interpolation=cv2.INTER_AREA)
              for image in images]
    for image in images:
        image[96:146, 205:288] = 0  # 合成普通结算页，专测同坐标按钮的转场。
    loop, device, _, saved, _ = adventure(
        images + [_blank()] * 6,
        [UIState.BATTLE_END, UIState.BATTLE_END, UIState.BATTLE_END],
    )
    loop.run(max_nodes=2)
    assert len(device.taps) == 2
    assert abs(device.taps[0][0] - device.taps[1][0]) < 40
    assert saved == ["continue_transition_unverified"]


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


@pytest.mark.parametrize("name", ["1080p_battle_loading_20261114.png", "f1-battle-loading-20261120.png"])
def test_battle_loading_screen_is_recognized(name):
    image = cv2.imread(str(FIXTURES.parent / "screens" / name))
    if image is None:
        pytest.skip(f"missing fixture {name}")
    assert is_battle_loading(image) and is_loading_screen(image)
    covered = image.copy()
    covered[40:100, 40:180] = 0
    assert not is_battle_loading(covered)


def test_node_transition_waits_through_slow_battle_loading(adventure, monkeypatch):
    # 20261120T055622 的 VS 载入页在 24 秒窗口末仍在；载入持续与换牌后继为合成时序。
    loading = cv2.imread(str(FIXTURES.parent / "screens" / "f1-battle-loading-20261120.png"))
    mulligan = cv2.imread(str(FIXTURES.parent / "screens" / "1080p_jinx_mulligan_20261114.png"))
    if loading is None or mulligan is None:
        pytest.skip("missing battle loading fixtures")
    loop, device, engine, saved, _ = adventure(
        [_img("1080p_battle_detail.png"), *([loading] * 40), mulligan, mulligan], [],
    )
    engine.parser.ui = UIStateDetector(
        threshold=loop.settings.perception.match_threshold,
        action_button=loop.settings.layout.to_layout().end_turn,
    )
    engine.parser.ui.load()
    clock = _clocked(loop, device, monkeypatch, 0.5)
    assert loop._handle_node_panel()
    assert clock[0] > 24
    assert device.taps == [(1581, 1010)]
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


def test_ability_select_picks_preference_once_then_stops(adventure, monkeypatch):
    # 选中一次后保存截图，不自动确认。
    from lorwright.core.champions.base import Preference
    from lorwright.core.decide.rewards import pick_reward

    selected = []

    def record(candidates, preferences):
        pick = pick_reward(candidates, preferences)
        selected.append(pick.candidate.name)
        return pick

    monkeypatch.setattr("lorwright.core.loop.adventure.pick_reward", record)
    loop, device, engine, saved, _ = adventure(
        [_img("1080p_zoommax.png"), _img("1080p_ability_select.png")],
        [UIState.UNKNOWN, UIState.UNKNOWN],
    )
    loop.pack = type("Pack", (), {
        "power_preferences": (Preference(("準備過度",)),),
    })()
    loop.run(max_nodes=1)
    assert device.taps == [(1189, 370), (1303, 430)]
    assert selected == ["準備過度"]  # 英雄偏好压过其他两项稀有品质
    assert saved == ["power_selected_unverified"]
    assert engine.run_calls == []


def _power_fixture(name):
    image = cv2.imread(str(FIXTURES.parent / "power_reward" / name))
    assert image is not None
    return image


def test_node_travel_dispatches_soloist_to_paid_power_handler(adventure, monkeypatch):
    vendor = cv2.imread(str(FIXTURES.parent / "screens/f1-soloist-20261116.png"))
    assert vendor is not None
    loop, device, _, saved, _ = adventure([_img("1080p_node_panel.png"), vendor], [])
    handled = []

    def handle(image):
        handled.append(image)
        return True

    monkeypatch.setattr(loop, "_handle_astrologer", handle)
    assert loop._handle_node_panel()
    assert handled == [vendor]
    assert device.taps == [(817, 485)]
    assert saved == []


def test_node_travel_dispatches_weekly_power_page(adventure, monkeypatch):
    power = _power_fixture("f1-weekly-diamond-20261116.png")
    loop, device, _, saved, _ = adventure([_img("1080p_node_panel.png"), power], [])
    handled = []

    def handle(image):
        handled.append(image)
        return image

    monkeypatch.setattr(loop, "_handle_power", handle)
    assert loop._handle_node_panel()
    assert handled == [power]
    assert device.taps == [(817, 485)]
    assert saved == []


def test_power_resumes_selected_and_confirms_once(adventure, monkeypatch):
    selected = _power_fixture("f1-power-selected-20261115.png")
    next_scene = _img("1080p_zoommax.png")
    loop, device, _, saved, _ = adventure([next_scene], [])
    monkeypatch.setattr(loop, "_recognized_after_home", lambda image: image is next_scene)
    assert loop._handle_power(selected) is next_scene
    assert device.taps == [(960, 1003)]
    assert saved == []


def test_power_selects_then_confirms_after_verification(adventure, monkeypatch):
    initial = _power_fixture("f1-power-20261115.png")
    selected = _power_fixture("f1-power-selected-20261115.png")
    next_scene = _img("1080p_zoommax.png")
    loop, device, _, saved, _ = adventure([selected, next_scene], [])
    monkeypatch.setattr(loop, "_recognized_after_home", lambda image: image is next_scene)
    assert loop._handle_power(initial) is next_scene
    assert device.taps == [(1303, 430), (960, 1003)]
    assert saved == []


def test_power_selected_wrong_preference_or_disabled_stops(adventure):
    from lorwright.core.champions.base import Preference

    selected = _power_fixture("f1-power-selected-20261115.png")
    loop, device, _, saved, _ = adventure([selected], [])
    loop.pack = type("Pack", (), {"power_preferences": (Preference(("因時制宜",)),)})()
    assert loop._handle_power(selected) is None
    assert device.taps == []
    assert saved == ["power_selected_unverified"]
    disabled = selected.copy()
    disabled[960:1045, 800:1120] = 0
    loop, device, _, saved, _ = adventure([disabled], [])
    assert loop._handle_power(disabled) is None
    assert device.taps == []
    assert saved == ["power_selected_unverified"]


def test_power_transition_timeout_never_confirms_twice(adventure):
    selected = _power_fixture("f1-power-selected-20261115.png")
    loop, device, _, saved, _ = adventure([selected] * 7, [])
    assert loop._handle_power(selected) is None
    assert device.taps == [(960, 1003)]
    assert saved == ["power_transition_unverified"]


def test_power_transition_honors_stop_after_confirmation(adventure, monkeypatch):
    from lorwright.core.runtime.session import StopRequested

    selected = _power_fixture("f1-power-selected-20261115.png")
    loop, device, _, _, _ = adventure([selected], [])

    def stop(*args, **kwargs):
        raise StopRequested()

    monkeypatch.setattr(loop, "_wait", stop)
    with pytest.raises(StopRequested):
        loop._handle_power(selected)
    assert device.taps == [(960, 1003)]


def test_hero_item_reward_from_selected_hero_picks_once(adventure):
    image = cv2.imread(str(FIXTURES.parent / "hero_item_reward" / "jinx-selected.png"))
    loop, device, _, saved, _ = adventure([image, image], [])
    loop.pack = load("jinx")
    loop.run(max_nodes=1)
    assert device.taps in [[(615, 750)], [(960, 750)]]
    assert saved == ["hero_item_selected_unverified"]


def test_hero_item_reward_selects_and_verifies_hero_first(adventure):
    folder = FIXTURES.parent / "hero_item_reward"
    before = cv2.imread(str(folder / "before-sample.png"))
    selected = cv2.imread(str(folder / "jinx-selected.png"))
    loop, device, _, saved, _ = adventure([before, selected, selected], [])
    loop.pack = load("jinx")
    loop.run(max_nodes=1)
    assert device.taps[0] == (780, 430)
    assert device.taps[1] in [(615, 750), (960, 750)]
    assert len(device.taps) == 2
    assert saved == ["hero_item_selected_unverified"]


def test_hero_item_reward_does_not_pick_if_hero_unverified(adventure):
    image = cv2.imread(str(FIXTURES.parent / "hero_item_reward" / "before-sample.png"))
    loop, device, _, saved, _ = adventure([image, image], [])
    loop.pack = load("jinx")
    loop.run(max_nodes=1)
    assert device.taps == [(780, 430)]
    assert saved == ["hero_item_hero_unverified"]


def test_hero_item_reward_unknown_item_stops_without_click(adventure):
    image = cv2.imread(str(FIXTURES.parent / "hero_item_reward" / "jinx-selected.png"))
    image[700:745, 906:1036] = 0
    loop, device, _, saved, _ = adventure([image], [])
    loop.pack = load("jinx")
    loop.run(max_nodes=1)
    assert device.taps == []
    assert saved == ["hero_item_selection_unverified"]


def test_hero_item_reward_wrong_selected_hero_stops(adventure):
    image = cv2.imread(str(FIXTURES.parent / "hero_item_reward" / "jinx-selected.png"))
    loop, device, _, saved, _ = adventure([image], [])
    loop.pack = load("elise")
    loop.run(max_nodes=1)
    assert device.taps == []
    assert saved == ["hero_item_wrong_hero"]


def _hero_item_tooltip_frames():
    folder = FIXTURES.parent / "hero_item_reward"
    tooltip = _blank()
    tooltip[:, 350:1500] = cv2.imread(str(folder / "f1-selected-tooltip-20261118.png"))
    # 合成关闭后的可见边框：仅恢复被提示遮挡的核验条带，不当作实机关闭证据。
    clear = tooltip.copy()
    reference = cv2.imread(str(folder / "both-selected.png"))
    clear[245:625, 642:646] = reference[245:625, 642:646]
    return tooltip, clear


@pytest.mark.parametrize("reentry", [False, True])
def test_hero_item_tooltip_dismisses_once_then_reverifies(adventure, monkeypatch, reentry):
    from lorwright.core.perceive.reward_screen import hero_item_hero_selection

    tooltip, clear = _hero_item_tooltip_frames()
    assert hero_item_hero_selection(tooltip) is None
    assert hero_item_hero_selection(clear) == 0
    before = clear.copy()
    if not reentry:
        reference = cv2.imread(str(FIXTURES.parent / "hero_item_reward" / "jinx-selected.png"))
        before[690:816, 471:475] = reference[690:816, 471:475]
        before[960:1045, 800:1120] = reference[960:1045, 800:1120]
    after = _blank()
    frames = [clear, after] if reentry else [tooltip, clear, after]
    loop, device, _, saved, _ = adventure(frames, [])
    loop.pack = load("jinx")
    monkeypatch.setattr(loop.rng, "choice", lambda options: options[0])
    monkeypatch.setattr(loop, "_recognized_after_home", lambda frame: not frame.any())
    assert loop._handle_hero_item_reward(tooltip if reentry else before) is not None
    assert device.taps == ([] if reentry else [(615, 750)]) + [(1500, 900), (960, 1003)]
    assert saved == []


@pytest.mark.parametrize("successor", ["tooltip", "unknown", "changed_items", "changed_selection"])
def test_hero_item_tooltip_unverified_successor_never_confirms_or_reselects(adventure, successor):
    tooltip, clear = _hero_item_tooltip_frames()
    if successor == "changed_items":
        clear[700:744, 906:1036] = 0
    elif successor == "changed_selection":
        clear[690:816, 471:475] = clear[690:816, 815:819]
    after = tooltip if successor == "tooltip" else _blank() if successor == "unknown" else clear
    loop, device, _, saved, _ = adventure([after], [])
    loop.pack = load("jinx")
    assert loop._handle_hero_item_reward(tooltip) is None
    assert device.taps == [(1500, 900)]
    assert saved == ["hero_item_selection_unverified"]


@pytest.mark.parametrize("damage", ["page", "heroes", "items", "button", "selection"])
def test_hero_item_tooltip_requires_reward_evidence_before_dismiss(adventure, damage):
    image, _ = _hero_item_tooltip_frames()
    if damage == "page":
        image[18:110, 760:1160] = 0
    elif damage == "heroes":
        image[275:455, 680:875] = 0
    elif damage == "items":
        image[700:744, 906:1036] = 0
    elif damage == "button":
        image[960:1045, 800:1120] = 0
    else:
        image[690:816, 471:475] = 0
    loop, device, _, saved, _ = adventure([image], [])
    loop.pack = load("jinx")
    assert loop._handle_hero_item_reward(image) is None
    assert device.taps == []
    assert saved == ["hero_item_selection_unverified"]


def test_hero_item_reentry_confirms_without_new_choice(adventure, monkeypatch):
    image = cv2.imread(str(FIXTURES.parent / "hero_item_reward" / "both-selected.png"))
    after = _blank()
    loop, device, _, saved, _ = adventure([image, after], [])
    loop.pack = load("jinx")
    monkeypatch.setattr(loop, "_recognized_after_home", lambda frame: not frame.any())
    loop.run(max_nodes=1)
    assert device.taps == [(960, 1003)]
    assert saved == []


def test_hero_item_real_map_transition_continues_adventure(adventure, monkeypatch):
    image = cv2.imread(str(FIXTURES.parent / "hero_item_reward" / "both-selected.png"))
    after = _img("1080p_map.png")
    loop, device, _, saved, _ = adventure([image, after], [])
    loop.pack = load("jinx")
    monkeypatch.setattr(loop, "_find_next", lambda image, hero: None)
    loop.run(max_nodes=2)
    assert device.taps == [(960, 1003)]
    assert saved == ["map_no_next"]


def test_hero_item_new_selection_verifies_before_confirm(adventure, monkeypatch):
    folder = FIXTURES.parent / "hero_item_reward"
    before = cv2.imread(str(folder / "jinx-selected.png"))
    selected = cv2.imread(str(folder / "both-selected.png"))
    after = _blank()
    loop, device, _, saved, _ = adventure([before, selected, after], [])
    loop.pack = load("jinx")
    monkeypatch.setattr(loop.rng, "choice", lambda options: options[0])
    monkeypatch.setattr(loop, "_recognized_after_home", lambda frame: not frame.any())
    loop.run(max_nodes=1)
    assert device.taps == [(615, 750), (960, 1003)]
    assert saved == []


def test_hero_item_selected_but_disabled_stops(adventure):
    folder = FIXTURES.parent / "hero_item_reward"
    image = cv2.imread(str(folder / "both-selected.png"))
    disabled = cv2.imread(str(folder / "jinx-selected.png"))
    image[960:1045, 800:1120] = disabled[960:1045, 800:1120]
    loop, device, _, saved, _ = adventure([image], [])
    loop.pack = load("jinx")
    loop.run(max_nodes=1)
    assert device.taps == []
    assert saved == ["hero_item_selected_unverified"]


def test_hero_item_confirmation_timeout_does_not_repeat(adventure):
    image = cv2.imread(str(FIXTURES.parent / "hero_item_reward" / "both-selected.png"))
    loop, device, _, saved, _ = adventure([image] * 7, [])
    loop.pack = load("jinx")
    loop.run(max_nodes=1)
    assert device.taps == [(960, 1003)]
    assert saved == ["hero_item_transition_unverified"]


def test_hero_item_stop_during_transition(adventure, monkeypatch):
    from lorwright.core.runtime.session import StopRequested

    image = cv2.imread(str(FIXTURES.parent / "hero_item_reward" / "both-selected.png"))
    loop, device, _, _, _ = adventure([image], [])
    loop.pack = load("jinx")
    def stop(*args, **kwargs):
        raise StopRequested("stop")
    monkeypatch.setattr(loop, "_wait", stop)
    with pytest.raises(StopRequested):
        loop.run(max_nodes=1)
    assert device.taps == [(960, 1003)]


def test_hero_item_sampling_taps_once_and_stops(adventure):
    image = cv2.imread(str(FIXTURES.parent / "hero_item_reward" / "f1-20261115.png"))
    loop, device, _, saved, _ = adventure([image, image], [])
    loop.sample_hero_item_jinx = True
    loop.run(max_nodes=3)
    assert device.taps == [(780, 430)]
    assert saved == ["hero_item_jinx_sample"]


def test_hero_item_sampling_rejects_unknown_page(adventure):
    image = cv2.imread(str(FIXTURES.parent / "hero_item_reward" / "f1-20261115.png"))
    image[18:110, 760:1160] = 0
    loop, device, _, saved, _ = adventure([image], [])
    loop.sample_hero_item_jinx = True
    loop.run(max_nodes=3)
    assert device.taps == []
    assert saved == ["hero_item_sample_precondition_failed"]


def test_map_wait_redispatches_card_reward(adventure, monkeypatch):
    reward = cv2.imread(str(FIXTURES.parent / "card_rewards" / "before.png"))
    loop, device, _, saved, _ = adventure([_img("1080p_jinx_map.png"), reward], [])
    monkeypatch.setattr(loop, "_find_next", lambda image, hero: None)
    handled = []
    monkeypatch.setattr(loop, "_handle_card_reward", handled.append)
    loop.run(max_nodes=2)
    assert len(handled) == 1
    assert np.array_equal(handled[0], reward)
    assert device.taps == []
    assert saved == []


@pytest.mark.parametrize("name", ["before.png", "f1-weekly-fourth-reward-20261116.png"])
def test_battle_end_waits_for_reward_before_map_node(adventure, monkeypatch, name):
    reward = cv2.imread(str(FIXTURES.parent / "card_rewards" / name))
    loop, device, engine, saved, _ = adventure(
        [_blank(), _img("1080p_jinx_map.png"), reward], [UIState.MY_TURN_IDLE]
    )
    handled = []
    monkeypatch.setattr(loop, "_handle_card_reward", handled.append)
    loop.run(max_nodes=3)
    assert engine.run_calls == [loop.coords.battle_max_ticks]
    assert len(handled) == 1
    assert device.taps == []
    assert saved == []


@pytest.mark.parametrize("delayed", [False, True])
def test_battle_end_hero_item_reward_continues_to_map(adventure, monkeypatch, delayed):
    reward = cv2.imread(str(FIXTURES.parent / "hero_item_reward" / "both-selected.png"))
    after = _img("1080p_map.png")
    frames = [_blank()]
    if delayed:
        frames.append(_img("1080p_jinx_map.png"))
    frames.extend([reward, after])
    loop, device, engine, saved, _ = adventure(frames, [UIState.MY_TURN_IDLE])
    loop.pack = load("jinx")
    monkeypatch.setattr(loop, "_find_next", lambda image, hero: None)
    loop.run(max_nodes=4)
    assert engine.run_calls == [loop.coords.battle_max_ticks]
    assert device.taps == [(960, 1003)]
    assert saved == ["map_no_next"]


def test_reward_stop_diagnostics_are_readable_through_cli(adventure, tmp_path):
    import json

    from typer.testing import CliRunner

    from lorwright.cli.app import app
    from lorwright.core.runtime.session import RunSession

    image = cv2.imread(str(FIXTURES.parent / "card_rewards/f1-weekly-fourth-reward-20261116.png"))
    image[18:110, 760:1160] = 0
    loop, device, _, saved, _ = adventure([], [])
    with RunSession(tmp_path, mode="adventure", champion="jinx", device="replay") as session:
        loop._snapshot(image, tag="battle_reward_missing")
        session.finish("stopped", "battle_reward_missing")
    runner = CliRunner()
    status = runner.invoke(app, ["sessions", "status", session.run_id, "--root", str(tmp_path)])
    assert status.exit_code == 0
    assert "未通过 title" in status.stdout
    assert "阈值 0.930" in status.stdout
    events = runner.invoke(app, ["sessions", "events", session.run_id,
                                 "--root", str(tmp_path), "--jsonl"])
    assert events.exit_code == 0
    diagnostics = [json.loads(line)["payload"] for line in events.stdout.splitlines()
                   if json.loads(line)["type"] == "perception_diagnostic"]
    assert len(diagnostics) == 1
    evidence = diagnostics[0]
    assert evidence["failed_checks"] == ["title"]
    assert evidence["scores"]["title"] < evidence["threshold"]
    assert evidence["scores"]["subtitle"] >= evidence["threshold"]
    assert evidence["scores"]["choose_button"] >= evidence["threshold"]
    assert evidence["expected_scene"] == "card_reward"
    assert evidence["snapshot"] == str(Path("/tmp/fake.png"))
    assert saved == ["battle_reward_missing"] and device.taps == []


def test_reward_decision_logs_all_candidate_costs(adventure, monkeypatch):
    image = cv2.imread(str(FIXTURES.parent / "card_rewards/f1-weekly-fourth-reward-20261116.png"))
    loop, device, _, saved, _ = adventure([image], [])
    loop.pack = load("jinx")
    events = []
    monkeypatch.setattr("lorwright.core.loop.adventure.record_event",
                        lambda event_type, **payload: events.append((event_type, payload)))
    assert loop._handle_card_reward(image) is None
    decisions = [payload for event_type, payload in events if event_type == "reward_decision"]
    assert len(decisions) == 1
    assert [candidate["preview_cost"] for candidate in decisions[0]["candidates"]] == [2, 2, 4]
    assert [candidate["card_kind"] for candidate in decisions[0]["candidates"]] == [
        "unit", "unit", "spell",
    ]
    assert decisions[0]["selection"] == 0
    assert decisions[0]["reason"]
    assert len(device.taps) == 1
    assert saved == ["card_reward_selection_failed"]


def test_battle_end_missing_reward_stops_without_map_input(adventure):
    loop, device, engine, saved, _ = adventure(
        [_blank()] + [_img("1080p_jinx_map.png")] * 7, [UIState.MY_TURN_IDLE]
    )
    loop.run(max_nodes=3)
    assert engine.run_calls == [loop.coords.battle_max_ticks]
    assert device.taps == []
    assert saved == ["battle_reward_missing"]


@pytest.mark.parametrize("recovery", ["clear", "transient", "persistent"])
def test_card_reward_continues_to_map_after_verified_transition(adventure, recovery):
    from lorwright.core.champions.base import Preference

    reward = FIXTURES.parent / "card_rewards"
    before, selected, after = (cv2.imread(str(reward / name)) for name in (
        "before.png", "selected-left.png", "after.png",
    ))
    clear_map = _img("1080p_jinx_map.png")
    dark_map = cv2.convertScaleAbs(clear_map, alpha=0.5)
    map_frames = {
        "clear": [clear_map],
        "transient": [dark_map, clear_map, clear_map],
        "persistent": [dark_map] * 5,
    }[recovery]
    loop, device, engine, saved, _ = adventure([before, selected, after, *map_frames], [])
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
    if recovery == "persistent":
        assert device.taps == [(555, 393), (960, 1003)]
        assert saved == ["card_reward_after_unknown"]
    else:
        assert device.taps == [(555, 393), (960, 1003), (982, 334)]
        assert saved == ["panel_unknown"]
    assert engine.run_calls == []


def test_jinx_card_reward_uses_unit_priority_before_default(adventure):
    from lorwright.core.decide.card import CardKind
    from lorwright.core.decide.rewards import CardRewardCandidate, RewardCandidate
    from lorwright.core.models import Rect

    before = cv2.imread(str(FIXTURES.parent / "card_rewards" / "before.png"))
    selected = cv2.imread(str(FIXTURES.parent / "card_rewards" / "selected-left.png"))
    after = cv2.imread(str(FIXTURES.parent / "card_rewards" / "after.png"))
    loop, device, _, saved, _ = adventure([before, selected, after, after], [])
    loop.pack = load("jinx")
    candidates = [
        CardRewardCandidate(RewardCandidate("优秀单位", "common", 1), "", True, kind=CardKind.UNIT),
        CardRewardCandidate(RewardCandidate("稀有法术", "rare", 4), "", True, kind=CardKind.SPELL),
        CardRewardCandidate(RewardCandidate("优秀单位", "common", 4), "", True, kind=CardKind.UNIT),
    ]
    # 保留真实选中帧和按钮检查，仅隔离候选识别。
    from unittest.mock import patch

    with patch("lorwright.core.loop.adventure.recognize_card_rewards", return_value=candidates), \
            patch("lorwright.core.loop.adventure.card_reward_target", return_value=Rect(551, 389, 8, 8)):
        loop.run(max_nodes=1)
    assert device.taps == [(555, 393), (960, 1003)]
    assert saved == []


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
    from lorwright.core.champions.base import Preference

    reward = FIXTURES.parent / "card_rewards"
    before = cv2.imread(str(reward / "before.png"))
    selected = cv2.imread(str(reward / "selected-left.png"))
    loop, device, _, saved, _ = adventure([before] + [selected] * 7, [])
    loop.pack = type("Pack", (), {
        "card_preferences": (Preference(("普羅大砲",)),), "item_preferences": (),
    })()
    loop.run(max_nodes=3)
    assert device.taps == [(555, 393), (960, 1003)]
    assert saved == ["card_reward_confirm_unchanged"]


def test_card_reward_does_not_click_an_obscured_target(adventure):
    from lorwright.core.champions.base import Preference

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
    from lorwright.core.champions.base import Preference

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


def test_gold_panel_with_map_shadow_travels_once(adventure):
    # 实拍面板配合合成战斗后继，只核验入口分支及单次旅行输入。
    image = _img("f1-gold-travel-panel-20261117.png")
    loop, device, _, saved, _ = adventure([_blank()], [UIState.UNKNOWN, UIState.MULLIGAN])
    loop.pack = load("jinx")
    assert loop._handle_node_panel(image)
    assert device.taps == [(1173, 355)]
    assert saved == []


@pytest.mark.parametrize("name,point", [
    ("f1-gold-travel-panel-20261117.png", (1173, 355)),
    ("1080p_node_panel.png", (817, 485)),
    ("1080p_battle_detail.png", (1581, 1010)),
])
def test_run_resumes_open_travel_panel_before_map_navigation(adventure, name, point):
    # 两种实拍面板＋合成战斗后继，覆盖公开 run 入口，不能再次点地图节点。
    loop, device, _, saved, _ = adventure(
        [_img(name), _blank()], [UIState.UNKNOWN, UIState.UNKNOWN, UIState.MULLIGAN],
    )
    loop.pack = load("jinx")
    loop.run(max_nodes=1)
    assert device.taps == [point]
    assert saved == []


def test_run_resumes_zoomed_halo_map_without_another_zoom(adventure):
    image = _img("f1-zoomed-branch-map-20261117.png")
    loop, device, _, saved, _ = adventure([image, image], [])
    loop.pack = load("jinx")
    loop.run(max_nodes=1)
    assert len(device.taps) == 1
    assert any((device.taps[0][0] - x) ** 2 + (device.taps[0][1] - y) ** 2 < 25 ** 2
               for x, y in ((1132, 420), (1208, 605)))
    assert saved == ["map_panel_not_open"]


@pytest.mark.parametrize("name, point", [
    ("1080p_jinx_map.png", (982, 334)),
    ("f1-after-gold-zoomed-map-20261117.png", (1062, 331)),
])
def test_occluded_route_zooms_once_then_reparses_before_node_input(adventure, monkeypatch, name, point):
    # 第一种后继为合成；第二种来自实际缩放，节点点击后继仍用重复地图模拟。
    before = _img("f1-after-gold-map-20261117.png")
    fresh = _img(name)
    loop, device, _, saved, _ = adventure([before, fresh, fresh], [])
    loop.pack = load("jinx")
    localized = _record_map_localizations(monkeypatch)
    loop.run(max_nodes=1)
    assert localized == [id(before), id(fresh), id(fresh)]
    assert len(device.taps) == 2
    assert device.taps[0] == (1822, 297)
    assert abs(device.taps[1][0] - point[0]) <= 20
    assert abs(device.taps[1][1] - point[1]) <= 20
    assert saved == ["map_panel_not_open"]


@pytest.mark.parametrize("successor", ["unchanged", "unknown", "panel"])
def test_occluded_route_zoom_never_repeats_or_clicks_unverified_node(adventure, successor):
    before = _img("f1-after-gold-map-20261117.png")
    after = {"unchanged": before, "unknown": _blank(),
             "panel": _img("1080p_node_panel.png")}[successor]
    loop, device, _, saved, _ = adventure([before] + [after] * 3, [])
    loop.pack = load("jinx")
    loop.run(max_nodes=1)
    assert device.taps == [(1822, 297)]
    assert saved == ["map_zoom_unverified"]


def test_open_node_panel_without_verified_action_does_not_click(adventure):
    image = _img("1080p_node_panel.png")
    image[450:520, 650:980] = 0
    loop, device, _, saved, _ = adventure([image], [UIState.UNKNOWN, UIState.UNKNOWN])
    loop.pack = load("jinx")
    loop.run(max_nodes=1)
    assert device.taps == []
    assert saved == ["panel_unknown"]


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


def test_resume_from_current_battle_node(adventure):
    # 地图和详情是同一节点的实拍，战斗帧用假 UI 状态模拟。
    battle = _img("1080p_zoommax.png")
    loop, device, engine, saved, _ = adventure(
        [_img("f1-karma-current-20261114.png"),
         _img("f1-karma-battle-detail-20261114.png"), battle, battle],
        [UIState.UNKNOWN, UIState.UNKNOWN, UIState.MULLIGAN, UIState.MULLIGAN],
    )
    loop.pack = load("jinx")
    loop.run(max_nodes=2)
    assert len(device.taps) == 2
    assert abs(device.taps[0][0] - 960) <= 15
    assert abs(device.taps[0][1] - 540) <= 15
    assert device.taps[1] == (1581, 1010)
    assert engine.run_calls == [400]
    assert saved == []


def test_resume_from_open_battle_detail(adventure):
    battle = _img("1080p_zoommax.png")
    loop, device, engine, saved, _ = adventure(
        [_img("f1-karma-battle-detail-20261114.png"), battle, battle],
        [UIState.UNKNOWN, UIState.UNKNOWN, UIState.MULLIGAN, UIState.MULLIGAN],
    )
    loop.pack = load("jinx")
    loop.run(max_nodes=2)
    assert device.taps == [(1581, 1010)]
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
    assert saved == ["panel_unknown"]


def test_jinx_unrecognized_map_avatar_does_not_navigate(adventure):
    image = _img("1080p_zoommax.png")
    image[410:490, 970:1050] = 0
    loop, device, _, saved, _ = adventure([image] * 7, [UIState.UNKNOWN])
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


def _weekly(name):
    image = cv2.imread(str(FIXTURES.parent / "screens" / name))
    assert image is not None
    return image


def test_home_world_weekly_lowest_detail_start_and_map(adventure):
    home = _weekly("1080p_home_adventure_entry.png")
    world = _weekly("world-weekly-20261115.png")
    listing = _weekly("weekly-list-20261115.png")
    detail = _weekly("weekly-detail-20261115.png")
    animation = _weekly("weekly-start-animation-20261115.png")
    after = _weekly("weekly-after-start-20261115.png")
    loop, device, engine, saved, _ = adventure(
        [home, _blank(), world, world, listing, listing, detail, detail, animation, after], [],
    )
    engine.parser.ui = UIStateDetector(
        threshold=loop.settings.perception.match_threshold,
        action_button=loop.settings.layout.to_layout().end_turn,
    )
    engine.parser.ui.load()
    result = loop.run(max_nodes=4)
    assert device.taps[0] == find_home_adventure_entry(home).center
    assert device.taps[1] == (1380, 464)
    assert abs(device.taps[2][0] - 1265) < 3 and abs(device.taps[2][1] - 530) < 5
    assert device.taps[3] == (1577, 981)
    assert len(device.taps) == 4
    assert result.reason == "iteration_limit"
    assert saved == []
    assert engine.run_calls == []


@pytest.fixture
def completed_weekly_listing():
    listing = _weekly("weekly-one-remaining.png")
    marker = listing[637:717, 665:745].copy()
    listing[108:320, 850:1020] = 0
    listing[150:230, 895:975] = marker
    return listing


def test_weekly_entry_verifies_all_completed_list_without_replaying(adventure, completed_weekly_listing):
    world = _weekly("world-weekly-20261115.png")
    loop, device, _, saved, _ = adventure([world] + [completed_weekly_listing] * 6, [])
    result = loop.run(max_nodes=2)
    assert result.reason == "weekly_already_completed"
    assert device.taps == [(1380, 464)]
    assert saved == ["weekly_already_completed"]


@pytest.mark.parametrize(("hero_matches", "reason"), [
    (True, "iteration_limit"),
    (False, "weekly_replay_hero_unknown"),
])
def test_weekly_replay_requires_new_detail_and_matching_hero(
    adventure, monkeypatch, completed_weekly_listing, hero_matches, reason,
):
    detail = _weekly("weekly-two-detail-20261116.png")
    after = _weekly("weekly-after-start-20261115.png")
    loop, device, _, saved, _ = adventure([completed_weekly_listing, detail, after], [])
    loop.weekly_replay_slot = 2
    monkeypatch.setattr("lorwright.core.loop.adventure.find_weekly_start",
                        lambda image, *, replay: Rect(1398, 947, 358, 68) if replay else None)
    monkeypatch.setattr("lorwright.core.loop.adventure.selected_world_hero_matches",
                        lambda image, pack: hero_matches)
    assert loop.run(max_nodes=2).reason == reason
    assert len(device.taps) == (2 if hero_matches else 1)
    assert 670 < device.taps[0][0] < 740 and 640 < device.taps[0][1] < 720
    if hero_matches:
        assert device.taps[-1] == (1577, 981)
        assert saved == []
    else:
        assert saved == [reason]


@pytest.mark.parametrize(("name", "reason", "taps"), [
    ("world-weekly-20261115.png", "weekly_entry_unverified", 1),
    ("weekly-list-20261115.png", "weekly_selection_unverified", 1),
    ("weekly-detail-20261115.png", "weekly_detail_without_selection", 0),
])
def test_weekly_repeated_polling_never_repeats_input(adventure, name, reason, taps):
    image = _weekly(name)
    loop, device, engine, saved, _ = adventure([image] * 7, [])
    result = loop.run(max_nodes=6)
    assert len(device.taps) == taps
    assert saved == [reason]
    assert result.reason == reason
    assert engine.run_calls == []


@pytest.mark.parametrize("obscure", ["rating", "decimal", "star", "clock"])
def test_weekly_unknown_evidence_never_clicks(adventure, obscure):
    image = _weekly("weekly-list-20261115.png")
    boxes = {"rating": (933, 283, 956, 306), "decimal": (1258, 637, 1266, 646),
             "star": (900, 240, 986, 279), "clock": (930, 123, 960, 155)}
    x1, y1, x2, y2 = boxes[obscure]
    image[y1:y2, x1:x2] = 0
    loop, device, _, saved, _ = adventure([image], [])
    loop.run(max_nodes=3)
    assert device.taps == []
    assert saved == ["unknown_scene" if obscure == "clock" else "weekly_stars_unknown"]


@pytest.mark.parametrize("after_name", ["weekly-detail-20261115.png",
                                         "weekly-start-animation-20261115.png"])
def test_weekly_start_requires_stable_successor_and_never_repeats(adventure, after_name):
    listing = _weekly("weekly-list-20261115.png")
    detail = _weekly("weekly-detail-20261115.png")
    after = _weekly(after_name)
    loop, device, _, saved, _ = adventure([listing, detail] + [after] * 6, [])
    loop.run(max_nodes=4)
    assert len(device.taps) == 2
    assert saved == ["weekly_start_unverified"]


def test_weekly_selection_rejects_detail_with_different_star_rating(adventure):
    listing = _weekly("weekly-list-20261115.png")
    # 让列表全部为 2，详情仍为实拍 1.5，必须拒绝开始。
    listing[576:656, 1215:1316] = listing[236:316, 894:995]
    detail = _weekly("weekly-detail-20261115.png")
    loop, device, _, saved, _ = adventure([listing] + [detail] * 6, [])
    loop.run(max_nodes=3)
    assert len(device.taps) == 1
    assert saved == ["weekly_selection_unverified"]


def test_resume_has_priority_over_weekly_entry(adventure, monkeypatch):
    from lorwright.core.models import Rect

    image = _weekly("f1-adventure-resume-20261114.png")
    after = _weekly("weekly-after-start-20261115.png")
    loop, device, _, saved, _ = adventure([image, after], [])
    loop.pack = load("jinx")
    monkeypatch.setattr("lorwright.core.loop.adventure.find_weekly_entry",
                        lambda image: Rect(1300, 400, 100, 100))
    loop.run(max_nodes=1)
    assert len(device.taps) == 1
    assert 1500 < device.taps[0][0] < 1650 and 950 < device.taps[0][1] < 1010
    assert saved == []


def test_unknown_power_reports_readable_name_quality_and_selection(adventure, monkeypatch):
    image = _power_fixture("f1-power-legendary-20261116.png")
    loop, device, _, saved, _ = adventure([image], [])
    reports = []
    monkeypatch.setattr("lorwright.core.loop.adventure.report",
                        lambda phase, reason=None, **details: reports.append((phase, reason, details)))
    assert loop._handle_power(image) is None
    decisions = [details for phase, reason, details in reports
                 if phase == "decided" and reason == "power_choice"]
    assert len(decisions) == 1
    assert decisions[0]["recommendation"] == "未知能力"
    assert decisions[0]["recommendation_quality"] == "legendary"
    assert decisions[0]["selection"] == 2
    assert device.taps == [(1303, 430)]
    assert saved == ["power_selected_unverified"]


def test_weekly_transition_obeys_cooperative_stop(adventure, monkeypatch):
    from lorwright.core.runtime.session import StopRequested

    loop, device, _, saved, _ = adventure([_weekly("world-weekly-20261115.png")], [])
    monkeypatch.setattr(loop, "_wait", lambda *args, **kwargs: (_ for _ in ()).throw(StopRequested()))
    with pytest.raises(StopRequested):
        loop.run(max_nodes=3)
    assert len(device.taps) == 1
    assert saved == []


def test_node_travel_waits_past_in_transit_map_until_destination_panel_opens(adventure):
    # 旅行点击后英雄先在无面板地图上移动（尚无下一可达节点），随后才弹出节点页面；
    # 拼接既有实拍验证等待分支，不宣称单次连续录像。
    in_transit_map = cv2.imread(str(FIXTURES.parent / "card_rewards" / "after.png"))
    assert in_transit_map is not None
    loop, device, _, saved, _ = adventure(
        [
            _img("1080p_node_panel.png"),
            in_transit_map,
            _remaining_shop(),
            _img("f1-shop-leave-stable-20261116.jpg"),
        ],
        [],
    )
    loop.pack = load("jinx")
    assert loop._handle_node_panel()
    assert device.taps == [(817, 485), (691, 1004)]
    assert saved == []


def test_node_travel_staying_on_map_without_next_node_times_out_once(adventure):
    in_transit_map = cv2.imread(str(FIXTURES.parent / "card_rewards" / "after.png"))
    assert in_transit_map is not None
    loop, device, _, saved, _ = adventure(
        [_img("1080p_node_panel.png"), *([in_transit_map] * 11)],
        [],
    )
    loop.pack = load("jinx")
    assert not loop._handle_node_panel()
    assert device.taps == [(817, 485)]
    assert saved == ["panel_transition_timeout"]


@pytest.mark.parametrize("champion", ["jinx", "elise", None])
def test_map_navigation_does_not_depend_on_champion_avatar(adventure, champion):
    image = _img("1080p_jinx_map.png")
    loop, _, _, _, _ = adventure([image], [])
    loop.pack = load(champion) if champion else object()
    node = loop._find_next(image, locate_map_hero(image))
    assert node is not None
    assert (node.x - 982) ** 2 + (node.y - 334) ** 2 < 20 ** 2


def test_map_navigation_refuses_when_token_is_unverified(adventure):
    image = _img("1080p_jinx_map.png")
    loop, _, _, _, _ = adventure([image], [])
    loop.pack = object()
    assert loop._find_next(image, None) is None


@pytest.mark.parametrize("completed", [True, False])
def test_healer_map_verification_without_champion_avatar(adventure, completed):
    image = cv2.imread(str(FIXTURES.parent / "screens/f1-field-cook-20261116.png"))
    after = cv2.imread(str(FIXTURES.parent / "healer/f1-after-heal.png"))
    assert image is not None and after is not None
    if not completed:
        after[500:560, 930:990] = 0
    loop, _, _, saved, _ = adventure([after] * 8, [])
    loop.pack = object()
    assert loop._handle_healer(image) is completed
    assert saved == ["healer_completed" if completed else "healer_map_unverified"]


@pytest.mark.parametrize("revealed", [False, True])
def test_map_wait_zooms_once_on_fresh_short_edge(adventure, monkeypatch, revealed):
    in_transit = cv2.imread(str(FIXTURES.parent / "card_rewards" / "after.png"))
    assert in_transit is not None
    settled = _img("f1-after-gold-map-20261117.png")
    zoomed = _img("f1-after-gold-zoomed-map-20261117.png")
    after_zoom = [zoomed, zoomed.copy()] if revealed else [settled.copy() for _ in range(3)]
    frames = [in_transit, settled, *after_zoom]
    loop, device, _, saved, _ = adventure(frames, [])
    localized = _record_map_localizations(monkeypatch)

    loop.run(max_nodes=1)

    assert localized == [id(frame) for frame in frames]
    assert device.taps == ([(1822, 297), (1062, 331)] if revealed else [(1822, 297)])
    assert saved == (["map_panel_not_open"] if revealed else ["map_zoom_unverified"])


def test_map_zoom_allowance_renews_after_node(adventure, monkeypatch):
    settled = _img("f1-after-gold-map-20261117.png")
    zoomed = _img("f1-after-gold-zoomed-map-20261117.png")
    # 重放同一对画面模拟不同节点，节点处理验证交接以替身完成。
    frames = [settled, zoomed, settled.copy(), zoomed.copy()]
    loop, device, _, saved, _ = adventure(frames, [])
    localized = _record_map_localizations(monkeypatch)
    monkeypatch.setattr(loop, "_handle_node_panel", lambda: True)

    loop.run(max_nodes=2)

    assert localized == [id(frame) for frame in frames]
    assert device.taps == [(1822, 297), (1062, 331)] * 2
    assert saved == []


def _interrupted_event_map() -> np.ndarray:
    # 2026-11-19 断线打断独奏家后恢复的停止实拍，不在 491dc94 基线内；缺图时跳过。
    image = cv2.imread(str(FIXTURES / "f1-soloist-interrupted-map-20261119.png"))
    if image is None:
        pytest.skip("缺少 f1-soloist-interrupted-map-20261119.png")
    return image


def test_locked_routes_reenter_interrupted_event_node_once(adventure, monkeypatch):
    stopped = _interrupted_event_map()
    vendor = cv2.imread(str(FIXTURES.parent / "screens/f1-soloist-20261116.png"))
    assert vendor is not None
    loop, device, _, saved, _ = adventure([stopped] * 7 + [vendor], [UIState.UNKNOWN] * 8)
    loop.pack = load("jinx")
    handled = []
    monkeypatch.setattr(loop, "_handle_astrologer", lambda image: handled.append(image) or True)
    loop.run(max_nodes=1)
    assert len(device.taps) == 1
    assert abs(device.taps[0][0] - 959) <= 10 and abs(device.taps[0][1] - 534) <= 10
    assert handled == [vendor]
    assert saved == []


def test_locked_routes_reenter_interrupted_power_diamond_once(adventure, monkeypatch):
    stopped = cv2.imread(str(FIXTURES / "f1-power-interrupted-map-20261120.png"))
    if stopped is None:
        pytest.skip("缺少 f1-power-interrupted-map-20261120.png")
    power = cv2.imread(str(FIXTURES.parent / "power_reward/f1-power-20261115.png"))
    assert power is not None
    loop, device, _, saved, _ = adventure([stopped] * 7 + [power], [UIState.UNKNOWN] * 8)
    loop.pack = load("jinx")
    handled = []
    monkeypatch.setattr(loop, "_handle_power", lambda image: handled.append(image) or image)
    loop.run(max_nodes=1)
    assert len(device.taps) == 1
    assert abs(device.taps[0][0] - 960) <= 10 and abs(device.taps[0][1] - 546) <= 10
    assert handled and handled[0] is power
    assert saved == []


def test_reentry_is_not_repeated_when_routes_stay_locked(adventure, monkeypatch):
    stopped = _interrupted_event_map()
    vendor = cv2.imread(str(FIXTURES.parent / "screens/f1-soloist-20261116.png"))
    assert vendor is not None
    loop, device, _, saved, _ = adventure([stopped] * 7 + [vendor] + [stopped] * 7,
                                          [UIState.UNKNOWN] * 16)
    loop.pack = load("jinx")
    monkeypatch.setattr(loop, "_handle_astrologer", lambda image: True)
    loop.run(max_nodes=2)
    assert len(device.taps) == 1
    assert saved == ["map_no_next"]


def test_healer_waits_for_toast_before_verifying_completion(adventure):
    # 2026-11-19 治疗后 3 秒的停止实拍（提示未消失、无完成勾）与随后另行采集的稳定地图，不是连续录像。
    toast = cv2.imread(str(FIXTURES.parent / "healer/f1-healer-toast-map-20261119.png"))
    done = cv2.imread(str(FIXTURES.parent / "healer/f1-healer-completed-map-20261119.png"))
    if toast is None or done is None:
        pytest.skip("缺少 2026-11-19 治疗实拍")
    before = cv2.imread(str(FIXTURES.parent / "healer" / "f1-full-health.png"))
    loop, device, _, saved, _ = adventure([toast, toast, done], [])
    loop.pack = load("jinx")
    assert loop._handle_healer(before) is True
    assert device.taps == [(1441, 1004)]
    assert saved == ["healer_completed"]
