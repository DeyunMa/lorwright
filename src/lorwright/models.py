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
    NO_OP = "no_op"          # 状态不明 → 什么都不做（安全默认）
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
    keywords: frozenset[str] = frozenset()
    stunned: bool = False


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
    has_attack_token: bool = False
    # 伊莉丝升级后我方全体蜘蛛获得挑战者，攻击声明由攻方指定格挡者
    my_units_have_challenger: bool = False

    def summary(self) -> str:
        return (
            f"[{self.ui_state.value}] T{self.turn} "
            f"mana={self.mana}/{self.max_mana} "
            f"hand={len(self.hand)} my={len(self.my_units)} "
            f"enemy={len(self.enemy_units)} hp={self.nexus_hp}/{self.enemy_nexus_hp}"
        )

    @property
    def spider_count(self) -> int:
        """场上蜘蛛数 —— buff 牌评分的关键变量。

        伊莉丝这套牌场上单位全是蜘蛛（含小蜘蛛 token），所以直接取单位数。
        将来换其他牌组时这里要改成按名字过滤。
        """
        return len(self.my_units)


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
    """一次动作需要执行的操作序列。

    drag=False：依次点击每个点（结束回合、选目标）
    drag=True ：从 points[0] 拖到 points[1]（出牌）
    drags      ：多段拖拽，每对 (起点, 终点) 依次执行（多个单位一起攻击）
    """

    points: list[tuple[int, int]]
    wait_ms: int = 400
    drag: bool = False
    drag_ms: int = 600
    drags: tuple[tuple[tuple[int, int], tuple[int, int]], ...] = ()
