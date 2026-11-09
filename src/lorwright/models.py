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
    MULLIGAN = "mulligan"            # 起手换牌：有「確定」按钮，还没进对局
    MY_TURN_IDLE = "my_turn_idle"      # 可以出牌
    BLOCKING = "blocking"              # 对手在攻击，等我方声明格挡（手牌拖不动）
    TARGETING = "targeting"            # 已选牌，等待选目标
    ENEMY_TURN = "enemy_turn"          # 对手行动中
    COMBAT_RESOLVING = "combat_resolving"
    BATTLE_END = "battle_end"


class ActionType(StrEnum):
    PLAY_CARD = "play_card"
    ATTACK = "attack"
    BLOCK = "block"          # 声明格挡：把单位拖到敌方攻击单位上
    CONFIRM = "confirm"      # 点动作按钮确认（攻擊/格擋声明后的「確認」）
    END_TURN = "end_turn"
    SELECT_TARGET = "select_target"  # 「選擇目標」：点一个单位完成选择
    CANCEL = "cancel"        # 退出「選擇目標」：点战场空白处收回已选的牌
    MULLIGAN_REPLACE = "mulligan_replace"  # 起手换牌：点若干张「替換」
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


@dataclass(frozen=True)
class Reading:
    """数值的最近观测；None 表示从未读到，age_frames=0 才是本帧。"""

    value: int | None = None
    age_frames: int | None = None

    @property
    def fresh(self) -> bool:
        return self.value is not None and self.age_frames == 0


@dataclass
class GameState:
    ui_state: UIState = UIState.UNKNOWN
    turn: int = 0
    mana: int = 0
    max_mana: int = 0
    hand: list[CardInHand] = field(default_factory=list)
    #: 起手换牌界面的 4 张牌；rect 是「替換」按钮中心，用于点选。
    mulligan_cards: list[CardInHand] = field(default_factory=list)
    #: 手牌是否处于展开态。收起态卡片斜叠、只露左边缘，**拖不动**；
    #: 必须先 tap 展开才能拖出牌（2026-11-04 实测）
    hand_expanded: bool = False
    my_units: list[Unit] = field(default_factory=list)
    enemy_units: list[Unit] = field(default_factory=list)
    # 格挡阶段站在敌方攻击行里的单位（perceive 按区域过滤）
    enemy_attackers: list[Unit] = field(default_factory=list)
    nexus_hp: int = 20
    enemy_nexus_hp: int = 20
    has_attack_token: bool = False
    # 伊莉丝升级后我方全体蜘蛛获得挑战者，攻击声明由攻方指定格挡者
    my_units_have_challenger: bool = False
    #: 数字字段的观测证据；旧值仅供展示，不代表本帧仍然有效。
    readings: dict[str, Reading] = field(default_factory=dict)

    def has_fresh_readings(self, *names: str) -> bool:
        return all(name in self.readings and self.readings[name].fresh for name in names)

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
    my_nexus: Rect | None = None
    play_area: Rect | None = None
    # 场上单位区域（靠攻击力徽章定位）
    my_board: Rect | None = None
    my_combat: Rect | None = None
    enemy_board: Rect | None = None
    # 攻击声明落点（分隔线上方）
    attack_row: Rect | None = None
    # 攻击令牌箭头（动作按钮左侧）
    attack_token: Rect | None = None
    # 敌方攻击行（BLOCKING 时在这里的单位视为攻击者）
    enemy_combat: Rect | None = None
    # 取消选目标的落点：战场左侧空白，点这里会把手上的牌收回去
    cancel_point: Rect | None = None
    hand_region: Rect | None = None
    hand_expanded: Rect | None = None
    enemy_hp: Rect | None = None
    my_hp: Rect | None = None
    mana: Rect | None = None
    # 登录界面（splash 按钮 / 用户名 / 密码 / 提交）
    login_splash: Rect | None = None
    login_username: Rect | None = None
    login_password: Rect | None = None
    login_submit: Rect | None = None
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
    drag_hold_ms: int = 0
    drags: tuple[tuple[tuple[int, int], tuple[int, int]], ...] = ()
