"""英雄包注册表：按名字动态加载 `lorwright.champions.<name>`。

加英雄不需要改这里 —— 丢一个目录进来就能被 `available()` 发现。
"""

from __future__ import annotations

import importlib
import pkgutil

from lorwright.champions.base import ChampionPack

#: 没配置 `champion` 时用哪个
DEFAULT = "elise"


def available() -> list[str]:
    """已安装的英雄包名字。"""
    return sorted(m.name for m in pkgutil.iter_modules(__path__) if m.ispkg)


def load(name: str | None = None) -> ChampionPack:
    """按名字加载英雄包。名字非法或包不存在时抛 ValueError。"""
    target = (name or DEFAULT).strip()
    if not target:
        target = DEFAULT
    if target not in available():
        raise ValueError(f"未知英雄包 {target!r}，可选：{', '.join(available())}")

    module = importlib.import_module(f"lorwright.champions.{target}")
    pack = getattr(module, "PACK", None)
    if pack is None:
        raise ValueError(f"英雄包 {target!r} 没有暴露 PACK")
    return pack
