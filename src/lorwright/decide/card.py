"""卡牌的通用词汇：类型 + 静态定义。

这里**只放任何牌组都成立的字段**。英雄专属的字段（buff 数值、召唤数量、
效果分类）由 `champions/<name>/deck.py` 继承扩展 —— 核心层不认识任何具体牌组。

加英雄时不应该需要改这个文件。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CardKind(StrEnum):
    UNIT = "unit"
    SPELL = "spell"
    CHAMPION = "champion"


@dataclass(frozen=True)
class CardDef:
    """一张牌的静态数据。"""

    name: str
    name_en: str = ""
    cost: int = 0
    attack: int = 0
    health: int = 0
    kind: CardKind = CardKind.UNIT
    keywords: frozenset[str] = frozenset()

    @property
    def is_unit(self) -> bool:
        return self.kind in (CardKind.UNIT, CardKind.CHAMPION)
