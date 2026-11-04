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
def state(device: str = typer.Option("adb", help="adb | desktop")) -> None:
    """解析当前画面，打印识别到的状态（调感知层用）。"""
    from lorwright.perceive.digits import DigitReader
    from lorwright.perceive.state import StateParser
    from lorwright.perceive.ui_state import UIStateDetector

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

    st = parser.parse(frame.image)
    table = Table(title="状态解析")
    table.add_column("字段")
    table.add_column("值")
    table.add_row("UI 状态", st.ui_state.value)
    table.add_row("法力", f"{st.mana}/{st.max_mana}")
    table.add_row("我方水晶", str(st.nexus_hp))
    table.add_row("敌方水晶", str(st.enemy_nexus_hp))
    table.add_row("手牌", str(len(st.hand)))
    if st.hand:
        table.add_row("手牌费用", ", ".join(str(c.cost) for c in st.hand))
    table.add_row("字形库", f"{sorted(parser.digits.digits)}")
    console.print(table)
    console.print(f"summary: {st.summary()}", markup=False)


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
    from lorwright.champions import load as load_champion
    from lorwright.decide.jev import JevClient
    from lorwright.decide.jev_policy import JevPolicy, LlmPolicy
    from lorwright.decide.llm import LlmClient
    from lorwright.decide.router import Router
    from lorwright.loop.engine import Engine

    settings = load_settings()
    pack = load_champion(settings.champion)
    console.print(f"英雄包：[bold]{pack.name}[/bold]（{pack.display_name}，{len(pack.deck)} 张牌）")

    layers: list = [pack.make_policy()]
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
