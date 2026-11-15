import time
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from typer.testing import CliRunner

from lorwright.cli.app import app
from lorwright.core.device.adb import AdbDevice
from lorwright.core.device.base import Frame
from lorwright.core.loop.bootstrap import _auto_login
from lorwright.core.perceive.login import LoginScreen
from lorwright.core.perceive.normalize import Normalizer
from lorwright.core.runtime.session import StopRequested


def setup_login():
    def rect(x):
        return SimpleNamespace(center=(x, 100))
    layout = SimpleNamespace(login_username=rect(100), login_password=rect(200),
                             login_submit=rect(300))
    settings = SimpleNamespace(lor_username="fake-user", lor_password="fake-pass",
                               layout=SimpleNamespace(to_layout=lambda: layout),
                               loop=SimpleNamespace(max_frame_age_s=5))
    frame = Frame(image=np.zeros((1080, 1920, 3), dtype=np.uint8),
                  ts=time.time(), capture_ms=0)
    device = Mock()
    device.screencap.return_value = frame
    detector = Mock()
    detector.detect.side_effect = [LoginScreen.FORM] * 3 + [LoginScreen.NONE]
    return settings, frame, device, detector, Normalizer((1920, 1080))


def test_single_submission_and_unrecognized_frame_handoff():
    settings, frame, device, detector, normalizer = setup_login()
    result = _auto_login(settings, device, frame, normalizer, detector)
    assert result.stop_reason is None
    assert result.login_screen is LoginScreen.NONE
    assert [c.args[0] for c in device.text_secret.call_args_list] == ["fake-user", "fake-pass"]
    assert device.tap.call_count == 3


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


def test_form_timeout_does_not_retry(monkeypatch):
    settings, frame, device, detector, normalizer = setup_login()
    detector.detect.side_effect = None
    detector.detect.return_value = LoginScreen.FORM
    ticks = iter([0, 31])
    monkeypatch.setattr("lorwright.core.loop.bootstrap.time.monotonic", lambda: next(ticks))
    assert _auto_login(settings, device, frame, normalizer, detector).stop_reason == "login_transition_unverified"
    assert device.tap.call_count == 3
    assert device.text_secret.call_count == 2


def test_cli_requires_bootstrap(tmp_path, monkeypatch):
    monkeypatch.setenv("LORWRIGHT_RUNS_DIR", str(tmp_path))
    result = CliRunner().invoke(app, ["adventure", "--auto-login", "--jsonl"])
    assert result.exit_code == 1
    assert "--auto-login" in result.stdout
    result = CliRunner().invoke(app, ["sessions", "start", "--auto-login"])
    assert result.exit_code != 0
