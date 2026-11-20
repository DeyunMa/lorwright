"""Prepare the explicitly selected f1 Pie64 device inside an existing run session."""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass

from lorwright.core.device.adb import secret_text_supported
from lorwright.core.device.base import Frame
from lorwright.core.device.startup import PACKAGE
from lorwright.core.models import UIState
from lorwright.core.perceive.adventure_scene import (
    find_home_adventure_entry,
    find_resume_adventure_button,
    is_map,
)
from lorwright.core.perceive.login import LoginDetector, LoginScreen
from lorwright.core.perceive.normalize import Normalizer
from lorwright.core.perceive.ui_state import UIStateDetector
from lorwright.core.runtime.session import StopRequested, checkpoint, record_event, report
from lorwright.core.util import snapshot

LOGIN_FORM_WAIT_S = 30
LOGIN_RESTART_WAIT_S = 60


@dataclass(frozen=True)
class BootstrapResult:
    frame: Frame
    login_screen: LoginScreen
    transition_unverified: bool = False
    button_unverified: bool = False
    auto_login_stop: str | None = None

    @property
    def stop_reason(self) -> str | None:
        if self.auto_login_stop:
            return self.auto_login_stop
        if self.button_unverified:
            return "login_button_unverified"
        if self.transition_unverified:
            return "login_transition_unverified"
        if self.login_screen in (LoginScreen.SPLASH, LoginScreen.FORM):
            return "login_required"
        return None

    @property
    def login_required(self) -> bool:
        return self.stop_reason == "login_required"


def prepare_f1(
    settings, device, *, timeout_s: float = 120, poll_s: float = 2,
    open_riot_login: bool = False, auto_login: bool = False,
) -> BootstrapResult:
    """Start Pie64 if needed, launch LoR and return a fresh frame.

    Caller must hold the device session lock and close the device. This function
    only enters credentials when explicitly requested and the form is recognized.
    An unrecognized screen is passed to the adventure loop for further recognition.
    """
    if sys.platform != "win32":
        raise RuntimeError("f1 启动仅支持 Windows")
    if (settings.adb.serial != "127.0.0.1:5555" or
            settings.adb.launch_mode != "pie64_trace" or
            device.serial != settings.adb.serial or device.launch_mode != "pie64_trace" or
            settings.adb.package != PACKAGE):
        raise RuntimeError("f1 启动要求显式配置 Pie64 串口与 pie64_trace")
    if timeout_s <= 0 or poll_s <= 0:
        raise ValueError("等待时间必须大于零")

    def command(args, timeout=10):
        checkpoint()
        try:
            return subprocess.run(args, capture_output=True, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"启动命令执行失败：{args[0]}：{exc}") from exc

    def online():
        # Reconnect on each poll: the ADB daemon may precede the emulator.
        command([settings.adb.adb_path, "connect", settings.adb.serial])
        result = command([settings.adb.adb_path, "-s", settings.adb.serial, "get-state"])
        return result.returncode == 0 and result.stdout.strip() == b"device"

    report("bootstrap", "checking_adb", wait_s=timeout_s)
    if not online():
        task = ["schtasks", "/Query", "/TN", "F1StartPie64"]
        if command(task).returncode:
            raise RuntimeError("找不到或无法查询计划任务 F1StartPie64")
        report("bootstrap", "starting_emulator", wait_s=timeout_s)
        if command(["schtasks", "/Run", "/TN", "F1StartPie64"]).returncode:
            raise RuntimeError("无法启动计划任务 F1StartPie64")
        deadline = time.monotonic() + timeout_s
        report("bootstrap", "waiting_for_adb", wait_s=timeout_s)
        while True:
            checkpoint()
            if online():
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("等待 Pie64 ADB 在线超时")
            time.sleep(min(poll_s, remaining))

    report("bootstrap", "adb_ready", progress=True)
    deadline = time.monotonic() + timeout_s
    report("bootstrap", "waiting_android", wait_s=timeout_s)
    while True:
        boot = command([settings.adb.adb_path, "-s", settings.adb.serial, "shell", "getprop",
                        "sys.boot_completed"])
        if boot.returncode == 0 and boot.stdout.strip() == b"1":
            package = command([settings.adb.adb_path, "-s", settings.adb.serial,
                               "shell", "pm", "path", PACKAGE])
            if package.returncode == 0 and package.stdout.strip().startswith(b"package:"):
                break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("等待 Android 启动及游戏包就绪超时")
        checkpoint()
        time.sleep(min(poll_s, remaining))

    report("bootstrap", "android_ready", progress=True)
    report("bootstrap", "launching_game", wait_s=60)
    checkpoint()
    device.launch(settings.adb.package)
    checkpoint()
    if settings.adb.package not in device.current_focus():
        deadline = time.monotonic() + 10
        report("bootstrap", "waiting_game_foreground", wait_s=10)
        while True:
            checkpoint()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("未确认游戏位于前台")
            time.sleep(min(0.5, remaining))
            checkpoint()
            if settings.adb.package in device.current_focus():
                break
    return prepare_login(settings, device, open_riot_login=open_riot_login, auto_login=auto_login)


