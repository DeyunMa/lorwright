from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from lorwright.core.device.base import Frame
from lorwright.core.loop import bootstrap
from lorwright.core.perceive.login import LoginScreen
from lorwright.core.runtime.session import StopRequested


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(bootstrap.sys, "platform", "win32")
    settings = SimpleNamespace(
        adb=SimpleNamespace(serial="127.0.0.1:5555", launch_mode="pie64_trace",
                            adb_path="adb", package="com.riotgames.legendsofruneterra"),
        screen=SimpleNamespace(width=1920, height=1080),
    )
    device = Mock(serial=settings.adb.serial, launch_mode="pie64_trace")
    device.current_focus.return_value = settings.adb.package
    device.screencap.return_value = Frame(image=np.zeros((1080, 1920, 3), dtype=np.uint8),
                                          ts=0, capture_ms=0)
    detector = Mock()
    detector.detect.return_value = LoginScreen.NONE
    detector.riot_button_visible.return_value = True
    monkeypatch.setattr(bootstrap, "LoginDetector", lambda: detector)
    def response(args, **kwargs):
        if args[-2:] == ["getprop", "sys.boot_completed"]:
            return SimpleNamespace(returncode=0, stdout=b"1\n")
        if "pm" in args:
            return SimpleNamespace(returncode=0, stdout=b"package:/installed/base.apk\n")
        return SimpleNamespace(returncode=0, stdout=b"device\n")

    run = Mock(side_effect=response)
    monkeypatch.setattr(bootstrap.subprocess, "run", run)
    return settings, device, detector, run


def test_existing_device_and_login(setup):
    settings, device, detector, run = setup
    detector.detect.return_value = LoginScreen.SPLASH
    result = bootstrap.prepare_f1(settings, device)
    assert result.login_required and result.frame is device.screencap.return_value
    device.launch.assert_called_once_with(settings.adb.package)
    assert all("schtasks" not in call.args[0] for call in run.call_args_list)


def test_riot_login_selection_is_once_and_stops_at_form(setup, monkeypatch):
    settings, device, detector, _ = setup
    settings.layout = SimpleNamespace(
        to_layout=lambda: SimpleNamespace(login_splash=SimpleNamespace(center=(720, 835)))
    )
    settings.loop = SimpleNamespace(max_frame_age_s=2)
    monkeypatch.setattr(bootstrap.time, "monotonic", lambda: 100.0)
    device.screencap.return_value.ts = 100.0
    detector.detect.side_effect = [LoginScreen.SPLASH, LoginScreen.FORM]
    result = bootstrap.prepare_f1(settings, device, open_riot_login=True)
    device.tap.assert_called_once_with(720, 835)
    assert result.stop_reason == "login_required"
    assert result.login_screen is LoginScreen.FORM
    device.text.assert_not_called()


def test_auto_login_from_form_calls_once(setup, monkeypatch):
    settings, device, detector, _ = setup
    detector.detect.return_value = LoginScreen.FORM
    expected = bootstrap.BootstrapResult(device.screencap.return_value, LoginScreen.NONE)
    login = Mock(return_value=expected)
    monkeypatch.setattr(bootstrap, "_auto_login", login)
    assert bootstrap.prepare_f1(settings, device, auto_login=True) is expected
    login.assert_called_once()


def test_auto_login_unknown_screen_does_not_enter_credentials(setup, monkeypatch):
    settings, device, detector, _ = setup
    login = Mock()
    monkeypatch.setattr(bootstrap, "_auto_login", login)
    assert bootstrap.prepare_f1(settings, device, auto_login=True).login_screen is LoginScreen.NONE
    login.assert_not_called()
    device.text.assert_not_called()


