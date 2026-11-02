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
    table.add_row("配置分辨率", f"{settings.screen.width}x{settings.screen.height}")
    table.add_row("Layout 标定", "✅ 就绪" if settings.layout_ready else "❌ 未标定")
    table.add_row("决策层", "rules" + ("" if not settings.jev_base_url else " → jev")
                  + ("" if not settings.vlm_base_url else " → llm"))
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

    router = Router(layers)
    engine = Engine(settings, router)
    try:
        engine.run(max_ticks=max_ticks or None)
    except KeyboardInterrupt:
        console.print("[yellow]已停止[/yellow]")


@app.command()
def doctor() -> None:
    """环境自检：依赖、素材、坐标、可选服务。"""
    from lorwright.doctor import blockers, format_checks, run_checks

    settings = load_settings()
    checks = run_checks(settings)
    console.print(format_checks(checks), markup=False)
    bad = blockers(checks)
    if bad:
        console.print(f"\n[yellow]{len(bad)} 项阻塞，先修这些[/yellow]")
    else:
        console.print("\n[green]必需项全部就绪[/green]")


if __name__ == "__main__":
    app()
