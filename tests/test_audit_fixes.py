from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from lorwright.core.act.translate import ActionTranslator
from lorwright.core.champions.jinx.vision import recognize_hero
from lorwright.core.decide.card import CardKind
from lorwright.core.decide.generic import AttackWhenTokenPolicy, plan_blocks
from lorwright.core.decide.rewards import CardRewardCandidate, RewardCandidate, pick_card_reward
from lorwright.core.device.adb import AdbRunner, AdbTimeout
from lorwright.core.loop.engine import Engine
from lorwright.core.models import (
    Action,
    ActionType,
    CardInHand,
    GameState,
    Layout,
    Reading,
    Rect,
    UIState,
    Unit,
)
from lorwright.core.perceive.locate import exists
from lorwright.core.runtime.session import RunSession

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools" / "f1"))
import remote as f1_remote  # noqa: E402
import sync as f1_sync  # noqa: E402


def test_engine_unit_card_does_not_use_spell_mana() -> None:
    card = CardInHand(
        index=0, name="Unit", rect=Rect(100, 900, 80, 120), cost=3,
        drag_point=(140, 960), drag_point_valid=True,
    )
    state = GameState(
        ui_state=UIState.MY_TURN_IDLE,
        mana=2,
        spell_mana=3,
        hand=[card],
        hand_expanded=True,
        readings={"mana": Reading(2, 0), "spell_mana": Reading(3, 0)},
    )
    unit_action = Action(type=ActionType.PLAY_CARD, card_index=0, raw={"unit_card": True})
    spell_action = Action(type=ActionType.PLAY_CARD, card_index=0, raw={})
    assert Engine._missing_action_evidence(unit_action, state) == ["affordable_cost"]
    assert Engine._missing_action_evidence(spell_action, state) == []


def test_stunned_unit_excluded_from_attack_evidence_policy_and_translator() -> None:
    stunned = Unit(name="S", rect=Rect(500, 820, 100, 140), attack=5, health=5, can_attack=True, stunned=True)
    state = GameState(ui_state=UIState.MY_TURN_IDLE, has_attack_token=True, my_units=[stunned])
    assert Engine._missing_action_evidence(Action(type=ActionType.ATTACK), state) == ["attack_priority"]
    assert AttackWhenTokenPolicy().decide(state) is None
    layout = Layout(end_turn=Rect(1700, 500, 100, 100), attack_row=Rect(800, 500, 200, 100))
    assert ActionTranslator(layout).translate(Action(type=ActionType.ATTACK), state) is None
    pass_plan = ActionTranslator(layout).translate(Action(type=ActionType.PASS), state)
    assert pass_plan is not None and pass_plan.points == [layout.end_turn.center]


def test_best_blocks_falls_back_to_greedy_when_my_unit_attack_unknown() -> None:
    my_unit = Unit(name="B", rect=Rect(500, 700, 100, 140), attack=-1, health=4)
    attacker = Unit(name="A", rect=Rect(500, 300, 100, 140), attack=3, health=3)
    pairs = plan_blocks([my_unit], [attacker])
    assert pairs == [(0, 0)]


def test_adb_runner_resets_connected_on_timeout_and_offline() -> None:
    runner = AdbRunner(serial="127.0.0.1:5555", timeout=1.0)
    runner._connected = True
    with patch("lorwright.core.device.adb.subprocess.run", side_effect=subprocess.TimeoutExpired("adb", 1.0)):
        with pytest.raises(AdbTimeout):
            runner.run("shell", "echo", "hi")
    assert runner._connected is False

    runner._connected = True
    fail_proc = subprocess.CompletedProcess(["adb"], 1, b"", b"error: device offline")
    with patch("lorwright.core.device.adb.subprocess.run", return_value=fail_proc):
        with pytest.raises(RuntimeError):
            runner.run("shell", "echo", "hi")
    assert runner._connected is False


def test_remote_wait_validates_run_id_and_sleeps_on_fast_failure() -> None:
    with pytest.raises(ValueError):
        f1_remote.status_body("bad; rm -rf /")

    now = [0.0]
    sleeps: list[float] = []

    def fake_clock() -> float:
        return now[0]

    def fake_sleep(sec: float) -> None:
        sleeps.append(sec)
        now[0] += sec

    fail_proc = subprocess.CompletedProcess(["ssh"], 255, "", "connection refused")
    with patch.object(f1_remote, "run_ps", return_value=fail_proc):
        code = f1_remote.wait("f1", "run-123", max_s=12.0, clock=fake_clock, sleeper=fake_sleep)
    assert code == 4
    assert sleeps == [5.0, 5.0, 2.0]


def test_sync_ssh_command_includes_keepalive() -> None:
    cmd = f1_sync.build_ssh_command("f1")
    assert "ServerAliveInterval=10" in cmd
    assert "ServerAliveCountMax=3" in cmd


def test_session_report_progress_clears_transient_diagnostic_keys(tmp_path: Path) -> None:
    with RunSession(tmp_path, mode="adventure", champion="jinx", device="adb", run_id="r-clean") as run:
        run.report("waiting", "missing", missing_readings=["mana"], recognition_diagnostic="old", error="boom")
        assert run._status["details"]["recognition_diagnostic"] == "old"
        run.report("recognized", "ok", progress=True, settlement_closed=True)
        details = run._status["details"]
        assert "missing_readings" not in details
        assert "recognition_diagnostic" not in details
        assert "error" not in details
        assert details["settlement_closed"] is True


def test_jinx_recognize_hero_handles_black_frame_without_crash() -> None:
    black = np.zeros((1080, 1920, 3), dtype=np.uint8)
    assert recognize_hero(black) is None


def test_locate_exists_fast_path() -> None:
    rng = np.random.default_rng(7)
    frame = rng.integers(0, 255, size=(120, 160, 3), dtype=np.uint8)
    tpl = frame[30:60, 40:80].copy()
    assert exists(frame, tpl, threshold=0.95) is True
    assert exists(frame, np.zeros((20, 20, 3), dtype=np.uint8)) is False
    assert exists(frame, np.zeros((200, 200, 3), dtype=np.uint8)) is False


def test_pick_card_reward_allows_preview_cost_verified_tie_break() -> None:
    c1 = CardRewardCandidate(
        card=RewardCandidate(name="A", quality="rare", cost=3),
        item_name="",
        kind=CardKind.UNIT,
        cost_certain=False,
        preview_cost_verified=True,
    )
    c2 = CardRewardCandidate(
        card=RewardCandidate(name="B", quality="rare", cost=1),
        item_name="",
        kind=CardKind.UNIT,
        cost_certain=False,
        preview_cost_verified=True,
    )
    pick = pick_card_reward([c1, c2])
    assert pick is not None and pick.candidate.card.name == "B"

    # Known cost-modifying item (item_name set, cost_certain=False) must still stay conservative.
    c3 = CardRewardCandidate(
        card=RewardCandidate(name="C", quality="rare", cost=1),
        item_name="光輝板甲",
        kind=CardKind.UNIT,
        cost_certain=False,
        preview_cost_verified=True,
    )
    assert pick_card_reward([c1, c3]) is None
