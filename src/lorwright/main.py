"""CLI 入口。"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from lorwright.config import load_settings
from lorwright.util.logger import setup_logger

app = typer.Typer(add_completion=False, help="lorwright — LoR 英雄之路自动化")
console = Console()


@app.callback()
def _init() -> None:
    settings = load_settings()
    setup_logger(settings.logging.dir, settings.logging.level, settings.logging.by_date)


def _make_device(kind: str):
    from lorwright.device import AdbDevice, DesktopDevice

    settings = load_settings()
    if kind == "desktop":
        return DesktopDevice(settings.screen.width, settings.screen.height)
    return AdbDevice(
        serial=settings.adb.serial or None,
        adb=settings.adb.adb_path,
    )


@app.command()
def devices() -> None:
    """列出已连接的 ADB 设备。"""
    from lorwright.device.adb import AdbDevice

    serials = AdbDevice.list_devices()
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
    from lorwright.perceive.ui_state import UIStateDetector

    settings = load_settings()
    dev = _make_device(device)
    det = UIStateDetector(threshold=settings.perception.match_threshold)
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
    table.add_row("Layout 标定", "✅" if settings.layout_ready else "❌ 未标定")
    if hasattr(dev, "current_focus"):
        table.add_row("前台应用", dev.current_focus()[:80])
    console.print(table)
    dev.close()


@app.command()
def shot(
    out: str = "logs/shot.png",
    device: str = typer.Option("adb", help="adb | desktop"),
) -> None:
    """截一张图保存（用于量坐标、采模板）。"""
    import cv2

    dev = _make_device(device)
    frame = dev.screencap()
    dev.close()

    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), frame.image)
    console.print(f"[green]已保存[/green] {path}  ({frame.width}x{frame.height})")


@app.command()
def doctor() -> None:
    """环境自检。"""
    from lorwright.doctor import blockers, format_checks, run_checks

    settings = load_settings()
    checks = run_checks(settings)
    console.print(format_checks(checks), markup=False)
    bad = blockers(checks)
    console.print(
        f"\n[yellow]{len(bad)} 项阻塞[/yellow]" if bad else "\n[green]必需项全部就绪[/green]"
    )


@app.command()
def run(
    max_ticks: int = typer.Option(0, help="最大循环次数，0 = 无限"),
    device: str = typer.Option("adb", help="adb | desktop"),
) -> None:
    """运行主循环。"""
    from lorwright.decide.jev import JevClient
    from lorwright.decide.jev_policy import JevPolicy, LlmPolicy
    from lorwright.decide.llm import LlmClient
    from lorwright.decide.router import Router
    from lorwright.decide.rules import SpiderAggroPolicy
    from lorwright.loop.engine import Engine

    settings = load_settings()

    layers: list = [SpiderAggroPolicy()]
    if settings.jev_base_url:
        layers.append(JevPolicy(JevClient(settings.jev_base_url, settings.jev_api_key)))
    if settings.vlm_base_url and settings.vlm_model:
        layers.append(
            LlmPolicy(LlmClient(settings.vlm_base_url, settings.vlm_api_key, settings.vlm_model))
        )

    dev = _make_device(device)
    engine = Engine(settings, Router(layers), dev)
    try:
        engine.run(max_ticks=max_ticks or None)
    except KeyboardInterrupt:
        console.print("[yellow]已停止[/yellow]")


if __name__ == "__main__":
    app()
