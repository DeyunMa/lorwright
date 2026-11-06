"""AdventureLoop 流程回归：假设备 + 假引擎，锁住地图循环的行为。

地图帧用 tests/fixtures/mapnav 的真截图（960x540，与运行时 mapnav
输入同尺寸）。坐标空间断言：mapnav 坐标 ×2 后才下发点击。
2026-11-06 建立：本测试抓到过 coords 字段名错配（first_option vs
rest_first_option），第一次进商店/休息面板就会 AttributeError。
"""

from pathlib import Path

import cv2
import numpy as np
import pytest

from lorwright.config import load_settings
from lorwright.loop.adventure import AdventureLoop
from lorwright.models import UIState

FIXTURES = Path(__file__).parent / "fixtures" / "mapnav"


def _img(name: str) -> np.ndarray:
    img = cv2.imread(str(FIXTURES / name))
    assert img is not None, name
    return img


class FakeDevice:
    """按帧序返回截图，记录所有点击。"""

    def __init__(self, frames: list[np.ndarray]) -> None:
        self._frames = list(frames)
        self.taps: list[tuple[int, int]] = []

    def screencap(self):
        from lorwright.device.base import Frame

        img = self._frames.pop(0) if self._frames else self._frames[-1] if self._frames else np.zeros((540, 960, 3), np.uint8)
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
        loop = AdventureLoop(settings, engine, device)
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
    # m3-g6：商店事件未完成，全图无可走线 → 快照 + 停止，不点击任何东西
    loop, device, engine, saved, coords = adventure([_img("m3-g6.jpg")], [UIState.UNKNOWN])
    loop.run(max_nodes=3)
    assert device.taps == []
    assert saved == ["map_no_next"]
    assert engine.run_calls == []


def test_battle_takeover_runs_engine(adventure):
    # 主循环帧直接是战斗画面（进入战斗节点后）→ 引擎接管，不点任何东西
    loop, device, engine, _, coords = adventure(
        [_img("m3-g7.jpg")],
        [UIState.MULLIGAN, UIState.UNKNOWN],
    )
    loop.run(max_nodes=1)
    assert engine.run_calls == [400]  # settings.adventure.battle_max_ticks
    assert device.taps == []


def test_battle_end_taps_victory_continue(adventure):
    # 结算屏：点继续按钮，不触发引擎
    loop, device, engine, _, coords = adventure(
        [_img("m3-g6.jpg"), _img("m3-g6.jpg")],
        [UIState.BATTLE_END, UIState.UNKNOWN],
    )
    loop.run(max_nodes=2)
    vc = coords.victory_continue
    assert vc is not None
    assert device.taps[0] == tuple(vc.center)
    assert engine.run_calls == []


def test_node_panel_travel_first_option_leave(adventure):
    # 商店/休息面板：点节点 → 面板 → 旅行 → 非战斗 → 第一选项 → 离开
    loop, device, engine, saved, coords = adventure(
        [
            _img("m3-g7.jpg"),  # 地图：找下一节点
            _img("m3-g7.jpg"),  # 面板：UNKNOWN → tap travel
            _img("m3-g7.jpg"),  # 旅行后仍非战斗 → 第一选项 + 离开
            _img("m3-g6.jpg"),  # 回地图：无下一节点 → 停止
        ],
        [UIState.UNKNOWN, UIState.UNKNOWN, UIState.UNKNOWN, UIState.UNKNOWN],
    )
    loop.run(max_nodes=2)
    travel = coords.travel
    rest = coords.rest_first_option
    leave = coords.shop_leave
    assert device.taps == [
        (538 * 2, 177 * 2),  # 下一节点
        tuple(travel.center),
        tuple(rest.center),
        tuple(leave.center),
    ]
    assert engine.run_calls == []
    assert saved == ["map_no_next"]


def test_travel_into_battle_skips_shop_flow(adventure):
    # 旅行后直接进战斗：不再点第一选项/离开，引擎接管
    loop, device, engine, _, coords = adventure(
        [_img("m3-g7.jpg"), _img("m3-g7.jpg"), _img("m3-g7.jpg")],
        [UIState.UNKNOWN, UIState.UNKNOWN, UIState.MULLIGAN, UIState.MULLIGAN],
    )
    loop.run(max_nodes=2)
    assert engine.run_calls == [400]
    # 只有节点点击和旅行点击，没有 rest/shop 的点击
    assert len(device.taps) == 2
    assert tuple(coords.travel.center) in device.taps
