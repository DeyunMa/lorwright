import time
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest
from typer.testing import CliRunner

from lorwright.cli.app import app
from lorwright.core.config import load_settings
from lorwright.core.device.adb import AdbDevice
from lorwright.core.device.base import Frame
from lorwright.core.loop.bootstrap import _auto_login
from lorwright.core.perceive.login import LoginScreen
from lorwright.core.perceive.normalize import Normalizer
from lorwright.core.runtime.session import StopRequested
from tools.test_data import fixtures_root


def setup_login():
    def rect(x):
        return SimpleNamespace(center=(x, 100))
    defaults = load_settings()
    layout = SimpleNamespace(login_username=rect(100), login_password=rect(200),
                             login_submit=rect(300), end_turn=defaults.layout.to_layout().end_turn)
    settings = SimpleNamespace(lor_username="fake-user", lor_password="fake-pass",
                               layout=SimpleNamespace(to_layout=lambda: layout),
                               loop=SimpleNamespace(max_frame_age_s=5),
                               perception=defaults.perception, logging=defaults.logging)
    frame = Frame(image=np.zeros((1080, 1920, 3), dtype=np.uint8),
                  ts=time.monotonic(), capture_ms=0)
    device = Mock()
    device.screencap.return_value = frame
    detector = Mock()
    detector.detect.side_effect = [LoginScreen.FORM] * 3 + [LoginScreen.NONE]
    return settings, frame, device, detector, Normalizer((1920, 1080))


def test_single_submission_waits_through_loading_until_home(monkeypatch):
    settings, frame, device, detector, normalizer = setup_login()
    home = cv2.imread(str(fixtures_root() / "screens/1080p_home_adventure_entry.png"))
    assert home is not None
    loading = Frame(np.full_like(frame.image, 247), time.monotonic(), 0)
    ready = Frame(home, time.monotonic(), 0)
    device.screencap.side_effect = [frame] * 3 + [loading, ready]
    detector.detect.side_effect = [LoginScreen.FORM] * 3 + [LoginScreen.NONE] * 2
    monkeypatch.setattr("lorwright.core.loop.bootstrap.time.sleep", lambda _: None)
    result = _auto_login(settings, device, frame, normalizer, detector)
    assert result.stop_reason is None
    assert result.login_screen is LoginScreen.NONE
    assert result.frame is ready
    assert [c.args[0] for c in device.text_secret.call_args_list] == ["fake-user", "fake-pass"]
    assert device.tap.call_count == 3
    # 20261120T073940 失败后表单仍保留账号和密码；每个输入框先清空再输入。
    calls = [c[0] for c in device.method_calls if c[0] in ("tap", "clear_text", "text_secret")]
    assert calls == ["tap", "clear_text", "text_secret", "tap", "clear_text", "text_secret", "tap"]


def test_missing_or_unsupported_credentials_stop_without_input():
    settings, frame, device, detector, normalizer = setup_login()
    settings.lor_password = None
    assert _auto_login(settings, device, frame, normalizer, detector).stop_reason == "login_credentials_missing"
    settings.lor_password = "unsupported%fake"
    assert _auto_login(settings, device, frame, normalizer, detector).stop_reason == "login_credentials_unsupported"
    device.tap.assert_not_called()


def test_secret_text_is_sent_via_stdin_not_host_arguments():
    device = AdbDevice(serial="test", adb="adb")
    device._adb = Mock()
    device.text_secret("fake-pass")
    device._adb.run.assert_called_once_with("shell", "sh", stdin=b"input text fake-pass\n")
    device.text_secret("fake;$(no-execution)")
    assert device._adb.run.call_args.kwargs["stdin"] == b"input text 'fake;$(no-execution)'\n"
    with pytest.raises(ValueError):
        device.text_secret("unsupported%fake")
    assert device._adb.run.call_count == 2


def test_clear_text_moves_to_end_then_deletes_in_one_call():
    device = AdbDevice(serial="test", adb="adb")
    device._adb = Mock()
    device.clear_text(3)
    device._adb.run.assert_called_once_with("shell", "input", "keyevent", "123", "67", "67", "67", binary=False)


