"""英雄包（ChampionPack）接口。

**一个英雄 = 一个目录** `champions/<name>/`，里面放：

    champions/elise/
      __init__.py    # 暴露 PACK
      deck.py        # 牌表 + 卡牌效果分类 + 卡名查找
      policy.py      # 这个英雄的决策策略

核心层（`decide/`、`perceive/`、`loop/`、`act/`）**不认识任何具体英雄**。
加一个英雄 = 加一个目录，不改核心 —— 这是 MAA 的资源包思路：
core 负责机制，resource pack 负责某个具体对象的知识。

约定：
  - 核心只依赖 `Policy` 协议和 `CardDef` 通用字段
  - 英雄专属的数据/评分/规则全在自己的目录里
  - 英雄包之间不互相 import
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from lorwright.decide.base import Policy
from lorwright.decide.card import CardDef


@dataclass(frozen=True)
class Preference:
    """奖励节点上的一条英雄偏好。

    `names` 是这个对象已知的全部写法（英文 + 繁中对照，来自游戏
    本地化数据），识别层拿到展示名后按元组内容匹配；`note` 记录
    用户给这条偏好的理由，供文档和后续调优用。
    """

    names: tuple[str, ...]
    note: str = ""


@runtime_checkable
class ChampionPack(Protocol):
    """一个英雄的完整描述。"""

    #: 目录名，也是 `settings.yaml` 里 `champion` 的值
    name: str

    #: 展示名
    display_name: str

    #: 牌表（感知层采模板、文档生成都可以用它）
    deck: tuple[CardDef, ...]

    # ---- 奖励节点偏好（2026-11-05 用户确认）----
    # 默认规则：偏好未命中时按「品质优先，其次费用」排序；
    # 英雄包里的偏好永远压过默认规则。偏好只是数据，
    # 节点 UI 自动化建好后由奖励决策读取。

    #: 圣物：英雄开局自带的装备（选择/替换圣物时按此偏好）
    relic_preferences: tuple[Preference, ...]

    #: 道具节点：给卡组里已有卡牌选道具
    item_preferences: tuple[Preference, ...]

    #: 法术节点：新选一个法术进卡组
    spell_preferences: tuple[Preference, ...]

    #: 能力（菱形节点）：选择星力/能力
    power_preferences: tuple[Preference, ...]

    def make_policy(self) -> Policy:
        """构造这个英雄的 L1 规则层策略。"""
        ...
