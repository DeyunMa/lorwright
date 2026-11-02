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

from typing import Protocol, runtime_checkable

from lorwright.decide.base import Policy
from lorwright.decide.card import CardDef


@runtime_checkable
class ChampionPack(Protocol):
    """一个英雄的完整描述。"""

    #: 目录名，也是 `settings.yaml` 里 `champion` 的值
    name: str

    #: 展示名
    display_name: str

    #: 牌表（感知层采模板、文档生成都可以用它）
    deck: tuple[CardDef, ...]

    def make_policy(self) -> Policy:
        """构造这个英雄的 L1 规则层策略。"""
        ...
