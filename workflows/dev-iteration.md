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
3. 在 Mac 上先跑相关专项测试，再跑完整回归（可用 `pytest -n auto` 并行加速，新增回归图后用 `python3 tools/test_data.py --check` 确认已登记且基线无缺失）。完整回归不过就不 push，在本轮内继续修。通过后提交，推送 `origin/main`，再把 f1 同步到同一提交（规则见 `AGENTS.md`）。优先用 `python3 tools/f1/sync.py --apply` 同步：脚本会先核对 f1 工作区干净、无非终态会话、可快进，再执行 `ff-only`；若 `pyproject.toml` 有变更，会在 f1 的 `.venv` 中重新安装依赖。测试只在 Mac 做，f1 同步后只核对提交、工作区和会话状态，不再跑测试。提交前看一眼 `git log`：出现不是本 goal 提交的新 commit（违反下文「并发」）时，把它们的哈希和标题记进账本，卡点归因时考虑进去。
4. 从 f1 的当前实时画面重新启动会话，不放弃当前这局冒险。
5. 回到触发，等下一个卡点或终态。

**同一卡点**：同一个停止 `reason`，出现在同一类页面或冒险阶段（例如同一节点类型、同一奖励页）。同一类问题的不同变体（例如各种载入画面超时）合并计数。修复后停在别处就算新卡点，计数归零。只补诊断或判断为环境问题的那一次不算修复，但要记进账本。

**验收失败**：验收会话中途停下，这局转为推进；修复后要重新开一局验收。

