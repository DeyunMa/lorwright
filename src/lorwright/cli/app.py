"""CLI 入口。"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from lorwright.cli.sessions import app as sessions_app
from lorwright.core.config import load_settings
from lorwright.core.util.logger import logger, setup_logger

app = typer.Typer(add_completion=False, help="lorwright — LoR 英雄之路自动化")
app.add_typer(sessions_app, name="sessions")
console = Console()


@app.callback()
def _init(ctx: typer.Context) -> None:
    # 查询运行状态不依赖游戏配置、视觉库或设备；运行入口在会话内加载配置，
    # 保证启动失败也有机器可读结果。
    if ctx.invoked_subcommand not in {"sessions", "run", "adventure", "hand"}:
        settings = load_settings()
        setup_logger(settings.logging.dir, settings.logging.level, settings.logging.by_date)


def _session_wait(seconds: float, reason: str) -> None:
    from lorwright.core.runtime.session import checkpoint, report

    deadline = time.monotonic() + seconds
    report("waiting", reason, wait_s=seconds)
    while True:
        checkpoint()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.5, remaining))


def _make_device(kind: str):
    from lorwright.core.device import AdbDevice, DesktopDevice

    settings = load_settings()
    if kind == "desktop":
        return DesktopDevice(settings.screen.width, settings.screen.height)
    return AdbDevice(
        serial=settings.adb.serial or None,
        adb=settings.adb.adb_path,
        launch_mode=settings.adb.launch_mode,
        wait=_session_wait,
    )


@app.command()
def devices() -> None:
    """列出已连接的 ADB 设备（配了 serial 会先自动 connect）。"""
    from lorwright.core.device.adb import AdbDevice

    settings = load_settings()
    serials = AdbDevice.list_devices(
        settings.adb.adb_path, connect=settings.adb.serial or None
    )
    if not serials:
        console.print("[yellow]没有检测到 ADB 设备[/yellow]")
        console.print("检查：USB 调试是否开启、是否点了「允许」、数据线是否支持数据传输")
        raise typer.Exit(1)

    table = Table(title="ADB 设备")
    table.add_column("序号")
    table.add_column("序列号")
    for i, s in enumerate(serials):
        table.add_row(str(i), s)
    console.print(table)
    console.print("\n在 config/settings.yaml 的 adb.serial 里填序列号（多开时必填）")


@app.command()
def probe(device: str = typer.Option("adb", help="adb | desktop")) -> None:
    """设备探测：分辨率、前台应用、UI 状态。"""
    from lorwright.core.perceive.ui_state import UIStateDetector

    settings = load_settings()
    dev = _make_device(device)
    det = UIStateDetector(
        threshold=settings.perception.match_threshold,
        action_button=settings.layout.to_layout().end_turn,
    )
    det.load()

    frame = dev.screencap()
    state = det.detect(frame.image)
    size = dev.size()

    table = Table(title=f"环境探测（{dev.name}）")
    table.add_column("项目")
    table.add_column("值")
    table.add_row("分辨率", f"{size[0]}x{size[1]}")
    table.add_row("截图尺寸", f"{frame.width}x{frame.height}")
    table.add_row("UI 状态", state.value)
    table.add_row("按钮模板", str(len(det._tpl)))  # noqa: SLF001
    # Windows 控制台是 GBK，不能用 emoji
    table.add_row("Layout 标定", "已标定" if settings.layout_ready else "未标定")
    if hasattr(dev, "current_focus"):
        table.add_row("前台应用", dev.current_focus()[:80])
    console.print(table)
    dev.close()


@app.command()
def shot(
    out: str = "logs/shot.png",
    device: str = typer.Option("adb", help="adb | desktop"),
    grid: int = typer.Option(0, help="叠加坐标网格（像素间距，0=不叠）"),
) -> None:
    """截一张图保存（用于量坐标、采模板）。"""
    import cv2

    dev = _make_device(device)
    frame = dev.screencap()
    dev.close()

    img = frame.image
    if grid > 0:
        img = _draw_grid(img, grid)

    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), img)
    console.print(f"[green]已保存[/green] {path}  ({frame.width}x{frame.height})")
    if grid > 0:
        console.print(f"网格间距 {grid}px，直接读坐标填 layout")


def _draw_grid(img, step: int):
    """在图上画坐标网格，方便量 layout。"""
    import cv2

    out = img.copy()
    h, w = out.shape[:2]
    color = (0, 255, 0)
    for x in range(0, w, step):
        cv2.line(out, (x, 0), (x, h), color, 1)
        cv2.putText(out, str(x), (x + 3, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
    for y in range(0, h, step):
        cv2.line(out, (0, y), (w, y), color, 1)
        cv2.putText(out, str(y), (3, y + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
    return out


@app.command()
def crop(
    rect: str = typer.Option(..., help="x,y,w,h（左上角坐标 + 宽高）"),
    name: str = typer.Option(..., help="模板名，如 end_turn"),
    src: str = typer.Option("logs/shot.png", help="源图"),
    out: str = typer.Option("assets/buttons", help="输出目录"),
    device: str = typer.Option("", help="留空=用已有 src；填 adb=先截一张再裁"),
) -> None:
    """从截图裁出一块存成模板。"""
    import cv2

    if device:
        dev = _make_device(device)
        img = dev.screencap().image
        dev.close()
        Path(src).parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(src, img)

    img = cv2.imread(src)
    if img is None:
        console.print(f"[red]读不到图：{src}[/red]")
        raise typer.Exit(1)

    x, y, w, h = (int(v) for v in rect.split(","))
    patch = img[y : y + h, x : x + w]
    if patch.size == 0:
        console.print("[red]裁剪区域超出图像范围[/red]")
        raise typer.Exit(1)

    dest = Path(out) / f"{name}.png"
    dest.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(dest), patch)
    console.print(f"[green]已保存[/green] {dest}  ({w}x{h})")


@app.command()
def tap(
    x: int = typer.Argument(..., help="屏幕 x 坐标"),
    y: int = typer.Argument(..., help="屏幕 y 坐标"),
    device: str = typer.Option("adb", help="adb | desktop"),
) -> None:
    """手动点一下（标定、走界面、采模板时用）。"""
    dev = _make_device(device)
    try:
        dev.tap(x, y)
    finally:
        dev.close()
    console.print(f"[green]tap[/green] ({x}, {y})")


@app.command()
def drag(
    x1: int = typer.Argument(..., help="起点 x"),
    y1: int = typer.Argument(..., help="起点 y"),
    x2: int = typer.Argument(..., help="终点 x"),
    y2: int = typer.Argument(..., help="终点 y"),
    hold: int = typer.Option(0, help="按下后停顿毫秒，0 = 用配置的 act.drag_hold_ms"),
    ms: int = typer.Option(0, help="移动时长毫秒，0 = 用配置的 act.drag_ms"),
    device: str = typer.Option("adb", help="adb | desktop"),
) -> None:
    """按住 → 停顿 → 拖 → 松手（出牌、攻击）。LoR 出牌必须停顿，见 handoff §4.6。"""
    settings = load_settings()
    hold_ms = hold or settings.act.drag_hold_ms
    duration = ms or settings.act.drag_ms
    dev = _make_device(device)
    try:
        dev.drag(x1, y1, x2, y2, hold_ms, duration)
    finally:
        dev.close()
    console.print(
        f"[green]drag[/green] ({x1}, {y1}) -> ({x2}, {y2})  hold={hold_ms}ms move={duration}ms"
    )


@app.command()
def text(
    value: str = typer.Argument(..., help="要输入的文本（ASCII）"),
    device: str = typer.Option("adb", help="adb | desktop"),
) -> None:
    """往当前焦点输入框打字（登录、搜索框）。"""
    dev = _make_device(device)
    try:
        dev.text(value)
    finally:
        dev.close()
    console.print(f"[green]text[/green] {value!r}")


@app.command()
def launch(device: str = typer.Option("adb", help="adb | desktop")) -> None:
    """启动游戏客户端（不强制结束已在跑的进程）。"""
    settings = load_settings()
    dev = _make_device(device)
    try:
        dev.launch(settings.adb.package)
    finally:
        dev.close()
    console.print(f"[green]launch[/green] {settings.adb.package}")


@app.command()
def login(
    tries: int = typer.Option(3, help="最多尝试几轮"),
    device: str = typer.Option("adb", help="adb | desktop"),
) -> None:
    """登录 LoR（账号密码从 .env 的 LOR_USERNAME / LOR_PASSWORD 读）。

    模拟器重启会清掉登录态，而客户端卡在登录页时 `ui_state` 只能是 UNKNOWN，
    看门狗只会判「卡住」。所以登录得是个显式步骤。
    """
    from lorwright.core.device.adb import secret_text_supported
    from lorwright.core.perceive.login import LoginDetector, LoginScreen

    settings = load_settings()
    user, pwd = settings.lor_username, settings.lor_password
    if not user or not pwd:
        console.print("[red]缺少 LOR_USERNAME / LOR_PASSWORD[/red]（写进 .env）")
        raise typer.Exit(2)
    if device == "adb" and not (secret_text_supported(user) and secret_text_supported(pwd)):
        console.print("[red]凭据包含 ADB 输入不支持的字符[/red]")
        raise typer.Exit(2)

    layout = settings.layout.to_layout()
    if not (layout.login_splash and layout.login_username and layout.login_password
            and layout.login_submit):
        console.print("[red]config/settings.yaml 缺 login_* 坐标[/red]")
        raise typer.Exit(2)

    detector = LoginDetector()
    detector.load()
    dev = _make_device(device)
    try:
        for i in range(tries):
            kind = detector.detect(dev.screencap().image)
            console.print(f"  [{i + 1}/{tries}] {kind.value}")
            if kind is LoginScreen.NONE:
                console.print("[green]login[/green] 已登录（不在登录界面）")
                return
            if kind is LoginScreen.SPLASH:
                dev.tap(*layout.login_splash.center)
                time.sleep(5)
                continue
            input_credential = dev.text_secret if device == "adb" else dev.text
            try:
                for field, value in ((layout.login_username, user), (layout.login_password, pwd)):
                    dev.tap(*field.center)
                    time.sleep(0.6)
                    if hasattr(dev, "clear_text"):
                        dev.clear_text()
                        time.sleep(0.2)
                    input_credential(value)
                    time.sleep(0.4)
            except Exception:
                console.print("[red]登录凭据输入失败[/red]")
                raise typer.Exit(1) from None
            dev.tap(*layout.login_submit.center)
            time.sleep(10)
    finally:
        dev.close()
    console.print("[yellow]login[/yellow] 未能确认登录成功，请人工看一眼")


@app.command()
def state(device: str = typer.Option("adb", help="adb | desktop")) -> None:
    """解析当前画面，打印识别到的状态（调感知层用）。"""
    from lorwright.core.perceive.digits import DigitReader
    from lorwright.core.perceive.state import StateParser
    from lorwright.core.perceive.ui_state import UIStateDetector

    settings = load_settings()
    layout = settings.layout.to_layout()
    parser = StateParser(
        layout=layout,
        ui=UIStateDetector(
            threshold=settings.perception.match_threshold,
            action_button=layout.end_turn,
        ),
        digits=DigitReader(),
        threshold=settings.perception.match_threshold,
    )
    parser.load()

    dev = _make_device(device)
    try:
        frame = dev.screencap()
    finally:
        dev.close()

    from lorwright.core.perceive.normalize import Normalizer

    image, scale = Normalizer((settings.screen.width, settings.screen.height)).fit(frame.image)
    if not scale.identity:
        console.print(
            f"[yellow]分辨率 {frame.width}x{frame.height} != 设计尺寸 "
            f"{settings.screen.width}x{settings.screen.height}，已归一化[/yellow]"
        )
    st = parser.parse(image)
    table = Table(title="状态解析")
    table.add_column("字段")
    table.add_column("值")
    table.add_row("UI 状态", st.ui_state.value)
    table.add_row("法力", f"{st.mana}/{st.max_mana}")
    table.add_row("我方水晶", str(st.nexus_hp))
    table.add_row("敌方水晶", str(st.enemy_nexus_hp))
    for field_name, label in [("mana", "法力观测"), ("nexus_hp", "我方血量观测"),
                              ("enemy_nexus_hp", "敌方血量观测")]:
        reading = st.readings[field_name]
        detail = ("本帧读到" if reading.fresh else
                  f"缓存，{reading.age_frames} 帧前" if reading.value is not None else "未知，未读到")
        table.add_row(label, detail)
    table.add_row("手牌", str(len(st.hand)))
    if st.hand:
        table.add_row("手牌费用", ", ".join(str(c.cost) for c in st.hand))
    table.add_row("字形库", f"{sorted(parser.digits.digits)}")
    console.print(table)
    console.print(f"summary: {st.summary()}", markup=False)


@app.command()
def doctor() -> None:
    """环境自检。"""
    from lorwright.core.doctor import blockers, format_checks, run_checks

    settings = load_settings()
    checks = run_checks(settings)
    console.print(format_checks(checks), markup=False)
    bad = blockers(checks)
    console.print(
        f"\n[yellow]{len(bad)} 项阻塞[/yellow]" if bad else "\n[green]必需项全部就绪[/green]"
    )


def _battle_layers(pack, *, policy_kwargs: dict | None = None) -> list:
    """对局内共用决策层：可选选牌 → 英雄包 → 通用战斗策略。"""
    from lorwright.core.decide.card import CardKind
    from lorwright.core.decide.generic import (
        AttackWhenTokenPolicy,
        BlockingPolicy,
        CombatConfirmPolicy,
        ExpandHandPolicy,
        HeroFirstPolicy,
        OptionalChoicePolicy,
        PlayUnitPolicy,
        RequiredChoicePolicy,
        TargetingPolicy,
        UnknownCardPolicy,
    )

    champion_names = frozenset(
        card.name for card in pack.deck if card.kind is CardKind.CHAMPION
    )
    policy = pack.make_policy(**(policy_kwargs or {})) if policy_kwargs else pack.make_policy()
    layers = [
        OptionalChoicePolicy(),
        RequiredChoicePolicy(),
        policy,
        ExpandHandPolicy(),
        HeroFirstPolicy(champion_names),
    ]
    lookup = getattr(pack, "lookup", None)
    if lookup is not None:
        layers.append(PlayUnitPolicy(lookup))
    layers.extend(
        [
            TargetingPolicy(),
            AttackWhenTokenPolicy(),
            UnknownCardPolicy(),
            CombatConfirmPolicy(),
            BlockingPolicy(),
        ]
    )
    return layers


def _jinx_policy_kwargs(
    pack, *, spell_already_played: bool, jinx_summoned: bool,
    rockets_already_played: int | None = None,
) -> dict | None:
    if pack.name != "jinx":
        return None
    kwargs = {}
    if spell_already_played:
        kwargs["spell_already_played"] = True
    if jinx_summoned:
        kwargs["jinx_summoned"] = True
    if rockets_already_played is not None:
        kwargs["rockets_already_played"] = rockets_already_played
    return kwargs or None


def _execute_session(
    *, mode: str, device: str, replay: str, champion: str,
    max_ticks: int, max_nodes: int, jsonl: bool, run_id: str | None,
    stall_timeout: float, spell_already_played: bool, jinx_summoned: bool,
    bootstrap_f1: bool = False, open_riot_login: bool = False, auto_login: bool = False,
    rockets_already_played: int | None = None, confirm_empty_hand_once: bool = False,
    sample_hero_item_jinx: bool = False, hand_view: bool | None = None,
    weekly_replay_slot: int | None = None,
) -> None:
    """运行入口共用生命周期；手牌视图任务不装配战斗策略。"""
    from lorwright.core.device.adb import AdbTimeout
    from lorwright.core.runtime.session import RunSession, StopRequested, checkpoint, report

    root = Path(os.environ.get("LORWRIGHT_RUNS_DIR", "logs/runs"))
    device_key = f"replay:{Path(replay).resolve()}" if replay else device
    exit_code = 1
    session = None
    try:
        session = RunSession(
            root, mode=mode, champion=champion or "config", device=device_key,
            jsonl=jsonl, run_id=run_id, stall_timeout_s=stall_timeout,
        )
        with session:
            try:
                from lorwright.core.champions import load as load_champion
                from lorwright.core.decide.router import Router
                from lorwright.core.loop.adventure import AdventureLoop
                from lorwright.core.loop.engine import Engine
                from lorwright.core.loop.outcome import LoopResult

                if mode == "hand" and hand_view is None:
                    raise ValueError("hand 模式需要明确目标视图")
                if bootstrap_f1 and (mode != "adventure" or replay or device != "adb"):
                    raise ValueError("--bootstrap-f1 仅适用于使用 ADB 的实机冒险")
                if open_riot_login and not bootstrap_f1:
                    raise ValueError("--open-riot-login 需要 --bootstrap-f1")
                if auto_login and not bootstrap_f1:
                    raise ValueError("--auto-login 需要 --bootstrap-f1")
                report("starting", "loading_configuration")
                settings = load_settings()
                setup_logger(settings.logging.dir, settings.logging.level, settings.logging.by_date)
                settings.perception.snapshot_dir = str(root / session.run_id / "snapshots")
                pack = load_champion(champion or settings.champion)
                report("starting", "opening_device", champion=pack.name, replay=bool(replay))
                checkpoint()
                if not jsonl:
                    console.print(f"运行：{session.run_id}  英雄：{pack.display_name}")
                if replay:
                    from lorwright.core.device.replay import ReplayDevice

                    dev = ReplayDevice(replay)
                else:
                    if device not in {"adb", "desktop"}:
                        raise ValueError("device 必须是 adb 或 desktop")
                    dev = _make_device(device)
                try:
                    bootstrap_stop = None
                    if bootstrap_f1:
                        from lorwright.core.loop.bootstrap import prepare_f1

                        bootstrap_stop = prepare_f1(
                            settings, dev, open_riot_login=open_riot_login, auto_login=auto_login,
                        ).stop_reason
                    if bootstrap_stop:
                        result = LoopResult("stopped", bootstrap_stop)
                    else:
                        kwargs = None if mode == "hand" else _jinx_policy_kwargs(
                            pack, spell_already_played=spell_already_played,
                            jinx_summoned=jinx_summoned,
                            rockets_already_played=rockets_already_played,
                        )
                        def run_loop(capture_frame, restarted):
                            # 重启后重新识别场景，不携带旧动作、选择或中局恢复参数。
                            engine = Engine(
                                settings, Router([] if mode == "hand" else _battle_layers(
                                    pack, policy_kwargs=None if restarted else kwargs,
                                )), dev,
                                card_recognizer=getattr(pack, "recognize_hand", None),
                                mulligan_recognizer=getattr(pack, "recognize_mulligan", None),
                                targeted_spell_recognizer=getattr(pack, "recognize_targeted_spell", None),
                                confirm_empty_hand_once=confirm_empty_hand_once and not restarted,
                                capture_frame=capture_frame,
                                my_unit_recognizer=getattr(pack, "recognize_my_units", None),
                            )
                            if mode == "hand":
                                return engine.observe_hand(expanded=hand_view, close_device=False)
                            if mode == "adventure":
                                return AdventureLoop(
                                    settings, engine, dev, pack=pack,
                                    sample_hero_item_jinx=sample_hero_item_jinx,
                                    weekly_replay_slot=None if restarted else weekly_replay_slot,
                                    capture_frame=capture_frame,
                                ).run(max_nodes=max_nodes)
                            return engine.run(max_ticks=max_ticks or None, close_device=False)

                        if mode != "hand" and device == "adb" and not replay:
                            from lorwright.core.loop.reconnect import run_with_reconnect_recovery

                            result = run_with_reconnect_recovery(
                                settings, dev, run_loop, auto_login=auto_login,
                            )
                        else:
                            result = run_loop(None, False)
                finally:
                    dev.close()
                session.finish(result.status, result.reason)
                # 达到调用者指定的观察预算是正常返回，但不是通关。
                limited = result.reason in {"tick_limit", "node_limit", "iteration_limit"}
                exit_code = 0 if result.status == "completed" or limited else 3
            except (StopRequested, KeyboardInterrupt) as exc:
                reason = "stop_requested" if isinstance(exc, StopRequested) else "interrupted"
                session.finish("cancelled", reason)
                exit_code = 130
            except AdbTimeout as exc:
                session.finish("failed", "device_timeout", error_type=type(exc).__name__,
                               message=str(exc))
                logger.error("设备超时：{}", exc)
                exit_code = 1
            except Exception as exc:
                session.finish("failed", "execution_error", error_type=type(exc).__name__,
                               message=str(exc))
                logger.exception("运行失败：{}", type(exc).__name__)
                exit_code = 1
            if not jsonl:
                console.print(f"运行已结束，可查询：lorwright sessions status {session.run_id}")
    except Exception as exc:
        # 目录或设备锁失败也保持机器输出可解析，不把 traceback 写入 stdout。
        if jsonl and (session is None or not session.finished):
            record = {
                "schema_version": 1, "run_id": run_id, "seq": 0,
                "ts_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "type": "error", "payload": {
                    "reason": "session_start_failed", "error_type": type(exc).__name__,
                    "message": str(exc),
                },
            }
            print(json.dumps(record, ensure_ascii=True), flush=True)
        elif not jsonl:
            print(f"无法启动运行：{exc}", file=sys.stderr)
        exit_code = 1
    if exit_code:
        raise typer.Exit(exit_code)


class HandView(StrEnum):
    EXPANDED = "expanded"
    COLLAPSED = "collapsed"


@app.command()
def hand(
    view: Annotated[HandView, typer.Option(help="目标手牌视图：expanded | collapsed")],
    device: str = typer.Option("adb", help="adb | desktop"),
    replay: str = typer.Option("", help="离线回放目录，不连接设备"),
    champion: str = typer.Option("", help="覆盖 config 的 champion"),
    jsonl: bool = typer.Option(False, "--jsonl", help="stdout 输出会话 JSONL 事件"),
) -> None:
    """核验手牌展开或收起；最多一次视图输入，不推进战斗。"""
    _execute_session(
        mode="hand", hand_view=view is HandView.EXPANDED,
        device=device, replay=replay, champion=champion, jsonl=jsonl,
        max_ticks=0, max_nodes=0, run_id=None, stall_timeout=30.0,
        spell_already_played=False, jinx_summoned=False,
    )


@app.command()
def adventure(
    max_nodes: int = typer.Option(30, min=1, help="冒险外层的最大观察轮数（不是完成节点数）"),
    device: str = typer.Option("adb", help="adb | desktop"),
    replay: str = typer.Option("", help="离线回放目录，不连接设备"),
    champion: str = typer.Option("", help="覆盖 config 的 champion"),
    jsonl: bool = typer.Option(False, "--jsonl", help="stdout 输出会话 JSONL 事件"),
    run_id: str | None = typer.Option(None, hidden=True),
    stall_timeout: float = typer.Option(30.0, min=0.1, help="默认无进展告警秒数"),
    spell_already_played: bool = typer.Option(False, help="Jinx 恢复中局：起手法术已打出"),
    jinx_summoned: bool = typer.Option(False, help="Jinx 恢复中局：Jinx 已下场，直接打飞逝牌"),
    bootstrap_f1: bool = typer.Option(False, "--bootstrap-f1", help="启动或接管 f1 Pie64 与游戏"),
    open_riot_login: bool = typer.Option(False, "--open-riot-login", help="在登录方式页打开 Riot 登录表单"),
    auto_login: bool = typer.Option(False, "--auto-login", help="使用配置凭据自动登录一次"),
    sample_hero_item_jinx: bool = typer.Option(False, help="受控采样：仅选择一次 Jinx 并保存画面"),
    weekly_replay_slot: int | None = typer.Option(None, min=1, max=3, help="重玩已完成周常：1 上方，2 左下，3 右下"),
) -> None:
    """运行冒险流程，输出可查询的阶段、等待和停止原因。"""
    _execute_session(
        mode="adventure", device=device, replay=replay, champion=champion,
        max_ticks=0, max_nodes=max_nodes, jsonl=jsonl, run_id=run_id,
        stall_timeout=stall_timeout, spell_already_played=spell_already_played,
        jinx_summoned=jinx_summoned, bootstrap_f1=bootstrap_f1,
        open_riot_login=open_riot_login, auto_login=auto_login,
        sample_hero_item_jinx=sample_hero_item_jinx,
        weekly_replay_slot=weekly_replay_slot,
    )


@app.command()
def run(
    max_ticks: int = typer.Option(0, min=0, help="最大循环次数，0 = 无限"),
    device: str = typer.Option("adb", help="adb | desktop"),
    replay: str = typer.Option("", help="回放目录：用历史截图跑，不碰设备"),
    champion: str = typer.Option("", help="覆盖 config 的 champion"),
    jsonl: bool = typer.Option(False, "--jsonl", help="stdout 输出会话 JSONL 事件"),
    run_id: str | None = typer.Option(None, hidden=True),
    stall_timeout: float = typer.Option(30.0, min=0.1, help="默认无进展告警秒数"),
    spell_already_played: bool = typer.Option(False, help="Jinx 恢复中局：起手法术已打出"),
    jinx_summoned: bool = typer.Option(False, help="Jinx 恢复中局：Jinx 已下场，直接打飞逝牌"),
    rockets_already_played: int | None = typer.Option(None, min=0, max=2, help="Jinx 已打出火箭数"),
    confirm_empty_hand_once: bool = typer.Option(False, help="人工确认当前空手，仅用于一次攻击"),
) -> None:
    """运行单场战斗；--replay 仅回放，--jsonl 提供机器事件流。"""
    if rockets_already_played is not None and (champion != "jinx" or not jinx_summoned):
        raise typer.BadParameter("--rockets-already-played 需要 --champion jinx 和 --jinx-summoned")
    _execute_session(
        mode="battle", device=device, replay=replay, champion=champion,
        max_ticks=max_ticks, max_nodes=0, jsonl=jsonl, run_id=run_id,
        stall_timeout=stall_timeout, spell_already_played=spell_already_played,
        jinx_summoned=jinx_summoned, rockets_already_played=rockets_already_played,
        confirm_empty_hand_once=confirm_empty_hand_once,
    )


if __name__ == "__main__":
    app()
