"""Temporary ART tracing for the verified Pie64 / LoR startup workaround."""

from __future__ import annotations

import time
import uuid
from typing import Protocol

from lorwright.util.logger import logger

PACKAGE = "com.riotgames.legendsofruneterra"


class ShellRunner(Protocol):
    def run(self, *args: str) -> str: ...


def launch_pie64(runner: ShellRunner, package: str) -> None:
    """Launch once, trace for eight seconds, stop tracing, verify survival.

    A running client is only brought to the foreground. Failed launches retain
    their uniquely named trace; successful launches remove only their own trace.
    No system properties, compilation settings or app data are changed.
    """
    if package != PACKAGE:
        raise RuntimeError("pie64_trace 仅适用于 LoR")
    for name, expected in [("ro.build.version.release", "9"), ("ro.debuggable", "1")]:
        if runner.run("shell", "getprop", name).strip() != expected:
            raise RuntimeError(f"pie64_trace 要求 {name}={expected}，未修改设备设置")
    info = runner.run("shell", "dumpsys", "package", package)
    if not any(line.strip() == "versionName=07.11.015" for line in info.splitlines()):
        raise RuntimeError("pie64_trace 当前仅验证过 LoR 07.11.015")

    def pid() -> str:
        # Expected absence must not hide transport failures. The fixed package
        # name is checked above; only Android's pidof status is neutralized.
        output = runner.run("shell", f"pidof {PACKAGE}; true").strip()
        if output and not output.isdigit():
            raise RuntimeError("无法确认 LoR 进程，停止启动")
        return output

    activity = package + "/.LoRActivity"
    if pid():
        runner.run("shell", "am", "start", "-n", activity)
        return

    trace = f"/data/local/tmp/lorwright-start-{uuid.uuid4().hex}.trace"
    stop_failed = False
    try:
        result = runner.run(
            "shell", "am", "start", "--start-profiler", trace,
            "--streaming", "-n", activity,
        )
        if "Error:" in result or "Exception" in result:
            raise RuntimeError("Android 拒绝带轨迹的启动")
        time.sleep(8)
        started_pid = pid()
        if not started_pid:
            raise RuntimeError(f"LoR 启动后退出，诊断轨迹保留在 {trace}")
    finally:
        try:
            runner.run("shell", "am", "profile", "stop", package)
        except RuntimeError:
            stop_failed = True
            logger.error("停止启动轨迹失败，请检查设备连接：{}", trace)
    if stop_failed:
        raise RuntimeError("未确认启动轨迹已停止，停止后续操作")
    time.sleep(22)
    focus = runner.run("shell", "dumpsys", "window", "windows")
    focused = any("mCurrentFocus" in line and package in line for line in focus.splitlines())
    if pid() != started_pid or not focused:
        raise RuntimeError(f"关闭轨迹后客户端未保持前台存活，诊断轨迹保留在 {trace}")
    try:
        runner.run("shell", "rm", trace)
    except RuntimeError:
        logger.warning("LoR 已启动，但临时轨迹未清理：{}", trace)
    logger.info("LoR 已启动；临时 ART 跟踪已关闭，PID={}", started_pid)