def test_riot_login_unverified_transition_does_not_start_adventure(setup, monkeypatch):
    settings, device, detector, _ = setup
    settings.layout = SimpleNamespace(
        to_layout=lambda: SimpleNamespace(login_splash=SimpleNamespace(center=(720, 835)))
    )
    settings.loop = SimpleNamespace(max_frame_age_s=2)
    device.screencap.return_value.ts = 10.0
    detector.detect.side_effect = [LoginScreen.SPLASH, LoginScreen.NONE]
    end = 10.0 + bootstrap.LOGIN_FORM_WAIT_S + 1
    moments = iter([10.0, 10.0, 10.0, end])
    monkeypatch.setattr(bootstrap.time, "monotonic", lambda: next(moments, end))
    events, saved = [], []
    monkeypatch.setattr(bootstrap, "record_event", lambda name, **payload: events.append((name, payload)))
    monkeypatch.setattr(bootstrap.snapshot, "save_snapshot", lambda image, out_dir, tag: saved.append(tag))
    settings.perception = SimpleNamespace(snapshot_dir="/tmp/unused")
    result = bootstrap.prepare_f1(settings, device, open_riot_login=True)
    assert result.stop_reason == "login_transition_unverified"
    device.tap.assert_called_once()
    assert [name for name, _ in events] == ["login_form_wait"]
    assert [screen for screen, _ in events[0][1]["screens"]] == ["none"]
    assert saved == ["login_transition_first", "login_transition_unverified"]


def test_riot_login_waits_for_slow_form(setup, monkeypatch):
    # 20261120T063459：重启后点 Riot 登录，网页转圈 11 秒仍未出表单；时序为合成。
    settings, device, detector, _ = setup
    settings.layout = SimpleNamespace(
        to_layout=lambda: SimpleNamespace(login_splash=SimpleNamespace(center=(720, 835)))
    )
    settings.loop = SimpleNamespace(max_frame_age_s=2)
    device.screencap.return_value.ts = 10.0
    detector.detect.side_effect = [LoginScreen.SPLASH, LoginScreen.NONE, LoginScreen.FORM]
    moments = iter([10.0, 10.0, 10.0, 10.0, 25.0, 25.0, 30.0])
    monkeypatch.setattr(bootstrap.time, "monotonic", lambda: next(moments, 30.0))
    monkeypatch.setattr(bootstrap.time, "sleep", lambda _: None)
    result = bootstrap.prepare_f1(settings, device, open_riot_login=True)
    assert result.stop_reason == "login_required"
    assert result.login_screen is LoginScreen.FORM
    device.tap.assert_called_once()


