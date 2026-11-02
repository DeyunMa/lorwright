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

    if adb_ok:
        from lorwright.device.adb import AdbDevice

        serials = AdbDevice.list_devices(settings.adb.adb_path)
        checks.append(
            Check("ADB 设备", bool(serials), f"{len(serials)} 台: {', '.join(serials[:3])}" if serials else "未连接",
                  "手机开 USB 调试并允许；模拟器先启动")
        )

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
    buttons = list((r / "assets" / "buttons").glob("*.png"))
    cards = list((r / "assets" / "cards").glob("*.png"))
    checks.append(Check("按钮模板", len(buttons) >= 2, f"{len(buttons)} 张",
                        "至少 end_turn.png + victory.png，见 issue #2"))
    checks.append(Check("卡牌图库", len(cards) >= 10, f"{len(cards)} 张",
                        "用 tools/collect_cards.py 采集，见 issue #3"))

    # Layout
    lay = settings.layout.to_layout()
    ready = bool(lay.end_turn and lay.play_area)
    checks.append(Check("Layout 已标定", ready, "就绪" if ready else "未标定",
                        "在 config/settings.yaml 的 layout 段填 [x,y,w,h]，见 issue #2"))

    # 可选服务
    checks.append(Check("JEV 已配置", bool(settings.jev_base_url),
                        settings.jev_base_url or "未配置", "可选；不配就只用规则层", optional=True))
    checks.append(Check("LLM 已配置", bool(settings.vlm_base_url and settings.vlm_model),
                        settings.vlm_model or "未配置", "可选；不配就只用规则层", optional=True))

    return checks


def format_checks(checks: list[Check]) -> str:
    lines = []
    for c in checks:
        mark = "✅" if c.ok else ("⚠️ " if c.optional else "❌")
        line = f"{mark} {c.name}: {c.detail}"
        if not c.ok and c.hint:
            line += f"\n   → {c.hint}"
        lines.append(line)
    return "\n".join(lines)


def blockers(checks: list[Check]) -> list[Check]:
    return [c for c in checks if not c.ok and not c.optional]
