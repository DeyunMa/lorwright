"""决策接口：每一层（规则 / JEV / LLM）都实现同一个 Protocol。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from lorwright.models import Action, GameState


@runtime_checkable
class Policy(Protocol):
    """策略接口。

    约定：
      - 只读 state，返回语义动作
      - 返回 None 表示「弃权」，交给下一层
      - 不允许访问截图、鼠标、文件、网络
    """

    name: str
    version: str

    def decide(self, state: GameState) -> Action | None: ...