def test_form_change_prevents_password_input():
    settings, frame, device, detector, normalizer = setup_login()
    detector.detect.side_effect = [LoginScreen.FORM, LoginScreen.NONE]
    result = _auto_login(settings, device, frame, normalizer, detector)
    assert result.stop_reason == "login_form_changed"
    assert device.text_secret.call_count == 1
    assert device.tap.call_count == 1


def test_input_failure_hides_credentials():
    settings, frame, device, detector, normalizer = setup_login()
    device.text_secret.side_effect = RuntimeError("fake-user fake-pass")
    result = _auto_login(settings, device, frame, normalizer, detector)
    assert result.stop_reason == "login_input_failed"
    assert "fake-pass" not in repr(result)


def test_stop_before_input(monkeypatch):
    settings, frame, device, detector, normalizer = setup_login()
    def stop():
        raise StopRequested()
    monkeypatch.setattr("lorwright.core.loop.bootstrap.checkpoint", stop)
    with pytest.raises(StopRequested):
        _auto_login(settings, device, frame, normalizer, detector)
    device.tap.assert_not_called()


@pytest.mark.parametrize("after_submit", [LoginScreen.FORM, LoginScreen.NONE])
def test_login_timeout_does_not_retry(monkeypatch, after_submit):
    settings, frame, device, detector, normalizer = setup_login()
    frame.ts = 10.0
    post_frame = Frame(image=frame.image, ts=40.5, capture_ms=0)
    device.screencap.side_effect = [frame, frame, frame, post_frame]
    detector.detect.side_effect = [LoginScreen.FORM] * 3 + [after_submit]
    monkeypatch.setattr("lorwright.core.loop.bootstrap.time.sleep", lambda _: None)
    ticks = iter([10.0, 10.0, 10.0, 10.0, 10.0, 41.0, 41.0])
    monkeypatch.setattr("lorwright.core.loop.bootstrap.time.monotonic", lambda: next(ticks))
    assert _auto_login(settings, device, frame, normalizer, detector).stop_reason == "login_transition_unverified"
    assert device.tap.call_count == 3
    assert device.text_secret.call_count == 2


@pytest.mark.parametrize("failure", [False, True])
def test_legacy_adb_login_keeps_credentials_out_of_arguments_and_errors(tmp_path, monkeypatch, failure):
    settings, _, device, detector, _ = setup_login()
    settings.logging.dir = str(tmp_path)
    settings.layout.to_layout().login_splash = SimpleNamespace(center=(40, 100))
    monkeypatch.setattr("lorwright.cli.app.load_settings", lambda: settings)
    monkeypatch.setattr("lorwright.cli.app._make_device", lambda _: device)
    monkeypatch.setattr("lorwright.cli.app.time.sleep", lambda _: None)
    monkeypatch.setattr("lorwright.core.perceive.login.LoginDetector", lambda: detector)
    if failure:
        device.text_secret.side_effect = RuntimeError("fake-user fake-pass")

    result = CliRunner().invoke(app, ["login", "--tries", "1"])

    device.text.assert_not_called()
    device.close.assert_called_once()
    assert "fake-user" not in result.output and "fake-pass" not in result.output
    if failure:
        assert result.exit_code == 1
        assert device.tap.call_count == 1
    else:
        assert result.exit_code == 0
        assert [call.args[0] for call in device.text_secret.call_args_list] == ["fake-user", "fake-pass"]
        assert device.tap.call_count == 3


def test_cli_requires_bootstrap(tmp_path, monkeypatch):
    monkeypatch.setenv("LORWRIGHT_RUNS_DIR", str(tmp_path))
    result = CliRunner().invoke(app, ["adventure", "--auto-login", "--jsonl"])
    assert result.exit_code == 1
    assert "--auto-login" in result.stdout
    result = CliRunner().invoke(app, ["sessions", "start", "--auto-login"])
    assert result.exit_code != 0
