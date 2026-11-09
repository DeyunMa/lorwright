"""Exercise startup guards, already-running behavior and profiler cleanup."""
from __future__ import annotations

import pytest

from lorwright.device.adb import AdbDevice
from lorwright.device.startup import PACKAGE, launch_pie64


class Runner:
    def __init__(self, *, existing=False, crash=False, stop_error=False, start_error=False):
        self.calls = []
        self.running = existing
        self.crash = crash
        self.stop_error = stop_error
        self.start_error = start_error

    def run(self, *args, binary=False):
        self.calls.append(args)
        if args[:2] == ("shell", "getprop"):
            return "9" if args[2] == "ro.build.version.release" else "1"
        if args[:3] == ("shell", "dumpsys", "package"):
            return "    versionName=07.11.015\n"
        if args == ("shell", f"pidof {PACKAGE}; true"):
            return "1234" if self.running else ""
        if args[:3] == ("shell", "am", "start"):
            if self.start_error:
                raise RuntimeError("ADB transport failed")
            self.running = not self.crash
            return "Starting: Intent"
        if args[:4] == ("shell", "am", "profile", "stop") and self.stop_error:
            raise RuntimeError("ADB transport failed")
        if args[:3] == ("shell", "dumpsys", "window"):
            return f"mCurrentFocus=Window{{{PACKAGE}/.LoRActivity}}"
        return ""


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr("lorwright.device.startup.time.sleep", lambda _: None)


def test_trace_stops_before_post_start_verification():
    runner = Runner()
    launch_pie64(runner, PACKAGE)
    starts = [call for call in runner.calls if "--start-profiler" in call]
    assert len(starts) == 1 and "--streaming" in starts[0]
    stop = ("shell", "am", "profile", "stop", PACKAGE)
    focus = ("shell", "dumpsys", "window", "windows")
    assert runner.calls.index(stop) < runner.calls.index(focus)
    assert runner.calls[-1][:2] == ("shell", "rm")
    assert runner.calls[-1][2] == starts[0][4]


def test_existing_game_only_resumes_without_trace_or_force_stop():
    runner = Runner(existing=True)
    launch_pie64(runner, PACKAGE)
    assert runner.calls[-1] == ("shell", "am", "start", "-n", PACKAGE + "/.LoRActivity")
    assert not any("--start-profiler" in call or "force-stop" in call for call in runner.calls)


@pytest.mark.parametrize("failure", ["crash", "start_error", "stop_error"])
def test_failure_attempts_profiler_cleanup_and_retains_trace(failure):
    runner = Runner(**{failure: True})
    with pytest.raises(RuntimeError):
        launch_pie64(runner, PACKAGE)
    assert ("shell", "am", "profile", "stop", PACKAGE) in runner.calls
    assert not any(call[:2] == ("shell", "rm") for call in runner.calls)


def test_wrong_package_never_contacts_device():
    runner = Runner()
    with pytest.raises(RuntimeError):
        launch_pie64(runner, "another.package")
    assert runner.calls == []


def test_wrong_android_does_not_start_or_change_properties(monkeypatch):
    runner = Runner()
    monkeypatch.setattr(runner, "run", lambda *args: "11")
    with pytest.raises(RuntimeError, match="ro.build.version.release"):
        launch_pie64(runner, PACKAGE)


def test_standard_device_launch_remains_standard(monkeypatch):
    runner = Runner()
    device = AdbDevice(serial="phone")
    monkeypatch.setattr(device, "_adb", runner)
    device.launch(PACKAGE)
    assert runner.calls == [(
        "shell", "monkey", "-p", PACKAGE,
        "-c", "android.intent.category.LAUNCHER", "1",
    )]


def test_device_trace_mode_uses_shared_workflow(monkeypatch):
    calls = []
    monkeypatch.setattr("lorwright.device.startup.launch_pie64", lambda *args: calls.append(args))
    device = AdbDevice(serial="127.0.0.1:5555", launch_mode="pie64_trace")
    device.launch(PACKAGE)
    assert calls == [(device._adb, PACKAGE)]
