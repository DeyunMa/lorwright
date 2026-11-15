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
        status.update(status="failed", reason="process_exited_without_terminal")
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
            self._status.update(phase=phase, reason=reason,
                                details={**self._status["details"], **details},
                                wait_deadline=self._wait_deadline,
                                wait_phase=self._wait_key[0] if self._wait_key else None,
                                wait_reason=self._wait_key[1] if self._wait_key else None)
            if details.get("snapshot") is not None:
                self._status["last_snapshot"] = details["snapshot"]
            self.event("phase", phase=phase, reason=reason, progress=progress,
                       wait_deadline=self._status["wait_deadline"], **details)

    def finish(self, status, reason, **details):
        if status not in TERMINAL:
            raise ValueError("finish 需要终态 status")
        with self._mutex:
            if self._status["status"] in TERMINAL:
                return
            self.path.mkdir(parents=True, exist_ok=True)
            self._status.update(status=status, reason=reason,
                                details={**self._status["details"], **details},
                                finished_at=_utc(), wait_deadline=None,
                                wait_phase=None, wait_reason=None)
            self._append("session_finished", dict(status=status, reason=reason, **details))
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
