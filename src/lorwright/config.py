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


class RecoveryConfig(BaseModel):
    """卡住后的恢复行为。

    ``restart_app`` 会清掉登录态（回到 Riot 登入页），而自动登录还没做，
    所以默认禁止：卡住就停下等人，而不是把「卡住」升级成「要人工登录」。
    """

    #: 允许重启游戏客户端。打开前必须已经有自动登录。
    allow_client_restart: bool = False


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


class ActConfig(BaseModel):
    """动作参数。LoR 手机版对手势时长很挑，所以时长进配置而不是硬编码。"""

    #: 拖拽时长（毫秒）。<1200 会被游戏当成滑动取消，不出牌。
    drag_ms: int = 800
    #: 按下到开始移动之间的停顿。LoR 出牌必须是「按住 → 停一下 → 拖」，
    #: 不停顿会被当成点击/长按预览（docs/handoff.md §4.6）。
    drag_hold_ms: int = 300
    #: 拖拽后等画面稳定
    drag_wait_ms: int = 600
    #: 单次点击后等待
    tap_wait_ms: int = 400


class LayoutConfig(BaseModel):
    """界面坐标，格式：[x, y, w, h]。留空表示未标定。"""

    end_turn: list[int] | None = None
    enemy_nexus: list[int] | None = None
    my_nexus: list[int] | None = None
    play_area: list[int] | None = None
    hand_region: list[int] | None = None
    # 数字区域：水晶血量、法力
    enemy_hp: list[int] | None = None
    my_hp: list[int] | None = None
    mana: list[int] | None = None

    @staticmethod
    def _rect(v: list[int] | None) -> Rect | None:
        if not v or len(v) != 4:
            return None
        return Rect(*v)

    def to_layout(self) -> Layout:
        return Layout(
            end_turn=self._rect(self.end_turn),
            enemy_nexus=self._rect(self.enemy_nexus),
            my_nexus=self._rect(self.my_nexus),
            play_area=self._rect(self.play_area),
            hand_region=self._rect(self.hand_region),
            enemy_hp=self._rect(self.enemy_hp),
            my_hp=self._rect(self.my_hp),
            mana=self._rect(self.mana),
        )


class Settings(BaseModel):
    #: 英雄包名，对应 `champions/<name>/` 目录
    champion: str = "elise"
    screen: ScreenConfig = Field(default_factory=ScreenConfig)
    perception: PerceptionConfig = Field(default_factory=PerceptionConfig)
    loop: LoopConfig = Field(default_factory=LoopConfig)
    act: ActConfig = Field(default_factory=ActConfig)
    recovery: RecoveryConfig = Field(default_factory=RecoveryConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    layout: LayoutConfig = Field(default_factory=LayoutConfig)
    adb: AdbConfig = Field(default_factory=AdbConfig)

    # 可选外部服务（来自环境变量）
    vlm_base_url: str | None = None
    vlm_api_key: str | None = None
    vlm_model: str | None = None
    jev_base_url: str | None = None
    jev_api_key: str | None = None

    # 游戏账号（来自环境变量，仅用于自动登录；不入库）
    lor_username: str | None = None
    lor_password: str | None = None

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
    data.setdefault("lor_username", _env("LOR_USERNAME"))
    data.setdefault("lor_password", _env("LOR_PASSWORD"))

    return Settings(**data)
