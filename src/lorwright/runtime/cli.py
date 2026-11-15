"""会话命令；磁盘是跨进程查询接口，不启动网络服务。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Annotated

import typer

from lorwright.runtime.session import (
    TERMINAL,
    _atomic_json,
    _utc,
    new_run_id,
    read_status,
    run_path,
    runs_root,
)

app = typer.Typer(help="启动和观测本地运行会话。", add_completion=False)
Root = Annotated[Path | None, typer.Option(help="会话根目录；默认 LORWRIGHT_RUNS_DIR 或 logs/runs")]


def _utf8_stdout():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def _output(value: dict, machine: bool):
    if machine:
        _utf8_stdout()
        typer.echo(json.dumps(value, ensure_ascii=False))
    else:
        for key, item in value.items():
            typer.echo(f"{key}: {item}")


def _status(root, run_id, machine=False):
    try:
        return read_status(root, run_id)
    except (OSError, ValueError) as exc:
        if machine:
            _output({"error": {"code": "session_unavailable", "message": str(exc)}}, True)
        else:
            typer.echo(f"无法读取会话：{exc}", err=True)
        raise typer.Exit(1) from exc


def _detach_options() -> dict:
    if sys.platform == "win32":
        return {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


@app.command()
def start(
    mode: Annotated[str, typer.Option(help="battle | adventure")] = "battle",
    champion: Annotated[str, typer.Option(help="英雄名称，原样传给运行命令")] = "",
    device: Annotated[str, typer.Option(help="adb | desktop")] = "adb",
    replay: Annotated[Path | None, typer.Option(help="截图回放目录")] = None,
    stall_timeout: Annotated[float, typer.Option(min=0.1, help="无进展告警阈值（秒）")] = 30.0,
    max_ticks: Annotated[int | None, typer.Option(min=1)] = None,
    max_nodes: Annotated[int | None, typer.Option(min=1)] = None,
    root: Root = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
):
    """后台启动；console.log 混合 stdout JSONL 和 stderr，事件消费者读 events 命令。"""
    if mode not in {"battle", "adventure"}:
        raise typer.BadParameter("模式需为 battle 或 adventure")
    if mode == "adventure" and max_ticks is not None:
        raise typer.BadParameter("max-ticks 仅适用于 battle 模式")
    if mode == "battle" and max_nodes is not None:
        raise typer.BadParameter("max-nodes 仅适用于 adventure 模式")
    base = runs_root(root)
    run_id = new_run_id()
    folder = run_path(base, run_id)
    folder.mkdir(parents=True)
    now = time.time()
    initial = dict(
        schema_version=1, run_id=run_id, status="starting", mode=mode, champion=champion,
        device=str(replay.resolve()) if replay else device, pid=None, phase="starting",
        reason=None, details={}, started_at=_utc(), heartbeat_at=now, last_progress_at=now,
        wait_deadline=None, heartbeat_s=1.0, stall_timeout_s=stall_timeout, seq=0,
    )
    _atomic_json(folder / "status.json", initial)
    command = [sys.executable, "-m", "lorwright.main", "run" if mode == "battle" else "adventure",
               "--run-id", run_id, "--jsonl", "--device", device,
               "--stall-timeout", str(stall_timeout)]
    if champion:
        command += ["--champion", champion]
    if replay is not None:
        command += ["--replay", str(replay.resolve())]
    if max_ticks is not None:
        command += ["--max-ticks", str(max_ticks)]
    if max_nodes is not None:
        command += ["--max-nodes", str(max_nodes)]
    env = dict(os.environ, LORWRIGHT_RUNS_DIR=str(base), PYTHONIOENCODING="utf-8")
    try:
        with (folder / "console.log").open("ab", buffering=0) as output:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=output,
                                       stderr=subprocess.STDOUT, env=env, close_fds=True,
                                       **_detach_options())
        _atomic_json(folder / "process.json", {"pid": process.pid})
        try:
            code = process.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            code = None
    except OSError as exc:
        initial.update(status="failed", reason="spawn_failed", details={"error": str(exc)},
                       finished_at=_utc())
        _atomic_json(folder / "status.json", initial)
        _output(initial, json_output)
        raise typer.Exit(1) from exc
    if code is not None:
        saved = json.loads((folder / "status.json").read_text(encoding="utf-8"))
        if saved["status"] not in TERMINAL:
            saved.update(status="failed", reason="process_exited_without_terminal",
                         pid=process.pid, details={"exit_code": code}, finished_at=_utc())
            _atomic_json(folder / "status.json", saved)
        _output(dict(run_id=run_id, pid=process.pid, status=saved["status"],
                     console_log=str(folder / "console.log"),
                     console_log_format="mixed_jsonl_and_stderr"), json_output)
        if saved["status"] == "failed":
            raise typer.Exit(1)
    else:
        _output(dict(run_id=run_id, pid=process.pid, status="starting",
                     console_log=str(folder / "console.log"),
                     console_log_format="mixed_jsonl_and_stderr"), json_output)


@app.command()
def status(
    run_id: Annotated[str | None, typer.Argument()] = None,
    root: Root = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    wait: Annotated[float, typer.Option(min=0, max=60, help="等待终态或异常健康状态，最多秒数")] = 0,
):
    """查询指定会话；省略 ID 时读取最近更新的会话。"""
    deadline = time.monotonic() + wait
    saved = _status(root, run_id, json_output)
    run_id = saved["run_id"]
    while (saved["status"] not in TERMINAL
           and saved["health"] not in {"stalled", "unresponsive"}):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(0.2, remaining))
        saved = _status(root, run_id, json_output)
    _output(saved, json_output)


@app.command()
def stop(
    run_id: Annotated[str | None, typer.Argument()] = None,
    root: Root = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
):
    """写停止请求；运行进程到下一个安全点才停止。"""
    saved = _status(root, run_id, json_output)
    requested = saved["status"] not in TERMINAL
    if requested:
        folder = run_path(root, saved["run_id"])
        (folder / "stop.request").write_text(_utc() + "\n", encoding="utf-8")
    _output(dict(run_id=saved["run_id"], requested=requested, status=saved["status"]), json_output)


@app.command()
def events(
    run_id: Annotated[str | None, typer.Argument()] = None,
    root: Root = None,
    jsonl: Annotated[bool, typer.Option("--jsonl")] = False,
    follow: Annotated[bool, typer.Option("--follow")] = False,
    after: Annotated[int, typer.Option(min=0, help="只返回 seq 大于此值的事件")] = 0,
):
    """补读完整事件行；终态或心跳失联后停止跟随。"""
    if jsonl:
        _utf8_stdout()
    saved = _status(root, run_id, jsonl)
    run_id = saved["run_id"]
    path = run_path(root, run_id) / "events.jsonl"
    position = 0
    while True:
        # Read status before draining: a newly observed terminal event is included.
        saved = _status(root, run_id, jsonl)
        if path.exists():
            with path.open("rb") as stream:
                stream.seek(position)
                while line := stream.readline():
                    if not line.endswith(b"\n"):
                        break
                    position = stream.tell()
                    event = json.loads(line)
                    if event["seq"] > after:
                        if jsonl:
                            typer.echo(json.dumps(event, ensure_ascii=False))
                        else:
                            typer.echo(f"{event['seq']} {event['ts_utc']} {event['type']} "
                                       f"{json.dumps(event['payload'], ensure_ascii=False)}")
        if follow and saved["health"] == "unresponsive":
            typer.echo(f"会话 {run_id} 心跳失联（unresponsive），已停止跟随事件", err=True)
            raise typer.Exit(2)
        if not follow or saved["status"] in TERMINAL:
            return
        time.sleep(0.2)
