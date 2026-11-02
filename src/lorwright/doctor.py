"""环境自检：在跑 bot 之前，先确认环境是否就绪。

设计目标：每条检查都给出「怎么办」，而不是只说失败。
"""

from __future__ import annotations

import platform
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

    # 1. Python 版本
    v = sys.version_info
    checks.append(
        Check(
            "Python >= 3.11",
            v >= (3, 11),
            f"{v.major}.{v.minor}.{v.micro}",
            "升级 Python：https://www.python.org/downloads/",
        )
    )

    # 2. 平台
    checks.append(
        Check(
            "Windows 平台",
            platform.system() == "Windows",
            platform.system(),
            "本项目在 Windows 上运行（macOS 只能跑单测）",
            optional=True,
        )
    )

    # 3. 依赖
    for mod, pkg in [
        ("cv2", "opencv-python"),
        ("mss", "mss"),
        ("pynput", "pynput"),
        ("loguru", "loguru"),
        ("pydantic", "pydantic"),
    ]:
        checks.append(
            Check(
                f"依赖 {pkg}",
                _has_module(mod),
                "已安装" if _has_module(mod) else "缺失",
                f"pip install {pkg}",
            )
        )

    # 4. 素材
    buttons = list((r / "assets" / "buttons").glob("*.png"))
    cards = list((r / "assets" / "cards").glob("*.png"))
    checks.append(
        Check(
            "按钮模板",
            len(buttons) >= 2,
            f"{len(buttons)} 张",
            "至少需要 end_turn.png + victory.png，见 issue #2",
        )
    )
    checks.append(
        Check(
            "卡牌图库",
            len(cards) >= 10,
            f"{len(cards)} 张",
            "用 tools/collect_cards.py 采集，见 issue #3",
        )
    )

    # 5. Layout
    lay = settings.layout.to_layout()
    checks.append(
        Check(
            "Layout 已标定",
            bool(lay.end_turn and lay.play_area),
            "就绪" if (lay.end_turn and lay.play_area) else "未标定",
            "在 config/settings.yaml 的 layout 段填 \\[x,y,w,h\\]，见 issue #2",
        )
    )

    # 6. 可选服务
    checks.append(
        Check(
            "JEV 已配置",
            bool(settings.jev_base_url),
            settings.jev_base_url or "未配置",
            "可选；不配就只用规则层",
            optional=True,
        )
    )
    checks.append(
        Check(
            "LLM 已配置",
            bool(settings.vlm_base_url and settings.vlm_model),
            settings.vlm_model or "未配置",
            "可选；不配就只用规则层",
            optional=True,
        )
    )

    return checks


def format_checks(checks: list[Check]) -> str:
    lines = []
    for c in checks:
        if c.ok:
            mark = "✅"
        elif c.optional:
            mark = "⚠️ "
        else:
            mark = "❌"
        line = f"{mark} {c.name}: {c.detail}"
        if not c.ok and c.hint:
            line += f"\n   → {c.hint}"
        lines.append(line)
    return "\n".join(lines)


def blockers(checks: list[Check]) -> list[Check]:
    """必须修复的项（排除 optional）。"""
    return [c for c in checks if not c.ok and not c.optional]
