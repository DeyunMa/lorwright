"""环境自检：跑 bot 之前先确认环境就绪。"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from lorwright.config import Settings


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    hint: str = ""
    optional: bool = False


def _has_module(name: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(name) is not None


def run_checks(settings: Settings, root: str | Path = ".") -> list[Check]:
    r = Path(root)
    checks: list[Check] = []

    v = sys.version_info
    checks.append(
        Check("Python >= 3.11", v >= (3, 11), f"{v.major}.{v.minor}.{v.micro}",
              "升级 Python：https://www.python.org/downloads/")
    )

    # ADB
    adb_ok = shutil.which(settings.adb.adb_path) is not None
    checks.append(
        Check("adb 可用", adb_ok, settings.adb.adb_path if adb_ok else "未找到",
              "brew install android-platform-tools / winget install Google.PlatformTools")
    )

    device = None
    if adb_ok:
        from lorwright.device.adb import AdbDevice

        serials = AdbDevice.list_devices(
            settings.adb.adb_path, connect=settings.adb.serial or None
        )
        checks.append(
            Check("ADB 设备", bool(serials), f"{len(serials)} 台: {', '.join(serials[:3])}" if serials else "未连接",
                  "手机开 USB 调试并允许；模拟器先启动")
        )
        if serials:
            device = AdbDevice(
                serial=settings.adb.serial or None, adb=settings.adb.adb_path
            )

    # 分辨率 / 输入通道 / 登录态：都要真连上设备才查得了
    if device is not None:
        checks.extend(_device_checks(settings, device))

    # 依赖（核心）
    for mod, pkg in [("cv2", "opencv-python"), ("numpy", "numpy"),
                     ("loguru", "loguru"), ("pydantic", "pydantic")]:
        ok = _has_module(mod)
        checks.append(Check(f"依赖 {pkg}", ok, "已安装" if ok else "缺失", f"pip install {pkg}"))

    # 依赖（桌面模式，可选）
    for mod, pkg in [("mss", "mss"), ("pynput", "pynput")]:
        ok = _has_module(mod)
        checks.append(
            Check(f"依赖 {pkg}（桌面模式）", ok, "已安装" if ok else "缺失",
                  f"pip install {pkg}（只在 --device desktop 时需要）", optional=True)
        )

    # 素材
    for name, hint in [
        ("mulligan.png", "起手换牌识别，缺了会把换牌判成我方回合"),
        ("action_pass.png", "动作按钮「略過」"),
        ("action_commit.png", "动作按钮「結算」"),
    ]:
        p = r / "assets" / "buttons" / name
        checks.append(Check(f"模板 {name}", p.exists(), "存在" if p.exists() else "缺失", hint))
    for name in ["login_splash.png", "login_form.png"]:
        p = r / "assets" / "ui" / name
        checks.append(Check(f"模板 {name}", p.exists(), "存在" if p.exists() else "缺失",
                            "登录界面识别"))

    buttons = list((r / "assets" / "buttons").glob("*.png"))
    cards = list((r / "assets" / "cards").glob("*.png"))
    checks.append(Check("按钮模板", len(buttons) >= 3, f"{len(buttons)} 张",
                        "起手换牌 + 动作按钮文字"))
    checks.append(
        Check("卡牌图库", len(cards) >= 10, f"{len(cards)} 张",
              "用 tools/collect_cards.py 采集，见 issue #3", optional=True)
    )

    # Layout
    lay = settings.layout.to_layout()
    ready = bool(lay.end_turn and lay.play_area)
    checks.append(Check("Layout 已标定", ready, "就绪" if ready else "未标定",
                        "在 config/settings.yaml 的 layout 段填 [x,y,w,h]，见 issue #2"))

    # 可选服务

    return checks


def _device_checks(settings: Settings, device) -> list[Check]:
    """连上设备后才能做的检查：分辨率、输入后端、登录态。"""
    out: list[Check] = []
    try:
        size = device.size()
    except Exception as e:  # noqa: BLE001 - 自检要能报出任何失败
        out.append(Check("截图", False, f"{type(e).__name__}: {e}", "确认设备已连接、未锁屏"))
        return out

    design = (settings.screen.width, settings.screen.height)
    out.append(
        Check(
            "截图", True, f"{size[0]}x{size[1]}",
        )
    )
    out.append(
        Check(
            "分辨率", True,
            f"{size[0]}x{size[1]}（设计 {design[0]}x{design[1]}，会归一化）"
            if size != design
            else f"{size[0]}x{size[1]} = 设计尺寸",
        )
    )

    # 输入后端：能不能表达「按住再拖」决定出牌能不能做
    try:
        surface = device.surface()
        hold = getattr(surface, "can_hold", False)
        node = getattr(getattr(surface, "device", None), "node", "")
        out.append(
            Check(
                "输入后端", hold,
                f"{type(surface).__name__}{' @' + node if node else ''}"
                + ("（可停顿）" if hold else "（只能原子手势，出牌会失败）"),
                "shell 需要在 input 组里才能写 /dev/input/eventN",
            )
        )
    except Exception as e:  # noqa: BLE001
        out.append(Check("输入后端", False, f"{type(e).__name__}: {e}", "检查 adb 权限"))

    # 前台是不是 LoR：不在游戏里时，下面所有感知结论都没有意义
    package = settings.adb.package
    try:
        focus = device.current_focus()
    except Exception as e:  # noqa: BLE001
        focus = f"{type(e).__name__}: {e}"
    in_game = package in focus
    out.append(
        Check(
            "游戏在前台", in_game,
            "是" if in_game else (focus[-60:] or "取不到前台窗口"),
            "跑 `lorwright launch` 启动游戏",
        )
    )
    if not in_game:
        return out

    # 登录态：卡在登录页时 ui_state 只能是 UNKNOWN，会表现为「什么都不做」
    try:
        from lorwright.perceive.login import LoginDetector, LoginScreen

        det = LoginDetector()
        det.load()
        kind = det.detect(device.screencap().image)
        out.append(
            Check(
                "登录态", kind is LoginScreen.NONE,
                {"none": "已登录", "splash": "停在登录页",
                 "form": "停在账号密码表单"}[kind.value],
                "跑 `lorwright login`（账号从 .env 的 LOR_USERNAME/LOR_PASSWORD 读）",
            )
        )
    except Exception as e:  # noqa: BLE001
        out.append(Check("登录态", False, f"{type(e).__name__}: {e}", "检查 assets/ui/login_*.png"))

    return out


def format_checks(checks: list[Check]) -> str:
    lines = []
    for c in checks:
        # Windows 控制台是 GBK，emoji 会直接抛 UnicodeEncodeError
        mark = "[ok]" if c.ok else ("[--]" if c.optional else "[!!]")
        line = f"{mark} {c.name}: {c.detail}"
        if not c.ok and c.hint:
            line += f"\n   → {c.hint}"
        lines.append(line)
    return "\n".join(lines)


def blockers(checks: list[Check]) -> list[Check]:
    return [c for c in checks if not c.ok and not c.optional]