def prepare_login(settings, device, *, open_riot_login=False, auto_login=False,
                  allow_restart=True) -> BootstrapResult:
    """识别当前登录页，复用已授权的单次登录；不启动模拟器或游戏。"""
    checkpoint()
    frame = device.screencap()
    normalizer = Normalizer((settings.screen.width, settings.screen.height))
    image, scale = normalizer.fit(frame.image)
    detector = LoginDetector()
    detector.load()
    screen = detector.detect(image)
    transition_unverified = False
    if (open_riot_login or auto_login) and screen is LoginScreen.SPLASH:
        button = settings.layout.to_layout().login_splash
        if button is None:
            raise RuntimeError("缺少 Riot 登录方式按钮坐标")
        if not detector.riot_button_visible(image, button):
            report("bootstrap", "login_button_unverified", login_screen=screen.value)
            return BootstrapResult(frame=frame, login_screen=screen, button_unverified=True)
        checkpoint()
        if not frame.ts or frame.age_s() > settings.loop.max_frame_age_s:
            raise RuntimeError("登录方式画面已过期，未点击")
        report("bootstrap", "opening_riot_login")
        device.tap(*scale.to_device(*button.center))
        # Riot 登录网页在网络慢时会转圈十几秒；只等待，按钮不重复点击。
        started = time.monotonic()
        deadline = started + LOGIN_FORM_WAIT_S
        report("bootstrap", "waiting_login_form", wait_s=LOGIN_FORM_WAIT_S)
        seen = []
        first = None
        while True:
            checkpoint()
            frame = device.screencap()
            first = first or frame
            image, _ = normalizer.fit(frame.image)
            screen = detector.detect(image)
            if not seen or seen[-1][0] != screen.value:
                seen.append((screen.value, round(time.monotonic() - started, 1)))
            if screen is LoginScreen.FORM:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                transition_unverified = True
                break
            time.sleep(min(0.5, remaining))
        record_event("login_form_wait", screens=seen)
        if (transition_unverified and allow_restart
                and all(value == LoginScreen.SPLASH.value for value, _ in seen)):
            # 点击后始终停在登录方式页：上一会话中断的 Riot 网页登录会让按钮不再响应。
            # 重启 LoR 一次清掉挂起的登录流程，等登录方式页重新出现后再点一次。
            _save_frame(settings, frame, "login_tap_ignored")
            report("bootstrap", "login_restart", wait_s=LOGIN_RESTART_WAIT_S)
            record_event("client_restart_requested", reason="login_tap_ignored", attempt=1)
            device.restart_app(settings.adb.package)
            if _wait_for_splash(device, normalizer, detector):
                return prepare_login(settings, device, open_riot_login=open_riot_login,
                                     auto_login=auto_login, allow_restart=False)
            frame = device.screencap()
        if transition_unverified:
            # 只读诊断：点击后的首帧与末帧，便于区分点击未生效、网页失败返回等情况。
            _save_frame(settings, first, "login_transition_first")
            _save_frame(settings, frame, "login_transition_unverified")
    if auto_login and screen is LoginScreen.FORM and not transition_unverified:
        result = _auto_login(settings, device, frame, normalizer, detector)
        report("bootstrap", result.stop_reason or "screen_ready", progress=True,
               login_screen=result.login_screen.value)
        return result
    result = BootstrapResult(frame=frame, login_screen=screen,
                             transition_unverified=transition_unverified)
    report("bootstrap", result.stop_reason or "screen_ready", progress=not transition_unverified,
           login_screen=screen.value)
    return result


