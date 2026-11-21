"""共享重连页观察与单次客户端重启；调用者持有会话设备锁。"""

from __future__ import annotations

import time

import cv2
import numpy as np

from lorwright.core.loop.bootstrap import prepare_login
from lorwright.core.loop.outcome import LoopResult
from lorwright.core.models import UIState
from lorwright.core.perceive.adventure_scene import (
    find_home_adventure_entry,
    find_resume_adventure_button,
    is_map,
)
from lorwright.core.perceive.digits import DigitReader
from lorwright.core.perceive.login import LoginDetector, LoginScreen
from lorwright.core.perceive.normalize import Normalizer
from lorwright.core.perceive.reconnect import ReconnectDetector
from lorwright.core.perceive.ui_state import UIStateDetector, _is_isolated_blue_button
from lorwright.core.runtime.session import StopRequested, checkpoint, record_event, report
from lorwright.core.util.snapshot import save_snapshot


class ReconnectTimeout(Exception):
    """连续新鲜重连画面达到五分钟，退出旧交互栈后再恢复。"""

    def __init__(self, frame):
        super().__init__("reconnect_timeout")
        self.frame = frame


#: 连续卡死对战证据达到三分钟才重启客户端；对手正常回合不会静止这么久。
BATTLE_FROZEN_TIMEOUT_S = 180
#: 192×108 缩略帧与首个卡死帧的均差上限。实测同屏 1.6–4.5，
#: 重连浮层切换 11–22；取中间值，超出即视为画面已变化、重新计时。
BATTLE_FROZEN_STATIC_MAX_DIFF = 8.0
#: 对手优先权时动作按钮中心是暗色圆盘（实测均值 67）；亮于阈值不算卡死。
FROZEN_BUTTON_MAX_MEAN = 90


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
        self.normalizer = Normalizer((settings.screen.width, settings.screen.height))
        self.detector = ReconnectDetector()
        self.detector.load()
        self._layout = settings.layout.to_layout()
        self._ui = UIStateDetector(threshold=settings.perception.match_threshold,
                                   action_button=self._layout.end_turn)
        self._ui.load()
        self._digits = DigitReader()
        self._digits.load()

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
        if image is None:
            return frame
        if self.detector.detect(image):
            pass  # 完整重连页走下方既有 300s 等待
        elif self._frozen_kind(image) is not None:
            return self._wait_battle_frozen(frame, image)
        else:
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

    def _frozen_kind(self, image) -> str | None:
        """客户端卡死的对战证据："overlay"（对局内重连浮层）或
        "board"（UNKNOWN 的棋盘：双方水晶血量可读、动作按钮中心变暗
        且没有任何按钮文字/孤立蓝钮）。其余帧不参与卡死计时。"""
        if self.detector.detect_overlay(image):
            return "overlay"
        lay = self._layout
        if lay.end_turn is None or lay.enemy_hp is None or lay.my_hp is None:
            return None
        if self._ui.detect(image) is not UIState.UNKNOWN:
            return None
        if self._ui.action_prompt(image) is not None:
            return None
        if _is_isolated_blue_button(image, lay.end_turn):
            return None
        if (self._digits.read(image, lay.enemy_hp) is None
                or self._digits.read(image, lay.my_hp) is None):
            return None
        b = lay.end_turn
        patch = cv2.cvtColor(image[b.y:b.y + b.h, b.x:b.x + b.w], cv2.COLOR_BGR2GRAY)
        yy, xx = np.ogrid[:b.h, :b.w]
        centre = patch[(yy - b.h / 2) ** 2 + (xx - b.w / 2) ** 2 <= 40 ** 2]
        if centre.size == 0 or centre.mean() >= FROZEN_BUTTON_MAX_MEAN:
            return None
        return "board"

    def _wait_battle_frozen(self, frame, image):
        """卡死对战持续 180 秒（画面基本静止）则复用单次重启路径。"""
        started = time.monotonic()
        kind = self._frozen_kind(image)
        baseline = (_frozen_small(image) if kind == "board" else None)
        record_event("battle_frozen_detected", timeout_s=BATTLE_FROZEN_TIMEOUT_S)
        while True:
            checkpoint()
            elapsed = time.monotonic() - started
            if elapsed >= BATTLE_FROZEN_TIMEOUT_S:
                raise ReconnectTimeout(frame)
            report("waiting", "battle_frozen", wait_s=BATTLE_FROZEN_TIMEOUT_S - elapsed,
                   battle_frozen_elapsed_s=round(elapsed, 1))
            _wait(min(2, BATTLE_FROZEN_TIMEOUT_S - elapsed))
            frame = self.device.screencap()
            image = self.fresh_design(frame)
            if image is None:
                report("recognized", "battle_frozen_cleared", progress=False)
                return frame
            kind = self._frozen_kind(image)
            if kind is None:
                report("recognized", "battle_frozen_cleared", progress=True)
                return frame
            if kind == "board":
                small = _frozen_small(image)
                if baseline is None:
                    baseline = small
                elif float(np.abs(small - baseline).mean()) >= BATTLE_FROZEN_STATIC_MAX_DIFF:
                    report("recognized", "battle_frozen_cleared", progress=True)
                    return frame


def _frozen_small(image):
    return cv2.resize(image, (192, 108)).astype(np.int16)


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
                result = prepare_login(
                    settings, device, auto_login=auto_login, allow_restart=False,
                )
                if result.stop_reason:
                    return result.stop_reason
                # 表单消失只表示开始转场，继续用新帧核验已知游戏场景。
                continue
            battle_ui = ui.detect(image)
            battle_ready = (battle_ui is not UIState.UNKNOWN
                            and (battle_ui is not UIState.MY_TURN_IDLE
                                 or ui.action_prompt(image) is not None))
            if (find_home_adventure_entry(image) is not None
                    or find_resume_adventure_button(image) is not None
                    or is_map(image) or battle_ready):
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
            snapshot_path = str(path) if path is not None else None
            if restarted:
                reason = "reconnect_recovery_exhausted"
                report("stopped", reason, snapshot=snapshot_path)
                return LoopResult("stopped", reason)
            checkpoint()
            report("recovery", "reconnect_restart", snapshot=snapshot_path, attempt=1)
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
                report("stopped", reason, snapshot=str(path) if path is not None else None)
                return LoopResult("stopped", reason)
