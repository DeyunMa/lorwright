"""本地会话、事件及协作停止；心跳不代表游戏取得进展。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path

TERMINAL = frozenset({"stopped", "cancelled", "failed", "completed"})
_active: ContextVar[RunSession | None] = ContextVar("run_session", default=None)


class StopRequested(Exception):
    """调用方在安全点观察到停止请求。"""


def describe_status(phase: str, reason: str | None, details: dict) -> str:
    """可读说明与稳定的阶段、原因代码并存，不参与游戏决策。"""
    reasons = {
        "unknown_ui": "当前界面无法识别，等待新画面；到期仍未知则保存截图并停止",
        "unknown_target": "目标要求无法确认，等待重新识别；到期停止",
        "action_preconditions_unverified": "当前动作缺少必要证据："
            + ", ".join(details.get("missing_readings", [])),
        "action_readiness_unverified": "当前动作的相关证据尚未连续两帧稳定，继续采图；到期保存截图并停止",
        "battle_result_transition": "已识别结算转场背景，只读等待明确结果，最多六十秒",
        "battle_result_transition_unverified": "结算转场观察到期，仍未确认结束，已保存截图并停止",
        "action_plan_unavailable": "当前动作无法生成有效输入计划，等待重新识别",
        "no_action": "策略正在等待，当前没有可执行动作",
        "enemy_turn": "等待对手行动或游戏转场，正常运行无需外部命令",
        "action_result": "输入已发送，等待可见结果验证",
        "action_timeout": "未能在期限内验证动作结果，已停止，避免重复输入",
        "stale_frame": "画面已过期，重新截图；持续过期将停止",
        "game_reconnecting": "游戏正在重新连线，暂停输入；连续五分钟后尝试重启一次 LoR",
        "reconnect_restart": "重连页已持续五分钟，关闭并重新启动 LoR",
        "reconnect_restart_transition": "LoR 已重新启动，等待登录或可识别的游戏画面",
        "reconnect_restart_verified": "已识别重启后的游戏画面，重新进入自主流程",
        "reconnect_restart_failed": "LoR 重启命令失败，已停止",
        "reconnect_restart_unverified": "重启后两分钟内未确认进入游戏，已保存截图并停止",
        "reconnect_recovery_exhausted": "单次重启后仍持续重连，已停止，不再自动重启",
        "service_error_dismissed": "已点一次「確定」关闭服务错误弹窗，并识别到后继画面",
        "service_error_transition_unverified": "点击服务错误「確定」后未确认后继画面，已保存截图并停止，不重复点击",
        "service_error_repeated": "本次会话服务错误弹窗已出现多次，已保存截图并停止",
        "frame_expired_during_decision": "决策时画面已过期，重新截图",
        "battle_end": "已识别战斗结束画面，尚不代表获胜或冒险完成",
        "adventure_victory": "已识别冒险最终胜利结算页并核验退出结算；是否全程无人介入须结合完整运行记录确认",
        "reward_settlement_closed": "已核验退出奖励结算；单独领奖不证明冒险获胜",
        "discard_sample": "已选择一次弃牌并保存截图，后续确认流程尚未实现",
        "stop_requested": "已收到协作停止请求",
    }
    if phase in {"stopped", "failed", "cancelled"}:
        return f"运行已停止（{reason or phase}）；" + reasons.get(reason, "请查看事件与关联截图")
    if reason in reasons:
        return reasons[reason]
    if phase == "decided":
        return details.get("decision_reason") or f"已选择动作 {details.get('action', '')}"
    if phase == "recognized":
        return f"识别到 {details.get('ui', 'unknown')}；{details.get('summary', '')}"
    if phase == "input_sent":
        return f"已发送 {details.get('action', '')} 输入，尚未确认游戏结果"
    if phase == "verified":
        return f"已验证可见结果：{reason or details.get('action', '')}"
    return f"{phase}" + (f"（{reason}）" if reason else "")


def runs_root(root: str | Path | None = None) -> Path:
    return Path(root or os.environ.get("LORWRIGHT_RUNS_DIR", "logs/runs")).resolve()


def run_path(root: str | Path | None, run_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", run_id):
        raise ValueError("会话 ID 格式无效")
    base = runs_root(root)
    path = base / run_id
    if path.resolve().parent != base:
        raise ValueError("会话路径超出根目录")
    return path


def new_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:12]


def _utc() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sharing_conflict(exc: OSError) -> bool:
    return getattr(exc, "winerror", None) in {5, 32, 33}


def _atomic_json(path: Path, value: dict) -> None:
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")
        for attempt in range(5):
            try:
                os.replace(temp, path)
                break
            except OSError as exc:
                if not _sharing_conflict(exc) or attempt == 4:
                    raise
                time.sleep(0.05)
    finally:
        temp.unlink(missing_ok=True)


def process_alive(pid: int | None) -> bool:
    if not pid:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5  # access denied is not evidence of exit
        try:
            code = wintypes.DWORD()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def read_status(root: str | Path | None, run_id: str | None = None) -> dict:
    base = runs_root(root)
    if run_id is None:
        paths = list(base.glob("*/status.json"))
        if not paths:
            raise FileNotFoundError("找不到会话")
        run_id = max(paths, key=lambda path: path.stat().st_mtime_ns).parent.name
    status_path = run_path(base, run_id) / "status.json"
    if not status_path.exists():
        raise FileNotFoundError(f"找不到会话：{run_id}")
    status = json.loads(status_path.read_text(encoding="utf-8"))
    process_path = run_path(base, run_id) / "process.json"
    if status.get("pid") is None and process_path.exists():
        status["pid"] = json.loads(process_path.read_text(encoding="utf-8"))["pid"]
    now = time.time()
    age = max(0.0, now - status["heartbeat_at"])
    progress_age = max(0.0, now - status["last_progress_at"])
    deadline = status.get("wait_deadline")
    status.update(heartbeat_age_s=age, last_progress_age_s=progress_age)
    if status["status"] in TERMINAL:
        health = status["status"]
    elif status["status"] == "starting" and status.get("pid") is None and age <= 5.0:
        health = "starting"
    elif not process_alive(status.get("pid")):
        health = "unresponsive"
        status.update(status="failed", reason="process_exited_without_terminal",
                      message="工作进程已退出且没有写入终态，请查看启动日志和事件")
    elif age > max(5.0, status["heartbeat_s"] * 3):
        health = "unresponsive"
    elif status["status"] == "starting":
        health = "starting"
    elif deadline is not None and now < deadline:
        health = "waiting"
    elif deadline is not None or progress_age >= status["stall_timeout_s"]:
        health = "stalled"
    else:
        health = "running"
    status["health"] = health
    return status


def _device_lock_root() -> Path:
    """设备占用属于本机用户，不随项目或日志目录改变。"""
    if sys.platform == "win32":
        cache = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    elif sys.platform == "darwin":
        cache = Path.home() / "Library" / "Caches"
    else:
        cache = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
    return cache / "lorwright" / "device-locks"


class _DeviceLock:
    def __init__(self, device: str):
        folder = _device_lock_root()
        folder.mkdir(parents=True, exist_ok=True)
        self.path = folder / (hashlib.sha256(device.encode()).hexdigest() + ".lock")
        self.file = None

    def acquire(self):
        self.file = self.path.open("a+b")
        try:
            if sys.platform == "win32":
                import msvcrt

                if self.path.stat().st_size == 0:
                    self.file.write(b"0")
                    self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            self.file = None
            raise RuntimeError("设备已由另一会话控制") from exc

    def release(self):
        if self.file is not None:
            # Closing releases the OS lock on both platforms.
            self.file.close()
            self.file = None


class RunSession:
    def __init__(
        self, root, *, mode, champion, device, jsonl=False, run_id=None,
        heartbeat_s=1.0, stall_timeout_s=30.0,
    ):
        if heartbeat_s <= 0 or stall_timeout_s <= 0:
            raise ValueError("heartbeat_s 和 stall_timeout_s 必须大于 0")
        self.root = runs_root(root)
        self.run_id = run_id or new_run_id()
        self.path = run_path(self.root, self.run_id)
        self.jsonl = jsonl
        self._mutex = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._token = None
        # ADB and desktop may address the same local simulator; serialize both.
        lock_key = "local-interactive-device" if device in {"adb", "desktop"} else str(device)
        self._lock = _DeviceLock(lock_key)
        now = time.time()
        self._status = dict(
            schema_version=1, run_id=self.run_id, status="starting", mode=mode,
            champion=champion, device=str(device), pid=os.getpid(), phase="starting",
            reason=None, details={}, started_at=_utc(), heartbeat_at=now,
            last_progress_at=now, wait_deadline=None, wait_reason=None, wait_phase=None,
            heartbeat_s=heartbeat_s,
            stall_timeout_s=stall_timeout_s, seq=0,
        )
        self._reported_health = None
        self._wait_key = None
        self._wait_deadline = None

    @property
    def finished(self) -> bool:
        """终态已写出；外层异常处理据此避免重复输出错误事件。"""
        return self._status["status"] in TERMINAL

    def __enter__(self):
        if self.jsonl and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        self.path.mkdir(parents=True, exist_ok=True)
        status_path = self.path / "status.json"
        if status_path.exists():
            old = json.loads(status_path.read_text(encoding="utf-8"))
            if old["status"] != "starting" or old.get("pid") not in (None, os.getpid()):
                raise RuntimeError("会话 ID 已被使用")
        try:
            self._lock.acquire()
        except Exception as exc:
            self.finish("failed", "device_lock_unavailable", error=str(exc))
            raise
        try:
            self._token = _active.set(self)
            self._status["status"] = "running"
            self.event("session_started", mode=self._status["mode"], device=self._status["device"])
            self._thread = threading.Thread(target=self._heartbeat, name="run-heartbeat", daemon=True)
            self._thread.start()
            return self
        except BaseException:
            # __enter__ 失败时 Python 不会调用 __exit__，这里必须自行收尾。
            self._stop.set()
            if self._thread is not None and self._thread.is_alive():
                self._thread.join()
            if self._token is not None:
                _active.reset(self._token)
                self._token = None
            self._lock.release()
            raise

    def __exit__(self, exc_type, exc, tb):
        try:
            if isinstance(exc, (StopRequested, KeyboardInterrupt)):
                self.finish("cancelled", "stop_requested" if isinstance(exc, StopRequested)
                            else "keyboard_interrupt")
            elif exc is not None:
                self.finish("failed", "exception", error_type=type(exc).__name__, error=str(exc))
            else:
                self.finish("stopped", "run_returned")
        finally:
            self._stop.set()
            if self._thread:
                self._thread.join()
            if self._token is not None:
                _active.reset(self._token)
            self._lock.release()
        return False

    def _persist(self):
        _atomic_json(self.path / "status.json", self._status)

    def event(self, event_type, **payload):
        with self._mutex:
            if self._status["status"] in TERMINAL:
                return
            self._append(event_type, payload)
            self._persist()

    def _append(self, event_type, payload):
        seq = self._status["seq"] + 1
        envelope = dict(schema_version=1, run_id=self.run_id, seq=seq,
                        ts_utc=_utc(), type=event_type, payload=payload)
        line = json.dumps(envelope, ensure_ascii=False)
        with (self.path / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")
            stream.flush()
        self._status["seq"] = seq
        self._status["last_event"] = envelope
        if event_type == "snapshot":
            self._status["last_snapshot"] = payload.get("path", payload.get("snapshot"))
        if self.jsonl:
            print(line, flush=True)

    def report(self, phase, reason=None, *, progress=False, wait_s=None, **details):
        if wait_s is not None and wait_s < 0:
            raise ValueError("wait_s 不能小于 0")
        with self._mutex:
            if self._status["status"] in TERMINAL:
                return
            now = time.time()
            if "champion" in details:
                self._status["champion"] = details["champion"]
            if progress:
                self._status["last_progress_at"] = now
                self._wait_key = self._wait_deadline = None
            if wait_s is not None and self._wait_key != (phase, reason):
                self._wait_key = (phase, reason)
                self._wait_deadline = now + wait_s
            message = details.get("message") or describe_status(phase, reason, details)
            if phase == "decided":
                self._status["last_decision"] = {
                    key: details[key] for key in ("action", "strategy", "decision_reason", "unknown_cards")
                    if key in details
                }
            self._status.update(phase=phase, reason=reason, message=message,
                                details={**self._status["details"], **details},
                                wait_deadline=self._wait_deadline,
                                wait_phase=self._wait_key[0] if self._wait_key else None,
                                wait_reason=self._wait_key[1] if self._wait_key else None)
            if details.get("snapshot") is not None:
                self._status["last_snapshot"] = details["snapshot"]
            self.event("phase", phase=phase, reason=reason, progress=progress,
                       wait_deadline=self._status["wait_deadline"], **(details | {"message": message}))

    def finish(self, status, reason, **details):
        if status not in TERMINAL:
            raise ValueError("finish 需要终态 status")
        with self._mutex:
            if self._status["status"] in TERMINAL:
                return
            self.path.mkdir(parents=True, exist_ok=True)
            message = details.get("message") or describe_status(status, reason, self._status["details"] | details)
            self._status.update(status=status, reason=reason, message=message,
                                details={**self._status["details"], **details},
                                finished_at=_utc(), wait_deadline=None,
                                wait_phase=None, wait_reason=None)
            self._append("session_finished", dict(status=status, reason=reason,
                                                  **(details | {"message": message})))
            self._persist()
            self._stop.set()

    def _heartbeat(self):
        failed = False
        while not self._stop.wait(self._status["heartbeat_s"]):
            with self._mutex:
                if self._status["status"] in TERMINAL:
                    return
                previous = self._status["heartbeat_at"]
                try:
                    self._status["heartbeat_at"] = time.time()
                    try:
                        self._persist()
                    except OSError:
                        self._status["heartbeat_at"] = previous
                        raise
                    health = read_status(self.root, self.run_id)["health"]
                    if health != self._reported_health:
                        self.event("health", health=health)
                        self._reported_health = health
                except OSError as exc:
                    if not _sharing_conflict(exc):
                        raise
                    if not failed:
                        print(f"run-heartbeat: 状态访问失败，将重试: {exc}", file=sys.stderr, flush=True)
                    failed = True
                    continue
                if failed:
                    print("run-heartbeat: 状态访问已恢复", file=sys.stderr, flush=True)
                    failed = False


def current_session() -> RunSession | None:
    return _active.get()


def report(phase, reason=None, *, progress=False, wait_s=None, **details):
    if session := current_session():
        session.report(phase, reason, progress=progress, wait_s=wait_s, **details)


def checkpoint():
    if (session := current_session()) and (session.path / "stop.request").exists():
        raise StopRequested("stop requested")


def record_event(event_type, **payload):
    if session := current_session():
        session.event(event_type, **payload)
