# AGENTS.md

本文件是 AI agent 的项目入口：只放持续适用的目标和约束，进度、环境和详细设计放在链接的文档中。

## 项目目标

将基于视觉的《符文大地传说》英雄之路自动化工具跑通。最终目标是让程序**全自动完成从设备就绪、启动模拟器和游戏、登录，到进入冒险、路线移动、进入并完成战斗、结算、奖励、治疗及其他节点的整个流程**；基础目标是让 **Jinx 和 Elise 分别自动完成整个冒险**。Agent 主要通过 CLI 查询日志、状态和操作程序，遇阻时修改代码并验证，使自动化能力持续完善。当前实现和实机验证范围见 [`docs/handoff.md`](docs/handoff.md) 和 [`docs/status.md`](docs/status.md)；目标不代表已经实现。

优先建设所有英雄可复用的感知、决策和操作能力，再由英雄包提供必要的专属规则。冒险中会加入新卡，不能以提前登记所有手牌为完成基础目标的前提；无法可靠判断时应停下并补足通用能力，而不是盲点。

## 从这里开始

- 接手时先读 [`docs/handoff.md`](docs/handoff.md) 的最新接手入口和 [`docs/status.md`](docs/status.md)；历史记录不等于当前状态。
- 按任务查阅 [`docs/environment.md`](docs/environment.md)（f1、模拟器和 ADB）、[`docs/champions/elise.md`](docs/champions/elise.md)（Elise 决策）、[`docs/adr/`](docs/adr/)（架构决策）。现有实现与实测证据优先于过时的设计描述。
- 实战开发先通过 CLI 查询阶段、等待、进展和停止原因，见 [`docs/cli.md`](docs/cli.md)；需要定位视觉问题时再看关联截图。没有活动实例时先确认当前画面，让程序处理已支持步骤；遇阻后用截图和事件补能力、离线验证，同步后继续。画面变化影响下一步时，简短说明观察和下一步。
- 修改只针对当前目标和观察到的问题；区分离线图片回放、局部实机操作和完整冒险验证，不把其中一种说成另一种。

## 必须遵守

1. **英雄之路没有官方状态 API。** `localhost:21337` 覆盖收藏、构筑和 PvP，不能用来获取 PoC 状态，见 [ADR 0002](docs/adr/0002-vision-only-perception.md)。
2. **ADB 是主路径**（手机或模拟器），Windows 桌面模式仅用于调试回退，见 [ADR 0003](docs/adr/0003-adb-over-desktop.md)。不读写游戏内存、不修改游戏文件、不绕过反作弊。
3. **手机版出牌用带停顿的拖拽。** 展开手牌后执行「按住 → 停顿 → 拖 → 松手」，使用 `device/touch.py` 的事件级后端；点击出牌和 `input swipe` 不能替代这个手势。
4. **状态未知不点击。** `UNKNOWN` 的兜底是 `NO_OP`；只有确定处于 `MY_TURN_IDLE` 且各策略均弃权时才结束回合。不可为了继续流程盲点。
5. **坐标和模板按设计尺寸标定。** `config.screen` 当前为 1920×1080；`perceive/normalize.py` 负责截图归一化和动作坐标反算。f1 Pie64 的分辨率设置见环境文档。
6. **保留 f1 的独立改动。** 使用用户指定的 Tailscale 和系统 SSH；同步前核对待覆盖文件，备份已有内容并在同步后校验。实时操作前重新确认画面。

## 代码边界

`device → perceive → decide → act → loop`：设备负责截图和输入，感知只读画面，决策只产生语义动作，执行层将动作转换为坐标和手势，循环负责编排。决策层不能截图、控制鼠标或直接生成坐标。

- `core/` 包含自动化基础能力与英雄包，`cli/` 提供命令行入口；后续 GUI 使用同一核心。`core/runtime/` 只管运行会话、观测与协作停止，不做感知或打法决策。英雄规则、牌表和偏好放在 `core/champions/<name>/`；通用决策与模型不包含具体英雄知识。新英雄应通过英雄包接入，不为单个英雄改通用层。
- 每层决策可以弃权；确定没有优先权时返回 `NO_OP`，避免继续执行通用层。配置中的 `layout` 和 `champion` 优先于硬编码。
- 测试不依赖游戏：用合成图和保存的实拍截图验证感知及决策，包括误识别和遮挡等安全负例。
- 不提前引入 GUI、Playwright/Selenium 或插件系统；优先跑通现有 CLI 与英雄包。

## 常用命令

```bash
pip install -e ".[dev]"
pytest
ruff check src tests tools
lorwright doctor
lorwright devices
lorwright probe
lorwright shot --out x.png
lorwright run --max-ticks 50 --device adb
```
