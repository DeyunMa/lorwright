# LoRwright

基于纯视觉的《符文大地传说》英雄之路（Path of Champions）自动化工具：截图 → 规则决策 → ADB 输入 → 结果验证 → 继续推进。名字致敬 Playwright（wright = 工匠），项目不依赖 Playwright。

当前英雄包为伊莉絲（Elise）和金克丝（Jinx）。目标是程序自主完成设备就绪、启动、登录及整个冒险，并让两位英雄分别全自动完成冒险；这一目标尚未端到端验证。

接手开发先读 [`docs/handoff.md`](docs/handoff.md)，能力与证据见 [`docs/status.md`](docs/status.md)。用户已授权本地修改验证、同步 f1 并继续；共享状态与动作阶段已开始渐进改造，实际版本和最后会话以交接页为准。

## 核心与入口

`core/` 自主完成识别、决策、执行、验证和流程推进。CLI 用于启动、观测与停止，Agent 在开发期根据事件和截图诊断并补能力。GUI 待整体能力稳定后再做。

- ADB 提供截图、点击与输入，出牌使用事件级拖拽；桌面设备保留作调试回退。
- 感知使用模板匹配、颜色和字形等视觉证据；决策使用英雄规则、通用评分及条件满足时的战斗穷举。
- 局部未知只限制依赖它的动作：未知牌可跳过，其他有依据的动作继续；不要求冒险中新卡全部预先建档。
- 界面、交互或动作结果未知时有界等待，超时保存截图并明确停止。当前实现不能自动恢复所有异常。
- 采用 [ADR-0004](docs/adr/0004-pure-script-decision.md) 的纯脚本路线；不读写游戏内存、不修改游戏文件、不绕过反作弊。英雄之路状态不接本地 `localhost:21337`，依据见 [ADR-0002](docs/adr/0002-vision-only-perception.md)。

详细职责与安全边界见 [`docs/architecture.md`](docs/architecture.md)。

## 快速开始

```bash
rtk git clone git@github.com:DeyunMa/lorwright.git
```

进入仓库目录后安装依赖并检查：

```bash
rtk pip install -e ".[dev]"
rtk pytest
rtk ruff check src tests tools

rtk lorwright devices
rtk lorwright shot --grid 100 --out logs/probe.png
```

确认设备、实时画面和操作授权后，启动后台冒险会话：

```bash
rtk lorwright sessions start --mode adventure --champion jinx --json
rtk lorwright sessions status RUN_ID --wait 30 --json
rtk lorwright sessions events RUN_ID --after 0 --jsonl
rtk lorwright sessions stop RUN_ID --json
```

`RUN_ID` 使用启动回执中的值；停止回执只表示请求已写入，再查状态确认终态。前台 `run` / `adventure` 支持 `--jsonl`，运行文件位于已忽略的 `logs/runs/`。配置见 `config/settings.yaml`。

f1 冒险入口可选 `--bootstrap-f1` 接管或启动 Pie64 与游戏；`--open-riot-login` 已实机验证至 Riot 表单。已有自动登录后进入游戏主页的局部实机记录；模拟器关闭后的完整冷启动尚未验收。凭据加载及前置条件见 [`docs/cli.md`](docs/cli.md)，不要把凭据放进命令或日志。

## 当前能力与验证范围

| 范围 | 当前结论 |
|---|---|
| 核心与 CLI | 自主识别、决策、输入与结果核验；后台会话、事件、等待截止、停止原因及截图可查询；未知信息只限制依赖动作 |
| 战斗 | Jinx 换牌、召唤、火箭、目标选择、收手及攻击有实机记录；已有完整单场无人介入记录，当前场次仍暴露单位定位和动作后验缺口 |
| 地图与节点 | 一跳寻路已统一为当前节点＋连续亮线＋目标状态，并实机连续进入辅助英雄与下一战；治疗、付费能力、商店离开及复活有局部记录 |
| 奖励与结算 | 卡牌、英雄道具、能力及援军选择和转场有实机记录；支持随机任务奖励插页和最终冒险胜利识别；外观覆盖及到账核验仍有限 |
| 弃牌 | 单次选择后保存采样截图并停止，完整确认与转场仍未闭环 |
| 启动与登录 | 已接管运行中的模拟器和游戏，并由现有自动登录流程进入主页；模拟器关闭后的完整冷启动未验收 |
| 完整目标 | 曾在开发恢复下通关 Jinx 的旧冒险；Jinx、Elise 各自全自动完成整个冒险均未端到端验收 |

离线测试、图片回放、局部实机和完整冒险分别记录。MAA/MaaFramework [研究笔记](docs/research/maa-maaframework-control-loop.md) 只提供设计参考，不作为本项目实机验收。

## 目录与技术栈

```text
src/lorwright/
├── core/
│   ├── models.py       # 状态、动作与执行计划
│   ├── runtime/        # 会话、事件、设备锁、协作停止
│   ├── device/         # ADB 与桌面设备
│   ├── perceive/       # 视觉感知
│   ├── decide/         # 通用规则与战斗求解
│   ├── act/            # 动作翻译
│   ├── loop/           # 战斗与冒险闭环
│   └── champions/      # Elise / Jinx 英雄包
└── cli/                # 前台命令与后台会话入口
```

主要依赖为 `opencv-python`、`pydantic`、`loguru`、`typer` 和 `rich`；桌面回退使用 `mss` / `pynput`。运行模板在 `assets/`，回归截图在 `tests/fixtures/`，历史证据在 `research/archives/`。

## 文档

| 文档 | 用途 |
|---|---|
| [`docs/handoff.md`](docs/handoff.md) | 接手步骤、环境基线与待验证项 |
| [`docs/status.md`](docs/status.md) | 当前能力与证据边界 |
| [`docs/architecture.md`](docs/architecture.md) | 当前核心职责与闭环契约 |
| [统一能力与分层循环审计](docs/research/capability-loop-audit-20261116.md) | 审计证据、八项 ticket 与依赖；实施由 [总 issue #17](https://github.com/DeyunMa/lorwright/issues/17) 跟踪 |
| [`docs/cli.md`](docs/cli.md) | 启动、状态、事件、停止和排障 |
| [`docs/environment.md`](docs/environment.md) | f1、模拟器和 ADB 环境参考，历史结论需复核 |
| [`docs/champions/elise.md`](docs/champions/elise.md) | Elise 专属规则与牌表 |
| [`docs/adr/`](docs/adr/) | 架构决策记录 |
| [`docs/research/maa-maaframework-control-loop.md`](docs/research/maa-maaframework-control-loop.md) | 上游机制研究及其适用限制 |
| [`tools/f1/`](tools/f1/) | f1 运维脚本及说明 |
| [`AGENTS.md`](AGENTS.md) | Agent 持续规则 |

## 使用边界

自动化可能违反 Riot 的用户协议，存在账号风险，请使用测试账号。项目用于学习和研究自动化技术，不提供游戏代练服务。参考 MAA/ALAS 的设计时需尊重其许可证，避免直接引入与项目分发要求不兼容的代码。

仓库名为 `lorwright`，展示名为 `LoRwright`。