def _splash_login(setup, monkeypatch, screens):
    settings, device, detector, _ = setup
    settings.layout = SimpleNamespace(
        to_layout=lambda: SimpleNamespace(login_splash=SimpleNamespace(center=(720, 835)))
    )
    settings.loop = SimpleNamespace(max_frame_age_s=2)
    clock = [10.0]
    device.screencap.return_value.ts = clock[0]
    detector.detect.side_effect = screens

    def sleep(seconds):
        clock[0] += max(seconds, 0.5)
        device.screencap.return_value.ts = clock[0]

    monkeypatch.setattr(bootstrap.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(bootstrap.time, "sleep", sleep)
    return settings, device


def test_ignored_riot_tap_restarts_lor_once_and_retries(setup, monkeypatch):
    # 20261120T065911：点击后 30 秒内一直是登录方式页（首末帧均为 splash）。重启后的表单为合成。
    waits = int(bootstrap.LOGIN_FORM_WAIT_S / 0.5) + 2
    screens = [LoginScreen.SPLASH] * (1 + waits) + [LoginScreen.SPLASH, LoginScreen.SPLASH,
                                                     LoginScreen.FORM]
    settings, device = _splash_login(setup, monkeypatch, screens)
    result = bootstrap.prepare_f1(settings, device, open_riot_login=True)
    device.restart_app.assert_called_once_with(settings.adb.package)
    assert device.tap.call_count == 2
    assert result.stop_reason == "login_required"


def test_ignored_riot_tap_after_restart_stops_without_second_restart(setup, monkeypatch):
    settings, device = _splash_login(setup, monkeypatch, lambda image: LoginScreen.SPLASH)
    result = bootstrap.prepare_f1(settings, device, open_riot_login=True)
    device.restart_app.assert_called_once()
    assert device.tap.call_count == 2
    assert result.stop_reason == "login_transition_unverified"


def test_riot_login_missing_button_is_not_clicked(setup):
    settings, device, detector, _ = setup
    settings.layout = SimpleNamespace(
        to_layout=lambda: SimpleNamespace(login_splash=SimpleNamespace(center=(720, 835)))
    )
    detector.detect.return_value = LoginScreen.SPLASH
    detector.riot_button_visible.return_value = False
    result = bootstrap.prepare_f1(settings, device, open_riot_login=True)
    assert result.stop_reason == "login_button_unverified"
    device.tap.assert_not_called()


def test_riot_login_stale_frame_is_not_clicked(setup):
    settings, device, detector, _ = setup
    settings.layout = SimpleNamespace(
        to_layout=lambda: SimpleNamespace(login_splash=SimpleNamespace(center=(720, 835)))
    )
    settings.loop = SimpleNamespace(max_frame_age_s=2)
    detector.detect.return_value = LoginScreen.SPLASH
    with pytest.raises(RuntimeError, match="画面已过期"):
        bootstrap.prepare_f1(settings, device, open_riot_login=True)
    device.tap.assert_not_called()


def test_starts_task_when_offline(setup):
    settings, device, _, run = setup
    offline = SimpleNamespace(returncode=1, stdout=b"")
    ok = SimpleNamespace(returncode=0, stdout=b"device\n")
    boot = SimpleNamespace(returncode=0, stdout=b"1\n")
    package = SimpleNamespace(returncode=0, stdout=b"package:/installed/base.apk\n")
    run.side_effect = [ok, offline, ok, ok, ok, ok, boot, package]
    result = bootstrap.prepare_f1(settings, device)
    assert not result.login_required
    assert ["schtasks", "/Run", "/TN", "F1StartPie64"] in [c.args[0] for c in run.call_args_list]


def test_task_failure_is_reported(setup):
    settings, _, _, run = setup
    ok = SimpleNamespace(returncode=0, stdout=b"")
    bad = SimpleNamespace(returncode=1, stdout=b"")
    run.side_effect = [ok, bad, bad]
    with pytest.raises(RuntimeError, match="计划任务"):
        bootstrap.prepare_f1(settings, setup[1])


def test_timeout_and_stop(setup, monkeypatch):
    settings, device, _, run = setup
    run.side_effect = None
    run.return_value = SimpleNamespace(returncode=0, stdout=b"offline")
    times = iter([0, 2])
    monkeypatch.setattr(bootstrap.time, "monotonic", lambda: next(times))
    with pytest.raises(RuntimeError, match="超时"):
        bootstrap.prepare_f1(settings, device, timeout_s=1)
    monkeypatch.setattr(bootstrap, "checkpoint", Mock(side_effect=StopRequested()))
    with pytest.raises(StopRequested):
        bootstrap.prepare_f1(settings, device)
    device.launch.assert_not_called()


def test_waits_for_android_and_package_after_adb_online(setup, monkeypatch):
    settings, device, _, run = setup
    run.side_effect = [
        SimpleNamespace(returncode=0, stdout=b"connected"),
        SimpleNamespace(returncode=0, stdout=b"device"),
        SimpleNamespace(returncode=0, stdout=b"0"),
        SimpleNamespace(returncode=0, stdout=b"1"),
        SimpleNamespace(returncode=1, stdout=b""),
        SimpleNamespace(returncode=0, stdout=b"1"),
        SimpleNamespace(returncode=0, stdout=b"package:/installed/base.apk"),
    ]
    monkeypatch.setattr(bootstrap.time, "sleep", lambda _: None)
    bootstrap.prepare_f1(settings, device)
    device.launch.assert_called_once_with(settings.adb.package)
    assert all("schtasks" not in call.args[0] for call in run.call_args_list)


def test_waits_for_game_to_reach_foreground(setup, monkeypatch):
    settings, device, _, _ = setup
    device.current_focus.side_effect = ["", settings.adb.package]
    monkeypatch.setattr(bootstrap.time, "sleep", lambda _: None)
    bootstrap.prepare_f1(settings, device)
    assert device.current_focus.call_count == 2
    device.screencap.assert_called_once()


def test_requires_matching_device_and_foreground(setup, monkeypatch):
    settings, device, _, _ = setup
    device.serial = "another"
    with pytest.raises(RuntimeError, match="串口"):
        bootstrap.prepare_f1(settings, device)
    device.serial = settings.adb.serial
    device.current_focus.return_value = "other.app"
    moments = iter([0, 0, 11])
    monkeypatch.setattr(bootstrap.time, "monotonic", lambda: next(moments))
    with pytest.raises(RuntimeError, match="前台"):
        bootstrap.prepare_f1(settings, device)
    device.screencap.assert_not_called()
