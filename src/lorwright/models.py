"""共享数据模型：状态、动作、几何。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.w // 2, self.y + self.h // 2)

    @property
    def area(self) -> int:
        return self.w * self.h


class UIState(StrEnum):
    UNKNOWN = "unknown"
    MY_TURN_IDLE = "my_turn_idle"      # 可以出牌
    TARGETING = "targeting"            # 已选牌，等待选目标
    ENEMY_TURN = "enemy_turn"          # 对手行动中
    COMBAT_RESOLVING = "combat_resolving"
    BATTLE_END = "battle_end"


class ActionType(StrEnum):
    PLAY_CARD = "play_card"
    ATTACK = "attack"
    END_TURN = "end_turn"
    PASS = "pass"


@dataclass(frozen=True)
class Action:
    """语义动作 —— 决策层输出，执行层负责翻译成鼠标操作。"""

    type: ActionType
    card_index: int | None = None     # 手牌序号（0 = 最左）
    target: str | None = None         # "nexus" 或单位标识
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CardInHand:
    index: int
    name: str
    cost: int
    rect: Rect


@dataclass(frozen=True)
class Unit:
    name: str
    attack: int
    health: int
    rect: Rect
    can_attack: bool = True


@dataclass
class GameState:
    ui_state: UIState = UIState.UNKNOWN
    turn: int = 0
    mana: int = 0
    max_mana: int = 0
    hand: list[CardInHand] = field(default_factory=list)
    my_units: list[Unit] = field(default_factory=list)
    enemy_units: list[Unit] = field(default_factory=list)
    nexus_hp: int = 20
    enemy_nexus_hp: int = 20

    def summary(self) -> str:
        return (
            f"[{self.ui_state.value}] T{self.turn} "
            f"mana={self.mana}/{self.max_mana} "
            f"hand={len(self.hand)} my={len(self.my_units)} "
            f"enemy={len(self.enemy_units)} hp={self.nexus_hp}/{self.enemy_nexus_hp}"
        )


@dataclass
class Layout:
    """界面上各区域的坐标（由配置或感知层提供）。"""

    end_turn: Rect | None = None
    enemy_nexus: Rect | None = None
    play_area: Rect | None = None
    hand_region: Rect | None = None
    extras: dict[str, Rect] = field(default_factory=dict)


@dataclass(frozen=True)
class ClickPlan:
    """一次动作需要执行的点击序列。"""

    points: list[tuple[int, int]]
    wait_ms: int = 400
