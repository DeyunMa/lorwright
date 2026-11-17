"""通过真实 CLI / Engine / AdventureLoop 验证重连恢复装配。"""

import json
from unittest.mock import Mock

import numpy as np
import pytest
from typer.testing import CliRunner

from lorwright.cli.app import app
from lorwright.core.config import Settings
from lorwright.core.device.base import Frame
from lorwright.core.loop import reconnect
from lorwright.core.loop.adventure import AdventureLoop
from lorwright.core.runtime.session import read_status


@pytest.mark.parametrize("mode", ["run", "adventure"])
def test_adb_cli_restarts_once_rebuilds_policy_and_closes_device(tmp_path, monkeypatch, mode):
    from lorwright.cli import app as cli

    settings = Settings()
    settings.loop.tick_ms = 0
    settings.logging.dir = str(tmp_path / "logs")
    monkeypatch.setenv("LORWRIGHT_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    device = Mock(name="synthetic")
    device.size.return_value = (1920, 1080)
    reconnecting = np.ones((1080, 1920, 3), np.uint8)
    after = np.zeros_like(reconnecting)
    device.screencap.side_effect = lambda: Frame(
        after if device.restart_app.called else reconnecting,
    )
    monkeypatch.setattr(cli, "_make_device", lambda name: device)
    detector = Mock()
    detector.detect.side_effect = lambda image: bool(image[0, 0, 0])
    monkeypatch.setattr(reconnect, "ReconnectDetector", lambda: detector)
    now = [0.0]
    monkeypatch.setattr(reconnect.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(reconnect, "_wait", lambda seconds: now.__setitem__(0, now[0] + seconds))
    monkeypatch.setattr(reconnect, "find_home_adventure_entry", lambda image: object())
    monkeypatch.setattr(AdventureLoop, "_wait", lambda *args, **kwargs: None)
    build_layers = Mock(wraps=cli._battle_layers)
    monkeypatch.setattr(cli, "_battle_layers", build_layers)
    budget = ["--max-ticks", "1"] if mode == "run" else ["--max-nodes", "1"]
    result = CliRunner().invoke(app, [mode, *budget, "--champion", "jinx",
                                     "--spell-already-played", "--jsonl"])
    assert result.exit_code == (0 if mode == "run" else 3), result.output
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert events[-1]["type"] == "session_finished"
    assert events[-1]["payload"]["reason"] == ("tick_limit" if mode == "run" else "unknown_scene")
    assert len([event for event in events if event["type"] == "client_restart_requested"]) == 1
    assert len([event for event in events if event["type"] == "client_restart_verified"]) == 1
    assert [call.kwargs["policy_kwargs"] for call in build_layers.call_args_list] == [
        {"spell_already_played": True}, None,
    ]
    assert read_status(tmp_path / "runs", events[0]["run_id"])["reason"] != "execution_error"
    assert now[0] == 300
    device.restart_app.assert_called_once_with(settings.adb.package)
    device.tap.assert_not_called()
    device.drag.assert_not_called()
    device.close.assert_called_once()
