"""配置加载：config/settings.yaml + 环境变量。"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class ScreenConfig(BaseModel):
    width: int = 1920
    height: int = 1080
    dpi_scale: int = 100
    window_title: str = "Legends of Runeterra"


class PerceptionConfig(BaseModel):
    match_threshold: float = 0.85
    snapshot_dir: str = "logs/snapshots"


class LoopConfig(BaseModel):
    tick_ms: int = 200
    stuck_threshold: int = 3
    action_timeout_s: float = 8.0


class LoggingConfig(BaseModel):
    dir: str = "logs"
    by_date: bool = True
    level: str = "INFO"


class Settings(BaseModel):
    screen: ScreenConfig = Field(default_factory=ScreenConfig)
    perception: PerceptionConfig = Field(default_factory=PerceptionConfig)
    loop: LoopConfig = Field(default_factory=LoopConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    # 可选的外部服务
    vlm_base_url: str | None = None
    vlm_api_key: str | None = None
    vlm_model: str | None = None
    jev_base_url: str | None = None
    jev_api_key: str | None = None


def load_settings(path: str | Path = "config/settings.yaml") -> Settings:
    """读取 YAML 配置；文件不存在时用默认值。"""
    p = Path(path)
    data: dict = {}
    if p.exists():
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return Settings(**data)
