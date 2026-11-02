# ADR-0001：插件化规则系统（延后实现）

- 状态：**Proposed / Deferred**
- 日期：2026-11-02

## 背景

长期设想：`lorwright` 作为"底壳"（感知 + 执行 + 主循环），
规则以插件形式提供，不同用户可以为不同卡组/英雄编写插件并分享。

## 决策

**现阶段不实现插件系统。** 先让一个卡组（蜘蛛女皇快攻）跑通。

但**接口按插件形态设计**，避免以后重构：

```python
class Policy(Protocol):
    name: str                 # "elise_aggro"
    version: str              # "0.1.0"
    compatible_core: str      # ">=0.1,<0.2"
    decks: list[str]          # 适用的卡组代码

    def decide(self, state: GameState) -> Action | None:
        """返回 None = 弃权，交给下一层（JEV / LLM）"""
```

约束：
- 插件是**纯函数**：只读 `state`，返回 `Action`
- 插件**不能**调用 21337 API、不能截屏、不能点击、不能访问文件/网络
- 好处：可单元测试、可沙箱、可审计

## 后续步骤（跑通之后）

1. 把内置规则物理拆到 `plugins/elise_aggro/`
2. 定义插件加载器（目录扫描 + 版本校验）
3. 再决定：单仓库 monorepo（默认）还是独立仓库

## 后果

- 现在：少量额外设计成本（定义 `Policy` 接口）
- 以后：无需重写决策层，直接加载插件
- 风险：接口可能仍需调整，但影响面被限制在 `decide/` 一层
