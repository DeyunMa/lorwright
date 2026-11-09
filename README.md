# LoRwright

> 名字致敬 Microsoft 的 Playwright（*wright* = 工匠）。本项目**不依赖** Playwright。

基于**纯视觉**的《符文大地传说》英雄之路（Path of Champions）自动化工具。
截图 → 决策 → ADB 输入，不碰游戏内存、不接游戏 API。

---

## 👉 接手开发从这里开始

**[`docs/handoff.md`](docs/handoff.md)** —— 现在卡在哪、按什么顺序做、有哪些踩过的坑。

---

## 它是什么

- 用 **ADB** 从手机/模拟器截图，用**模板匹配 / 颜色探针**识别界面
- 战斗和出牌使用规则与评分；通用格挡在条件满足时穷举分配，信息不足时使用贪心规则
- 纯脚本决策（MAA 式），不接 LLM / 外部决策服务（见 ADR-0004）
- 用 ADB 点击，出牌等手势通过事件级触控后端执行

**当前英雄包**：伊莉絲（Elise）与金克丝（Jinx）。伊莉絲牌表见
[`docs/champions/elise.md`](docs/champions/elise.md)。

## 它不是什么

- ❌ **不用游戏 API。** 英雄之路没有 API —— `localhost:21337` 只覆盖收藏/构筑/PvP，
  证据：`RiotGames/developer-relations#773`（2023-05 提出，至今 open）。
  这是项目早期最大的弯路，别再走一遍。
- ❌ 不是通用 GUI Agent
- ❌ 不读写游戏内存、不修改游戏文件、不绕过反作弊
- ❌ 不保证胜率 —— 目标是「把局打完」

---

## 架构

**两条正交的链**，把它们混成一条是最容易犯的错。

```
A. 决策链 —— 现在该做什么
   英雄包规则  →  通用规则/穷举  →  安全兜底

B. 监督器 —— 是不是卡住了（不经过决策层）
   Watchdog（画面/摘要不变） → RecoveryPolicy（重试→重开→重启→停）
```

**输出必须是受约束的**：规则层输出 `Action`；战斗中不认识的状态返回
`NO_OP`；全部策略弃权且确认处于 `MY_TURN_IDLE` 时结束回合。

「卡住」由程序判定（像素 hash 不变），不调模型 —— 画面不动是像素问题，不是语义问题。

详见 [`docs/architecture.md`](docs/architecture.md)。

---

## 快速开始

```bash
git clone git@github.com:DeyunMa/lorwright.git
cd lorwright
pip install -e ".[dev]"

pytest                      # 单测，不需要游戏
ruff check src tests tools

lorwright devices           # 列出 ADB 设备
lorwright shot --grid --out logs/probe.png   # 截图 + 坐标网格
lorwright run --max-ticks 50
```

配置在 `config/settings.yaml`（`champion` / `layout` / `adb` / `loop`）。

---

## 技术栈

| 层 | 选型 | 理由 |
|---|---|---|
| 设备 | **ADB**（`adb screencap` / `input`） | 坐标即屏幕坐标、可后台、多开靠 `-s`、快照可回滚 |
| 图像 | `opencv-python` | 模板匹配 + 颜色探针 |
| 状态校验 | `pydantic` | 配置与数据契约 |
| 日志 | `loguru` | 按日期分目录 + JSONL 事件流 |
| CLI | `typer` + `rich` | 轻量 |

桌面模式（`mss` + `pynput`）保留为**调试回退**，不是主路径（见 `docs/adr/0003`）。

---

## 目录结构

```
src/lorwright/
├── models.py         # 数据契约：GameState / Action / Layout
├── device/           # ADB / 桌面设备抽象
├── perceive/         # 截图 → UI 状态、卡牌、场面
├── decide/           # 决策机制（不认识任何英雄）
│   ├── card.py       #   卡牌通用词汇
│   ├── combat.py     #   战斗求解器（穷举）
│   ├── generic.py    #   通用规则：英雄优先 / 攻击 / 格挡
│   ├── rewards.py    #   奖励三选一
│   └── router.py     #   分层路由
├── champions/        # 英雄包：一个英雄 = 一个目录
│   ├── elise/        #   牌表 + 策略 + 识别
│   └── jinx/         #   牌表 + 策略 + 识别
├── perceive/unit_stats.py # 单位攻击/生命数字
├── act/              # 语义动作 → 坐标
└── loop/             # 主循环、看门狗、恢复
```

**加英雄 = 加 `champions/<name>/` 目录，不改核心层。**

---

## 现状

| 阶段 | 目标 | 状态 |
|---|---|---|
| M0 | 骨架 + 规则 + 单测 + CI | ✅ 完成 |
| **M1** | 自动打完一场 PoC 战斗 | 🚧 进行中 |
| M2 | 自动选奖励（三选一） | 🚧 偏好/排序已落，UI 识别待实机 |
| M3 | 自动走地图 | 🚧 mapnav + AdventureLoop 已落，待实机验收 |
| M4 | 跑完一个完整副本 | 待做 |

**当前阻塞**：仍需完整自动战斗和起手换牌的连续实战复验；能力奖励仅支持
已采集的三种名称并输出推荐，选择/确认及其他奖励界面待素材。敌方攻击行
真实帧和生命遮挡样本也待补充。

细节见 [`docs/status.md`](docs/status.md)。

---

## 文档

| 文档 | 内容 |
|---|---|
| [`docs/handoff.md`](docs/handoff.md) | **交接入口** |
| [`docs/architecture.md`](docs/architecture.md) | 核心设计 |
| [`docs/status.md`](docs/status.md) | 当前状态 |
| [`docs/decision-l1-rules.md`](docs/decision-l1-rules.md) | 历史规则设计与加英雄检查清单 |
| [`docs/decision-l2-jev.md`](docs/decision-l2-jev.md) | 历史设计（ADR-0004 已废弃） |
| [`docs/champions/elise.md`](docs/champions/elise.md) | 伊莉絲牌组与专属规则 |
| [`docs/reference-prior-art.md`](docs/reference-prior-art.md) | MAA / ALAS 参考 |
| [`docs/adr/`](docs/adr/) | 架构决策记录 |
| [`tools/f1/`](tools/f1/) | f1 网络/游戏看门狗与 Pie64 启动脚本 |
| [`AGENTS.md`](AGENTS.md) | 给 AI agent 的硬约束 |

---

## 风险与免责

- **可能违反 Riot 的用户协议**，存在封号风险。请使用小号，风险自担。
- 本项目仅供学习与研究自动化技术，不提供任何形式的游戏代练服务。
- **只学 MAA / ALAS 的设计，不抄代码** —— 它们是 AGPL-3.0 / GPL-3.0，
  会传染，与本项目的分发方式冲突。

---

## 命名

`LoRwright` = `LoR` + `wright`（工匠）。仓库名全小写 `lorwright`，展示名 `LoRwright`。
