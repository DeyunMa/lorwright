"""共享重连页观察与单次客户端重启；调用者持有会话设备锁。"""

from __future__ import annotations

import time

from lorwright.core.loop.bootstrap import prepare_login
from lorwright.core.loop.outcome import LoopResult
from lorwright.core.models import UIState
from lorwright.core.perceive.adventure_scene import find_home_adventure_entry, is_map
from lorwright.core.perceive.login import LoginDetector, LoginScreen
from lorwright.core.perceive.normalize import Normalizer
from lorwright.core.perceive.reconnect import ReconnectDetector
from lorwright.core.perceive.ui_state import UIStateDetector
from lorwright.core.runtime.session import StopRequested, checkpoint, record_event, report
from lorwright.core.util.snapshot import save_snapshot


class ReconnectTimeout(Exception):
    """连续新鲜重连画面达到五分钟，退出旧交互栈后再恢复。"""

    def __init__(self, frame):
        super().__init__("reconnect_timeout")
        self.frame = frame


def _wait(seconds):
    deadline = time.monotonic() + seconds
    while True:
        checkpoint()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.1, remaining))


class _ReconnectCapture:
    def __init__(self, settings, device):
        self.settings = settings
        self.device = device
        self.normalizer = Normalizer((1920, 1080))
        self.detector = ReconnectDetector()
        self.detector.load()

    def fresh_design(self, frame):
        if frame.age_s() > self.settings.loop.max_frame_age_s:
            return None
        height, width = frame.image.shape[:2]
        if not height or abs(width / height - 16 / 9) > 0.02:
            return None
        return self.normalizer.fit(frame.image)[0]

    def __call__(self):
        checkpoint()
        frame = self.device.screencap()
        image = self.fresh_design(frame)
        if image is None or not self.detector.detect(image):
            return frame
        started = time.monotonic()
        record_event("reconnect_detected", timeout_s=300)
        while True:
            checkpoint()
            elapsed = time.monotonic() - started
            if elapsed >= 300:
                raise ReconnectTimeout(frame)
            report("waiting", "game_reconnecting", wait_s=300 - elapsed,
                   reconnect_elapsed_s=round(elapsed, 1))
            _wait(min(2, 300 - elapsed))
            frame = self.device.screencap()
            image = self.fresh_design(frame)
            # 失去明确或新鲜证据即终止本段连续计时，由原循环处理该帧。
            if image is None or not self.detector.detect(image):
                report("recognized", "reconnect_cleared", progress=image is not None)
                return frame


def _wait_after_restart(settings, device, capture, *, auto_login):
    login = LoginDetector()
    login.load()
    ui = UIStateDetector(threshold=settings.perception.match_threshold,
                         action_button=settings.layout.to_layout().end_turn)
    ui.load()
    deadline = time.monotonic() + 120
    login_attempted = False
    while True:
        checkpoint()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return "reconnect_restart_unverified"
        report("waiting", "reconnect_restart_transition", wait_s=remaining)
        frame = device.screencap()
        image = capture.fresh_design(frame)
        if time.monotonic() >= deadline:
            return "reconnect_restart_unverified"
        if image is not None and not capture.detector.detect(image):
            if login.detect(image) is not LoginScreen.NONE:
                if login_attempted:
                    return "login_required"
                login_attempted = True
                result = prepare_login(settings, device, auto_login=auto_login)
                if result.stop_reason:
                    return result.stop_reason
                # 表单消失只表示开始转场，继续用新帧核验已知游戏场景。
                continue
            battle_ui = ui.detect(image)
            battle_ready = (battle_ui is not UIState.UNKNOWN
                            and (battle_ui is not UIState.MY_TURN_IDLE
                                 or ui.action_prompt(image) is not None))
            if (find_home_adventure_entry(image) is not None or is_map(image) or battle_ready):
                report("verified", "reconnect_restart_verified", progress=True)
                record_event("client_restart_verified")
                return None
        _wait(min(2, max(0, deadline - time.monotonic())))


def run_with_reconnect_recovery(settings, device, run_loop, *, auto_login=False):
    """run_loop(capture, restarted) 每次新建循环；整个会话最多重启一次 LoR。"""
    capture = _ReconnectCapture(settings, device)
    restarted = False
    while True:
        try:
            return run_loop(capture, restarted)
        except ReconnectTimeout as exc:
            path = save_snapshot(exc.frame.image, settings.perception.snapshot_dir,
                                 tag="reconnect_timeout")
            if restarted:
                reason = "reconnect_recovery_exhausted"
                report("stopped", reason, snapshot=str(path))
                return LoopResult("stopped", reason)
            checkpoint()
            report("recovery", "reconnect_restart", snapshot=str(path), attempt=1)
            record_event("client_restart_requested", reason="reconnect_timeout", attempt=1)
            restarted = True
            try:
                device.restart_app(settings.adb.package)
            except StopRequested:
                raise
            except Exception as restart_error:
                report("stopped", "reconnect_restart_failed",
                       error_type=type(restart_error).__name__)
                return LoopResult("stopped", "reconnect_restart_failed")
            reason = _wait_after_restart(settings, device, capture, auto_login=auto_login)
            if reason:
                checkpoint()
                frame = device.screencap()
                path = save_snapshot(frame.image, settings.perception.snapshot_dir, tag=reason)
                report("stopped", reason, snapshot=str(path))
                return LoopResult("stopped", reason)
