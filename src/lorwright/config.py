"""配置加载：config/settings.yaml + .env + 环境变量。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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
    #: 设计尺寸内单位声明攻击/格挡的最小上移量，过滤定位抖动。
    combat_row_min_move_px: int = 80
    #: 帧时效上限（秒）。截图+决策耗时超过它就放弃本帧（退 NO_OP），
    #: 避免拿着已经过时的画面去点。见 docs/maa/04-screencap.md
    max_frame_age_s: float = 2.0


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
    launch_mode: Literal["standard", "pie64_trace"] = "standard"


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
    #: 点手牌到展开动画结束的等待。收起态拖不动，出牌前必须先展开
    expand_wait_ms: int = 500


class LayoutConfig(BaseModel):
    """界面坐标，格式：[x, y, w, h]。留空表示未标定。"""

    end_turn: list[int] | None = None
    enemy_nexus: list[int] | None = None
    my_nexus: list[int] | None = None
    play_area: list[int] | None = None
    # 场上单位：靠卡面攻击力徽章定位（perceive/units.py）
    my_board: list[int] | None = None
    my_combat: list[int] | None = None
    enemy_board: list[int] | None = None
    # 攻击声明落点：把单位拖到分隔线上方这一带，单位会吸附到攻击行
    attack_row: list[int] | None = None
    # 攻击令牌箭头（动作按钮左侧的橙色箭头）
    attack_token: list[int] | None = None
    enemy_combat: list[int] | None = None
    cancel_point: list[int] | None = None
    hand_region: list[int] | None = None
    hand_expanded: list[int] | None = None
    enemy_hp: list[int] | None = None
    my_hp: list[int] | None = None
    mana: list[int] | None = None
    login_splash: list[int] | None = None
    login_username: list[int] | None = None
    login_password: list[int] | None = None
    login_submit: list[int] | None = None

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
            my_board=self._rect(self.my_board),
            my_combat=self._rect(self.my_combat),
            enemy_board=self._rect(self.enemy_board),
            attack_row=self._rect(self.attack_row),
            attack_token=self._rect(self.attack_token),
            enemy_combat=self._rect(self.enemy_combat),
            cancel_point=self._rect(self.cancel_point),
            hand_region=self._rect(self.hand_region),
            hand_expanded=self._rect(self.hand_expanded),
            enemy_hp=self._rect(self.enemy_hp),
            my_hp=self._rect(self.my_hp),
            mana=self._rect(self.mana),
            login_splash=self._rect(self.login_splash),
            login_username=self._rect(self.login_username),
            login_password=self._rect(self.login_password),
            login_submit=self._rect(self.login_submit),
        )


@dataclass
class AdventureConfig:
    # 节点面板：旅行/戰鬥按钮共用区域（1920x1080 实测）
    travel: list[int] | None = None
    # Boss 面板右下的戰鬥按钮
    battle_confirm: list[int] | None = None
    # 战斗胜利后的继续按钮
    victory_continue: list[int] | None = None
    # 商店左下離開
    shop_leave: list[int] | None = None
    # 休息面板第一个选项（待实机校准）
    rest_first_option: list[int] | None = None
    # 一场战斗的引擎 tick 预算
    battle_max_ticks: int = 400



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
    adventure: AdventureConfig = Field(default_factory=AdventureConfig)

    # 可选外部服务（来自环境变量）

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

    data.setdefault("lor_username", _env("LOR_USERNAME"))
    data.setdefault("lor_password", _env("LOR_PASSWORD"))

    return Settings(**data)
