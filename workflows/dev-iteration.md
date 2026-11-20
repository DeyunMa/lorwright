# 第四层循环：开发迭代

> 状态：grilling 已收敛（2026-11-19），待用户最终确认。

## 定位

运行时有三层循环：单场战斗 → 单次冒险 → 跨冒险任务，由 `core/` 纯脚本执行，没有 AI。
第四层循环在这三层之外。Agent 在 Devin CLI 的 `/goal` 下，通过 CLI 会话、代码修改、回归和 f1 同步，
反复把三层循环开发到能完成指定冒险。做法与用户自己正常开发一样，文档、issue 按需更新。
Agent 不逐动作调度游戏，只改程序能力。

**原则：自主推进。** 设计这个循环就是为了让项目自动迭代。能判断的，Agent 自己判断后继续；
停下交还用户只限于下面「停止条件」列出的情况。

## 循环

触发：f1 上的实机会话进入终态（`stopped / failed / completed`）。Agent 用
`lorwright sessions status RUN_ID --wait 30 --json` 有界等待，不按固定时间轮询。

一轮：
1. 读终态的 `reason`、事件和停止截图，定位卡点。
2. 用停止素材复现：写失败测试，修复后让它通过，按[开发闭环](../docs/architecture.md#开发闭环)复验相关场次。
3. 在 Mac 上先跑相关专项测试，再跑完整回归（可用 `pytest -n auto` 并行加速，新增回归图后用 `python3 tools/test_data.py --check` 确认已登记且基线无缺失）。完整回归不过就不 push，在本轮内继续修。通过后提交，推送 `origin/main`，再把 f1 同步到同一提交（规则见 `AGENTS.md`）。优先用 `python3 tools/f1/sync.py --apply` 同步：脚本会先核对 f1 工作区干净、无非终态会话、可快进，再执行 `ff-only`；若 `pyproject.toml` 有变更，会在 f1 的 `.venv` 中重新安装依赖。测试只在 Mac 做，f1 同步后只核对提交、工作区和会话状态，不再跑测试。
4. 从 f1 的当前实时画面重新启动会话，不放弃当前这局冒险。
5. 回到触发，等下一个卡点或终态。

**同一卡点**：同一个停止 `reason`，出现在同一类页面或冒险阶段（例如同一节点类型、同一奖励页）。修复后停在别处就算新卡点，计数归零。

**验收失败**：验收会话中途停下，这局转为推进；修复后要重新开一局验收。

冒险失败（被打败）也算卡点：分析原因，改进程序后重新挑战。除每月挑战外，冒险不限次数（见[架构说明](../docs/architecture.md#自主闭环)）。

## 结束

- 目标中所有冒险都已验收：写 brief，更新 `docs/status.md` 并提交，用 `update_goal` 标记完成。
- 命中停止条件：写 brief，用 `update_goal` 标记受阻。

## 环境入口

实现者需要的事实散在现有文档里，这里只给入口：
- 连 f1：`ssh f1`（Mac 的 `~/.ssh/config` 已配置），工作区 `C:\Code\lorwright`，程序 `C:\Code\lorwright\.venv\Scripts\lorwright.exe`。每条 ssh 命令结束后 adb daemon 会被回收，见 `docs/environment.md` §5。
- 会话命令、状态字段、停止原因：`docs/cli.md`。
- 看停止截图：从 f1 的 `logs/runs/<run_id>/snapshots/` 用 `scp` 拷到 Mac 再读图（已实测 Windows OpenSSH 路径写法：`scp -r 'f1:C:/Code/lorwright/logs/runs/<run_id>/snapshots' logs/f1-pulls/<run_id>/`）。
- 把停止截图做成回归素材：按 `docs/offline-validation.md` 和 `docs/layout.md` 放入库外测试数据并标注。
- f1 同步与运维边界：`tools/f1/README.md`。

## 授权

| 项 | 规则 |
|---|---|
| f1 同步 | 默认执行，无需逐次授权（见 `AGENTS.md`）。f1 有未提交改动、非终态会话或无法快进时，停止并报告 |
| 预授权（随目标一次性确认） | `lorwright sessions start/status/events/stop`，冒险限目标清单内；读会话截图与日志；使用既有的 `--bootstrap-f1 --auto-login`（凭据在 f1 项目 `.env`） |
| 仍需停下 | 改看门狗或计划任务；改 Clash/Tailscale/网络配置；改凭据；重启整机；bundle 恢复流程；删除或归档 f1 数据；目标清单以外的冒险 |

## 停止条件

| 情况 | 先做什么 | 什么时候停 |
|---|---|---|
| 同一卡点修了 3 次仍未过 | 启动一个干净的 Devin 子智能体（`subagent_general`，不继承父对话），只给停止证据、相关代码位置和前 3 次修复的 commit，请它独立修复并跑回归 | 子智能体也修复不了 |
| 游戏机制无法判断 | 先查截图、项目文档、网上资料 | 资料仍不足以判断 |
| f1 不可达 | 每 30 分钟检查一次，最多 10 次（goal 模式下替代 `tools/f1/README.md` 的 5×5 分钟） | 10 次都失败 |
| 需要越过授权边界 | — | 立即 |

登录凭据放在 `.env`，按正常情况处理，不作为停止条件。

## 续接：50 轮暂停

已实测（2026-11-19，Devin CLI v3000.14.30821，herdr 0.9.5）：
- 「轮」指 agent 的一个回合：开始工作 → 若干工具调用 → 结束回合。`/goal` 每次自动续上算一轮，与修复次数无关。
- 第 50 轮结束时界面显示 `Goal paused after 50 turns. Use /goal resume to continue.`，底栏的 `Goal running` 消失。
- 通过 herdr 向该 pane 发送 `/goal resume` 后，同一会话继续推进，轮次接着计数（51、52…），最后可正常显示 `Goal complete`。
- agent 自己看不到轮次编号，续接提示里没有这个信息，所以无法在第 45 轮主动交接。
- goal 在两轮之间时，herdr 的 `agent_status` 显示 `idle`，不能用它判断 goal 状态，要读 pane 画面文字。

**看守**：`tools/goal/watch.py`，不用 AI，测试在 `tests/test_goal_watch.py`。goal 第一轮由 goal 自己用 herdr 启动它，传入 goal 所在 pane 的 ID（goal 会话里的 `$HERDR_PANE_ID`）：

```bash
W=$(herdr pane split --current --direction right --cwd "$PWD" --no-focus | python3 -c 'import sys,json;print(json.load(sys.stdin)["result"]["pane"]["pane_id"])')
herdr pane run "$W" "python3 tools/goal/watch.py $HERDR_PANE_ID"
```

脚本每 60 秒用 `recent-unwrapped --lines 40` 读一次该 pane（避免窄 pane 折行截断暂停提示），日志在 `logs/goals/watch-<pane>.log`，并通过单实例锁 `logs/goals/watch-<pane>.lock` 防止续接或上下文压缩后重复起看守：
- 只有底栏没有 `Goal running`，且画面上最近一条 goal 提示是 `Goal paused after 50 turns` 原文时，才发送 `/goal resume`，并写一行日志；
- 底栏没有 `Goal running`，且最近一条提示不是这句原文（完成、受阻、被用户中断或清除），就退出，不 resume；
- 读画面失败时，用 `herdr agent list` 区分瞬时读错与 agent 消失：agent 仍在则记日志重试，不退出；确认消失才按连续确认次数退出；`herdr` 连续不可达达上限时退出并记日志；
- 最多 resume 10 次，到上限后退出，并在日志里说明原因。

2026-11-19 实测：一个 55 轮的测试 goal 在第 50 轮暂停后，看守自动 resume 一次，goal 跑到 `Goal complete` 后看守自行退出。

因此每轮尽量包含一次完整的「等待 → 修复 → 同步 → 重启」，等待放在轮内用 `status --wait` 完成，不为等待而结束一轮。
账本顶部的「当前状态」每轮结束前更新，暂停续接或上下文压缩后，Agent 先读这一段再继续。

## 并发

goal 运行期间独占 Mac 主检出目录的 `main` 和 f1 设备锁。启动前置条件：本机工作区干净，f1 上没有非终态会话。
用户会在启动时把 Mac 和 f1 都交给 goal。

## 可选第五层：外层记录与收口优化（`improve`）

默认情况下，用户直接启动 Devin `/goal` 只运行第四层循环，没有第五层。

第五层（`improve`）由用户人工按需触发（例如通过外层 Agent 同时拉起第四层 `main` 与第五层 `improve`），采用两阶段分工，不破坏第四层的单写者独占前提：

- **第四层运行期（只读记录者）**：`improve` 只读观察第四层运行与账本，记录暴露出的规格漏洞、工具缺陷、重复脚手架和架构债；不修改仓库文件、不打断第四层推进（仅在看守进程意外退出等 1 级阻塞时做最小外部兜底）。
- **第四层结束或受阻后（收口优化回合）**：第四层释放工作区后，`improve` 接管 `main` 集中做一轮收口优化（修复记录项、跑回归、提交推送），让下一轮 `/goal` 站在更稳的底座上起跑。

## 启动

用户步骤：在外层对话确认目标 → 新开 Devin 会话并切到 Bypass → 粘贴：

```
/goal 按 workflows/dev-iteration.md 执行第四层循环。本轮目标：<一句话，例如「用 Elise 完成一轮每周冒险」>。完成标准、授权、停止条件和续接方式均以该文件为准；先读该文件和 AGENTS.md，再创建或读取账本。
```

goal 第一轮：检查并发前置条件 → 创建或读取账本 → 启动看守 → 进入循环。开头一段时间用户会在旁边看。

## 已定

| 决策 | 结论 |
|---|---|
| 委派对象 | 开发迭代闭环（第四层），三层运行循环是它改进的对象 |
| 产出约束 | 先用文档约束：本规格 + `NOTES.md` |
| 目标来源 | 启动前用户在外层对话与 Agent 确认本轮目标，再用 `/goal` 启动，`/goal` 文本指向本规格和目标 |
| 完成标准 | 两级。**推进**：中途停过、改过代码、接续后打完。**验收**：同一 commit 一次会话从启动跑到 `adventure_victory` 且 `settlement_closed=true`，中途不改代码、无人介入。goal 只认验收 |
| 初态 | 不另设。Agent 用 `--bootstrap-f1 --auto-login` 启动，从 f1 当时的实际画面开始（模拟器关闭、主页、地图都可）；周常已完成时加 `--weekly-replay-slot` |
| 目标写法 | 用户在外层对话用一句话给出，例如「用 Elise 完成一轮每周冒险」；Agent 展开成逐个冒险，按顺序推进，一个验收通过再开始下一个 |
| 验收起点 | 验收会话必须在冒险开始之前启动（周常列表、世界地图、主页或模拟器关闭）。f1 停在冒险中途时，先按推进跑完这一局，再开新一局做验收 |
| 权限模式 | goal 会话用 Bypass（`devin --permission-mode bypass` 或 `/bypass`）。复核用前台 `subagent_general` |
| 账本与 brief | 账本 `logs/goals/<日期>-<目标简称>.md`（git 忽略），顶部维护「当前状态」：目标、各冒险阶段、f1 run_id、看守 pane、最近 commit、同一卡点修复次数，下面逐轮追加：会话 ID、卡点、修复 commit、结果。goal 结束时 brief 追加在账本末尾并原样输出：每个冒险一行（验收/推进/未开始、会话 ID、commit），停在哪、为什么、需要用户决定什么（没有写「无」），账本与截图路径。改变验收结论的内容按现有规则写进 `docs/status.md` 并提交 |
| 模型 | Fusion，Opus 5.5 做 lead，sidekick 用官方推荐。用户在开头观察时检查截图诊断和修复方案是否由 lead 把关、质量够不够；sidekick 的修复反复被打回或诊断明显变浅时，用 `/model` 切回 Opus 5.5 单模型，goal 不受影响 |
| 每周刷新 | 不处理。用户安排运行时间避开刷新，单次 goal 也不会跑到一周 |
| 每月挑战 | 本阶段不涉及，不进入目标 |
| 新能力 | 目标可以要求新功能（例如跨冒险任务层），按 issue #17 拆票推进，ADR、文档、issue 按需更新 |