冒险失败（被打败）也算卡点：分析原因，改进程序后重新挑战。除每月挑战外，冒险不限次数（见[架构说明](../docs/architecture.md#自主闭环)）。

## 结束

- 目标中所有冒险都已验收：写 brief，更新 `docs/status.md` 并提交，用 `update_goal` 标记完成。
- 命中停止条件：写 brief，用 `update_goal` 标记受阻。

## 环境入口

实现者需要的事实散在现有文档里，这里只给入口：
- 连 f1：`ssh f1`（Mac 的 `~/.ssh/config` 已配置），工作区 `C:\Code\lorwright`，程序 `C:\Code\lorwright\.venv\Scripts\lorwright.exe`。每条 ssh 命令结束后 adb daemon 会被回收，见 `docs/environment.md` §5。
- 会话命令、状态字段、停止原因：`docs/cli.md`。
- 只读查看 f1：`python3 tools/f1/remote.py`，子命令 `status RUN`、`wait RUN --max 540`（有界等待到终态或 stalled）、`pull RUN`（截图、事件、状态拷到 `logs/f1-pulls/<run_id>/` 并打印精简事件）、`shot`（实时截图到 `logs/f1-pulls/`）、`focus`（前台窗口和 activity 栈）、`net`（TCP 连通和 netwatchdog 摘要）。它统一处理 ssh 保活、adb 在同一次调用内连接、截图按文件拉回等坑，优先用它，不再临时写脚本。
- 把停止截图做成回归素材：按 `docs/offline-validation.md` 和 `docs/layout.md` 放入库外测试数据并标注。
- f1 同步与运维边界：`tools/f1/README.md`。

## 授权

| 项 | 规则 |
|---|---|
| f1 同步 | 默认执行，无需逐次授权（见 `AGENTS.md`）。f1 有未提交改动、非终态会话或无法快进时，停止并报告 |
| 预授权（随目标一次性确认） | `lorwright sessions start/status/events/stop`，冒险限目标清单内；读会话截图与日志；使用既有的 `--bootstrap-f1 --auto-login`（凭据在 f1 项目 `.env`）；`tools/f1/remote.py` 的只读查看（实时截图、前台窗口、网络），f1 上的产物只写 `C:\Code\lorwright\logs\` |
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

**看守**：`tools/goal/watch.py`，不用 AI，测试在 `tests/test_goal_watch.py`。goal 第一轮由 goal 自己用 herdr 启动它，传入 goal 所在 pane 的 ID（goal 会话里的 `$HERDR_PANE_ID`）。**往下分屏**，保住 goal pane 的宽度；往右分会把 goal pane 压窄，底栏被截断：

```bash
W=$(herdr pane split --current --direction down --cwd "$PWD" --no-focus | python3 -c 'import sys,json;print(json.load(sys.stdin)["result"]["pane"]["pane_id"])')
herdr pane run "$W" "python3 tools/goal/watch.py $HERDR_PANE_ID"
```

脚本每 60 秒用 `recent-unwrapped --lines 40` 读一次该 pane，日志在 `logs/goals/watch-<pane>.log`，单实例锁 `logs/goals/watch-<pane>.lock`（锁文件内容是看守的 PID）：
- 只有不在回合内（输入框不是 `Guide Devin while it works`、没有转圈行，底栏也没有 `Goal running`），且最近一条 goal 提示是 `Goal paused after 50 turns` 原文时，才发送 `/goal resume`，并写一行日志；
- 只在看到明确的结束证据时退出：最近一条 goal 提示是 `✓ Goal …` / `✗ Goal …`（如 `Goal complete`、`Goal blocked`），或 goal 的 agent 已消失。用户取消回合、两轮之间、底栏被截断等其他情况一律继续守着，用户手动 `/goal resume` 后它仍然有效；
- 读画面失败时，用 `herdr agent list` 区分瞬时读错与 agent 消失：agent 仍在则记日志重试；`herdr` 连续不可达达上限时退出并记日志；
- 最多 resume 10 次，到上限后退出，并在日志里说明原因。

2026-11-19 实测：一个 55 轮的测试 goal 在第 50 轮暂停后，看守自动 resume 一次，goal 跑到 `Goal complete` 后看守自行退出。2026-11-20 goal-jinx 实跑中，旧版看守因 67 列窄 pane 截断底栏误退出一次，另有两次所在 pane 被外部关闭而静默消失，于是有了下面两条规则。

**看守存活检查**：goal 每轮开始时用 `ps -p "$(cat logs/goals/watch-${HERDR_PANE_ID//:/-}.lock)"` 检查锁文件里的 PID 是否还活着；不在就按上面的命令重启（单实例锁保证不会起两个），并把新 PID 记进账本。

**看守归属**：看守 pane 由启动它的 goal 负责。其他 agent 结束自己的监测时不得关闭看守 pane；第五层 `improve` 发现看守消失时可以重启它，但不关闭它。

因此每轮尽量包含一次完整的「等待 → 修复 → 同步 → 重启」，等待放在轮内用 `status --wait` 完成，不为等待而结束一轮。
账本顶部的「当前状态」每轮结束前更新，暂停续接或上下文压缩后，Agent 先读这一段再继续。账本只用文件写入或编辑工具更新，不用 shell heredoc：实测 shell 写中文会截断甚至清空账本。

## 并发

goal 运行期间独占 Mac 主检出目录的 `main` 和 f1 设备锁。启动前置条件：本机工作区干净，f1 上没有非终态会话。
运行期间，除第四层自己外，任何 agent 都不向 `main` 合入或推送：要合入的改动放在分支或独立 worktree，等第四层结束、受阻或用户暂停它之后再合。2026-11-20 运行期间外部合入了运行时代码和规格改动，结果账本把别人的合入记成了 goal 的修复，规格改动 goal 也没有读到。
用户会在启动时把 Mac 和 f1 都交给 goal。

## 可选第五层：外层记录与收口优化（`improve`）

默认情况下，用户直接启动 Devin `/goal` 只运行第四层循环，没有第五层。

第五层（`improve`）由用户人工按需触发（例如通过外层 Agent 同时拉起第四层 `main` 与第五层 `improve`），采用两阶段分工，不破坏第四层的单写者独占前提：

- **第四层运行期（只读记录者）**：`improve` 只读观察第四层运行与账本，记录暴露出的规格漏洞、工具缺陷、重复脚手架和架构债；不修改仓库文件、不打断第四层推进（仅在看守进程意外退出等 1 级阻塞时做最小外部兜底）。
- **第四层结束或受阻后（收口优化回合）**：第四层释放工作区后，`improve` 接管 `main` 集中做一轮收口优化（修复记录项、跑回归、提交推送），让下一轮 `/goal` 站在更稳的底座上起跑。

**启动第五层**：新开一个**干净的** Devin 会话做 `improve`，不要复用长上下文的旧会话：唤醒器每 30 分钟就让它完整跑一轮，长上下文会让每一轮都很贵。`improve` 第一轮先确认第四层 goal 所在的 pane（`herdr agent list`），再用 herdr 在自己下方开一个 pane 运行唤醒器 `tools/goal/notify.py`（不用 AI，测试在 `tests/test_goal_notify.py`）：

```bash
P=$(herdr pane split --current --direction down --cwd "$PWD" --no-focus | python3 -c 'import sys,json;print(json.load(sys.stdin)["result"]["pane"]["pane_id"])')
herdr pane run "$P" "python3 tools/goal/notify.py <第四层 goal 的 pane> $HERDR_PANE_ID"
```

唤醒器每 60 秒读一次 goal 的画面，经 `herdr agent prompt` 给 `improve` 发两类消息，每条都会让 `improve` 完整跑一轮：
- `[improve-tick]`：默认每 1800 秒（30 分钟，`--tick-interval` 可调）一次。`improve` 按运行期规则只读检查，把观察追加到 `logs/improve/notes.md`；
- `[improve-notify]`：goal 连续 3 次读到已停止（不在回合内，也不是 50 轮暂停），或 goal 的 agent 消失时发一次，送达后唤醒器退出。`improve` 按收口规则核对 goal 已结束、本机工作区干净、f1 无非终态会话，再按 `logs/improve/notes.md` 收口。

细节：
- 只在 `improve` 的 Herdr 状态为 `idle` / `done` 时发消息，不往正在进行的对话或回合里插话：定时消息遇忙跳过本次，结束消息每次读取后重试直到送达。用户正在 `improve` 输入框打字而 agent 仍为 `idle` 时，消息会和已输入的文字一起提交。
- 判断 goal 是否在回合内看输入框占位文字和转圈行，不看底栏的 `Goal running`（窄 pane 会截断底栏）。
- 日志和单实例锁：`logs/improve/notify-<goal pane>.log|.lock`；重复启动的第二个唤醒器读到锁即退出。
- 唤醒器在送达 `[improve-notify]` 后退出。用户之后 `/goal resume` 让第四层继续时，`improve` 要按上面的命令重新启动唤醒器。
- 收口改动在第四层释放工作区之后才合入 `main` 并推送。第四层运行期间若要预先开发，放在独立 worktree 的分支里，不从 worktree 推送 `origin/main`，否则第四层下一次 push 会被拒、`tools/f1/sync.py` 的目标比对也会失败。

## 日志与截图保留上限

为防止长周期运行下 1080p 截图无限膨胀，同时保留第四、五层复盘所需的文本记录，按「覆盖约 3 场冒险的调试体量」设以下保留上限，由 `tools/logs_cleanup.py`（默认 dry-run，加 `--apply` 才实际清理，测试在 `tests/test_logs_cleanup.py`）执行：

| 目录 / 文件 | 保留策略 | 估算上限 | 清理时机与边界 |
|---|---|---|---|
| `logs/goals/*.md`、`logs/improve/notes.md` | **永久保留** | 极小（纯文本） | 不自动删除，用于复盘第四、五层效率 |
| `logs/goals/watch-*.log`、`logs/improve/notify-*.log` | 单文件超 **5 MB** 时截断保留末尾 1 MB | ≤ 5 MB / 文件 | 第五层收口时可执行 `python3 tools/logs_cleanup.py --apply` |
| Mac `logs/f1-pulls/<run_id>/` | 保留最近 **50 个 run**（约 3 场重调试冒险；保留 `live.png`） | ~80–150 MB | 第五层收口时执行 `python3 tools/logs_cleanup.py --apply`（有价值失败帧已按 `docs/offline-validation.md` 登记进库外测试集） |
| Mac `logs/` 根目录散落截图与 `f1-material-*` / `lorwright-sync-*` | 默认不动；显式加 `--include-legacy` 清理 7 天前历史文件 | 按需 | 手动确认后执行 |
| f1 `C:\Code\lorwright\logs\runs\` | 保留最近 **100 个终态 run**（跳过非终态会话） | ~200–300 MB | 属于「删除或归档 f1 数据」，仅在用户明确授权后执行 `python3 tools/logs_cleanup.py --f1 --apply` |

## 模型策略与实测

按「机械执行 vs 高判断」占比为不同角色分配模型，平衡额度消耗与修复质量：

| 角色 | 推荐模型 | 适用理由 | 回退 / 切换方式 |
|---|---|---|---|
| 第四层 `/goal` | **均衡主力：`Fusion`（Opus 5.5 Lead + SWE-2 Sidekick）**<br>**零额度方案：`SWE-2 High`（免费）** | ~70% 机械闭环（SSH 等待、拉图、跑测试、同步、提交）可由 `SWE-2` 承担；复杂战斗截图与架构不变量由 Opus 兜底 | 均可在会话内 `/model` 实时切换（`SWE-2` ↔ `Fusion` ↔ `Opus 5.5`），不中断 goal |
| 第五层 `improve` 与专项审核 | **`Opus 5.5`** | 以只读巡检、边界挑刺与 diff 审查为主，调用频次低但判断权重高，可为 `SWE-2` 兜底 | 保持单模型 `Opus 5.5` |
| 外层协调 / 辅助（`agy`） | 日常编码 **`Orchestrator (Neon)`**（Neon 规划/复核 + Hydrogen 执行） | 多文件修改、补测试和重构性价比高 | 纯架构讨论或复杂排障时按需切单 `Neon` |

### 视觉盲测记录（2026-11-20）

用 5 张真实 1080p 停机截图（去文件名提示，覆盖大地图节点、能力三选一、战斗弃牌弹窗、复杂战斗卡顿、治疗节点飘字）对 `Claude Opus 5.5 Medium` 与 `SWE-2 High` 做纯视觉盲测（未读仓库代码）：

- **用量**：`Opus 5.5 Medium` 消耗 `46k / 1.0M` tokens；`SWE-2 High` 消耗 `31k / 262k` tokens（Free，省 33% 图像上下文，但总窗口为 262k，长 goal 压缩更频繁）。
- **识别效果**：`SWE-2 High` 繁体 OCR 几乎零失误，4/5 场景（地图、选能力、弃牌模态、治疗飘字）准确命中根因并给出可用感知规则；仅在最复杂战斗帧（`action_timeout`）将火焰攻击令牌、地标倒数误判为结算火焰与单位战力，以及地图漏看一条画外分支。`Opus 5.5 Medium` 5/5 全部准确并主动估算 1080p 坐标。
- **结论（可用）**：结合真实 `/goal` 可读代码、日志与全量回归的条件，**`SWE-2 High`（免费）可用于跑第四层 `/goal`**；但需搭配两道安全阀：
  1. 第五层 `improve` 保持 `Opus 5.5`（30 分钟巡检防硬编码/改歪）；
  2. 同一卡点（尤其复杂战斗帧）连修 2 次未过时，会话内 `/model` 临时切 `Fusion` 或 `Opus 5.5` 解决，解完可切回 `SWE-2`。

### `Fusion` / `SWE-2` 实跑观察项（手动选定冒险时）

后续手动挑一场冒险用 `Fusion` 或 `SWE-2 High` 跑完整 `/goal` 时，在账本里重点记录：
1. **截图诊断质量**：停机截图的根因判断是否与实际画面一致（重点看复杂战斗帧是否误判）；
2. **修复泛化度**：是否先写失败测试并按 `docs/architecture.md` 做跨冒险泛化，而非硬编码阈值/单英雄特判；
3. **收敛效率与消耗**：同一卡点的平均修复轮数、压缩后接续是否稳定，以及与此前单模型 `Opus` 场次的额度消耗对比。

若观察到诊断明显变浅或反复返工，直接在会话内用 `/model` 切到 `Fusion` 或 `Opus 5.5`，保留进度继续推进，并把实跑结论回写本节。

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
| 账本与 brief | 账本 `logs/goals/<日期>-<目标简称>.md`（git 忽略），顶部维护「当前状态」：目标、各冒险阶段、f1 run_id、看守 pane 和 PID、最近 commit、同一卡点修复次数，下面逐轮追加：会话 ID、卡点、修复 commit、结果。goal 结束时 brief 追加在账本末尾并原样输出：每个冒险一行（验收/推进/未开始、会话 ID、commit），停在哪、为什么、需要用户决定什么（没有写「无」），账本与截图路径。改变验收结论的内容按现有规则写进 `docs/status.md` 并提交 |
| 模型 | 按上文「模型策略与实测」执行：第四层 `/goal` 可选 `Fusion`（Opus 5.5 Lead + SWE-2 Sidekick）或零额度 `SWE-2 High`（配 `improve` Opus 巡检兜底），第五层 `improve` 保持 `Opus 5.5`；卡点反复返工时用 `/model` 切到 `Fusion` 或 `Opus 5.5`，goal 不受影响 |
| 每周刷新 | 不处理。用户安排运行时间避开刷新，单次 goal 也不会跑到一周 |
| 每月挑战 | 本阶段不涉及，不进入目标 |
| 新能力 | 目标可以要求新功能（例如跨冒险任务层），按 issue #17 拆票推进，ADR、文档、issue 按需更新 |
