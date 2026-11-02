"""配置加载：config/settings.yaml + .env + 环境变量。"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from lorwright.models import Layout, Rect


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


class AdbConfig(BaseModel):
    """ADB 设备配置。"""

    enabled: bool = True
    serial: str | None = None      # 留空 = 自动选第一个
    adb_path: str = "adb"
    package: str = "com.riotgames.legendsofruneterra"


class LayoutConfig(BaseModel):
    """界面坐标，格式：[x, y, w, h]。留空表示未标定。"""

    end_turn: list[int] | None = None
    enemy_nexus: list[int] | None = None
    play_area: list[int] | None = None
    hand_region: list[int] | None = None

    @staticmethod
    def _rect(v: list[int] | None) -> Rect | None:
        if not v or len(v) != 4:
            return None
        return Rect(*v)

    def to_layout(self) -> Layout:
        return Layout(
            end_turn=self._rect(self.end_turn),
            enemy_nexus=self._rect(self.enemy_nexus),
            play_area=self._rect(self.play_area),
            hand_region=self._rect(self.hand_region),
        )


class Settings(BaseModel):
    screen: ScreenConfig = Field(default_factory=ScreenConfig)
    perception: PerceptionConfig = Field(default_factory=PerceptionConfig)
    loop: LoopConfig = Field(default_factory=LoopConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    layout: LayoutConfig = Field(default_factory=LayoutConfig)
    adb: AdbConfig = Field(default_factory=AdbConfig)

    # 可选外部服务（来自环境变量）
    vlm_base_url: str | None = None
    vlm_api_key: str | None = None
    vlm_model: str | None = None
    jev_base_url: str | None = None
    jev_api_key: str | None = None

    @property
    def layout_ready(self) -> bool:
        lay = self.layout.to_layout()
        return bool(lay.end_turn and lay.play_area)


def _load_dotenv(path: str | Path = ".env") -> None:
    """极简 .env 解析（不引入额外依赖）。已存在的环境变量优先。"""
    p = Path(path)
    if not p.exists():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def _env(name: str) -> str | None:
    v = os.getenv(name)
    return v or None


def load_settings(path: str | Path = "config/settings.yaml") -> Settings:
    """读取 YAML + .env；环境变量覆盖 YAML 里的可选服务。"""
    _load_dotenv()

    p = Path(path)
    data: dict = {}
    if p.exists():
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}

    data.setdefault("vlm_base_url", _env("VLM_BASE_URL"))
    data.setdefault("vlm_api_key", _env("VLM_API_KEY"))
    data.setdefault("vlm_model", _env("VLM_MODEL"))
    data.setdefault("jev_base_url", _env("JEV_BASE_URL"))
    data.setdefault("jev_api_key", _env("JEV_API_KEY"))

    return Settings(**data)
