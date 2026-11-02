"""CLI 入口：probe / capture / run。"""

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


@app.command()
def probe() -> None:
    """截一帧，识别 UI 状态并打印（验证环境是否就绪）。"""
    from lorwright.perceive.capture import ScreenCapture
    from lorwright.perceive.ui_state import UIStateDetector

    settings = load_settings()
    cap = ScreenCapture(settings.screen.width, settings.screen.height)
    det = UIStateDetector(threshold=settings.perception.match_threshold)
    det.load()

    shot = cap.grab()
    state = det.detect(shot.frame)
    cap.close()

    table = Table(title="环境探测")
    table.add_column("项目")
    table.add_column("值")
    table.add_row("分辨率", f"{shot.frame.shape[1]}x{shot.frame.shape[0]}")
    table.add_row("UI 状态", state.value)
    table.add_row("按钮模板数", str(len(det._tpl)))  # noqa: SLF001
    table.add_row("配置", f"{settings.screen.width}x{settings.screen.height}")
    console.print(table)

    if not det._tpl:  # noqa: SLF001
        console.print("[yellow]提示：assets/buttons/ 为空，先放按钮模板再跑 run[/yellow]")


@app.command()
def capture(out: str = "logs/probe.png") -> None:
    """截一帧保存到文件（用于采集模板）。"""
    from lorwright.perceive.capture import ScreenCapture

    settings = load_settings()
    cap = ScreenCapture(settings.screen.width, settings.screen.height)
    frame = cap.grab().frame
    cap.close()

    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    import cv2

    cv2.imwrite(str(path), frame)
    console.print(f"[green]已保存[/green] {path}")


@app.command()
def run(max_ticks: int = typer.Option(0, help="最大循环次数，0 = 无限")) -> None:
    """运行主循环（默认无限，Ctrl+C 停止）。"""
    from lorwright.decide.rules import SpiderAggroPolicy
    from lorwright.loop.engine import Engine

    settings = load_settings()
    engine = Engine(settings, SpiderAggroPolicy())
    try:
        engine.run(max_ticks=max_ticks or None)
    except KeyboardInterrupt:
        console.print("[yellow]已停止[/yellow]")


if __name__ == "__main__":
    app()