def _wait_for_splash(device, normalizer, detector) -> bool:
    deadline = time.monotonic() + LOGIN_RESTART_WAIT_S
    while time.monotonic() < deadline:
        checkpoint()
        time.sleep(1)
        image, _ = normalizer.fit(device.screencap().image)
        if detector.detect(image) is LoginScreen.SPLASH:
            return True
    return False


def _save_frame(settings, frame, tag):
    perception = getattr(settings, "perception", None)
    if frame is not None and perception is not None:
        snapshot.save_snapshot(frame.image, perception.snapshot_dir, tag=tag)


def _auto_login(settings, device, frame, normalizer, detector) -> BootstrapResult:
    """Keep device exceptions and their potentially sensitive tracebacks out of logs."""
    try:
        return _auto_login_impl(settings, device, frame, normalizer, detector)
    except StopRequested:
        raise
    except Exception:
        return BootstrapResult(frame, LoginScreen.FORM, auto_login_stop="login_input_failed")


def _auto_login_impl(settings, device, frame, normalizer, detector) -> BootstrapResult:
    """Submit at most once; never treat disappearance of the form as proof of login."""
    user, password = settings.lor_username, settings.lor_password
    if not user or not password:
        return BootstrapResult(frame, LoginScreen.FORM, auto_login_stop="login_credentials_missing")
    if not secret_text_supported(user) or not secret_text_supported(password):
        return BootstrapResult(frame, LoginScreen.FORM, auto_login_stop="login_credentials_unsupported")
    layout = settings.layout.to_layout()
    if not all((layout.login_username, layout.login_password, layout.login_submit)):
        return BootstrapResult(frame, LoginScreen.FORM, auto_login_stop="login_layout_missing")
    if not frame.ts or frame.age_s() > settings.loop.max_frame_age_s:
        return BootstrapResult(frame, LoginScreen.FORM, auto_login_stop="login_frame_stale")
    def verified_form():
        checkpoint()
        fresh = device.screencap()
        image, scale = normalizer.fit(fresh.image)
        if (not fresh.ts or fresh.age_s() > settings.loop.max_frame_age_s
                or detector.detect(image) is not LoginScreen.FORM):
            return None
        return scale

    report("bootstrap", "entering_login")
    try:
        for rect, value in ((layout.login_username, user), (layout.login_password, password)):
            scale = verified_form()
            if scale is None:
                return BootstrapResult(frame, LoginScreen.FORM, auto_login_stop="login_form_changed")
            checkpoint()
            device.tap(*scale.to_device(*rect.center))
            time.sleep(0.4)
            checkpoint()
            # 上次失败的登录会把内容留在表单里，先清空再输入，避免拼接出错误凭据。
            device.clear_text()
            checkpoint()
            device.text_secret(value)
            time.sleep(0.4)
        scale = verified_form()
        if scale is None:
            return BootstrapResult(frame, LoginScreen.FORM, auto_login_stop="login_form_changed")
        checkpoint()
        device.tap(*scale.to_device(*layout.login_submit.center))
    except StopRequested:
        raise
    except Exception:
        raise RuntimeError("自动登录输入失败") from None
    deadline = time.monotonic() + 30
    report("bootstrap", "waiting_login_transition", wait_s=30)
    ui = UIStateDetector(threshold=settings.perception.match_threshold, action_button=layout.end_turn)
    ui.load()
    while True:
        checkpoint()
        frame = device.screencap()
        image, _ = normalizer.fit(frame.image)
        screen = detector.detect(image)
        if frame.age_s() <= settings.loop.max_frame_age_s:
            if screen is LoginScreen.SPLASH and time.monotonic() < deadline:
                return BootstrapResult(frame, screen, auto_login_stop="login_required")
            if (screen is LoginScreen.NONE and _post_login_scene(image, ui)
                    and time.monotonic() < deadline):
                return BootstrapResult(frame, screen)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return BootstrapResult(frame, screen, auto_login_stop="login_transition_unverified")
        time.sleep(min(0.5, remaining))


def _post_login_scene(image, ui) -> bool:
    if find_home_adventure_entry(image) or find_resume_adventure_button(image) or is_map(image):
        return True
    battle_ui = ui.detect(image)
    if battle_ui is UIState.MY_TURN_IDLE:
        return ui.action_prompt(image) is not None
    return battle_ui is not UIState.UNKNOWN
