# AGENTS.md

给在本仓库工作的 AI agent 的规则。人类可读，但主要写给 agent。

## 这是什么

基于视觉的《符文大地传说》**英雄之路（Path of Champions）**自动化工具，Windows 上运行。

## 三条硬约束（先读这个，否则会走错方向）

1. **英雄之路没有官方 API。** `localhost:21337` 只覆盖收藏/构筑/PvP，
   PoC 至今无 API（见 `docs/adr/0002`）。**不要尝试接 API 做 PoC 状态。**
2. **必须 1920×1080 全屏 + 显示缩放 100%。** 模板与坐标按此采集，改分辨率就全错。
3. **出牌用「点击出牌」模式**（游戏设置里开），不要实现拖拽为主路径。

## 命令

```bash
pip install -e ".[dev]"     # 安装
pytest                      # 28 个单测（不需要游戏）
ruff check src tests tools  # 静态检查
lorwright doctor            # 环境自检
lorwright probe             # 截一帧 + 识别 UI 状态
lorwright capture --out x.png
lorwright run --max-ticks 50
```

## 架构

```
perceive（截图/模板匹配/OCR） → decide（规则→JEV→LLM） → act（点击） → loop（主循环+看门狗）
```

| 目录 | 职责 | 关键约定 |
|---|---|---|
| `models.py` | 数据契约 | `GameState` / `Action` / `Layout`，**决策层不碰坐标** |
| `perceive/` | 感知 | 只读截图，不产生动作 |
| `decide/` | 决策 | 每层实现 `decide(state) -> Action | None`，**None = 弃权** |
| `act/` | 执行 | 语义动作 → 点击序列 |
| `loop/` | 编排 | 主循环、看门狗、恢复策略 |

## 设计约定

- **决策层只产出语义动作**（`PlayCard(card_index=2)`），不产出坐标。
  坐标由 `act/translate.py` 负责，这样决策逻辑可以脱离屏幕单测。
- **每层都能弃权。** 规则覆盖 70–80%，JEV 补 15–25%，LLM 只兜底 1–5%。
  新规则优先加在 `decide/rules.py`，不要一上来就调模型。
- **配置优先于硬编码。** 坐标放 `config/settings.yaml` 的 `layout` 段。
- **测试不依赖游戏。** 用合成图像（`test_locate.py`）和 mock HTTP（`test_jev_fallback.py`）。

## 不要做

- ❌ 不引入 GUI（先做 CLI + 日志；可视化需求用 `rich`）
- ❌ 不引入 Playwright/Selenium（这不是浏览器自动化）
- ❌ 不读写游戏内存、不改游戏文件、不绕过反作弊
- ❌ 不把插件系统提前实现（见 `docs/adr/0001`，先跑通一个卡组）
- ❌ 不在 `decide/` 里调用截图或鼠标（破坏可测试性）

## 当前状态

见 `docs/status.md`。打开的 issue 在 GitHub Issues，标签 `p0/p1/p2`。
