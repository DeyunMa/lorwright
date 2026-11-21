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
3. 在 Mac 上分层验证（2026-11-21 起，测试分层见 `tests/conftest.py` 的 `slow` / `smoke` 标记）：
   - **每次修复，push 前必跑**：改动涉及的测试文件全文件运行，加冒烟层 `pytest -n 4 -m "not slow" --strict-markers`（约 30–40 秒）。新增回归图后用 `python3 tools/test_data.py --check` 确认已登记且基线无缺失。这两项不过就不 push，在本轮内继续修。
   - **完整回归**：每次 push 后在后台跑 `.venv/bin/pytest -n auto > logs/goals/full-<commit>.log 2>&1`，和 f1 上的续接会话同时进行，不阻塞重启；结果在下一轮开始前看，以日志末行的「N passed」为准。不要再加 `-q`：`pyproject.toml` 的 `addopts` 已有 `-q`，叠加成 `-qq` 后 pytest 不打印汇总行，2026-11-21 Elise 1 号位的全量日志因此全部没有通过数。完整回归有失败时，下一轮先修它，再看新的停点。另外每场冒险打完、收口之前必须跑完一次并通过。
   - 提交说明写明实际跑的测试和通过数（例如「受影响文件 312 passed，冒烟 1707 passed」；后台全量出结果后在下一个提交或账本里补上）。
   通过后提交，推送 `origin/main`，再把 f1 同步到同一提交（规则见 `AGENTS.md`）。优先用 `python3 tools/f1/sync.py --apply` 同步：脚本会先核对 f1 工作区干净、无非终态会话、可快进，再执行 `ff-only`；若 `pyproject.toml` 有变更，会在 f1 的 `.venv` 中重新安装依赖。测试只在 Mac 做，f1 同步后只核对提交、工作区和会话状态，不再跑测试。提交前看一眼 `git log`：出现不是本 goal 提交的新 commit（违反下文「并发」）时，把它们的哈希和标题记进账本，卡点归因时考虑进去。
4. 从 f1 的当前实时画面重新启动会话，不放弃当前这局冒险。
5. 回到触发，等下一个卡点或终态。

**同一卡点**：同一个停止 `reason`，出现在同一类页面或冒险阶段（例如同一节点类型、同一奖励页）。同一类问题的不同变体（例如各种载入画面超时）合并计数。修复后停在别处就算新卡点，计数归零。只补诊断或判断为环境问题的那一次不算修复，但要记进账本。

**验收失败**：验收会话中途停下，这局转为推进；修复后要重新开一局验收。

冒险失败（被打败）也算卡点：分析原因，改进程序后重新挑战。除每月挑战外，冒险不限次数（见[架构说明](../docs/architecture.md#自主闭环)）。

## 结束

- 每打完或验收一场冒险，就在 `docs/status.md` 记一行并提交：冒险名、完成级别（打完 / 验收）、第四层和第五层所用的工具与模型（没有第五层写「无」）、关键会话 ID、修复提交范围、遗留问题。账本不入库，这一行是仓库里唯一的完成记录。
- 续接停在结算阶段（胜利页、奖励汇总、任务插页）的会话前，先用 `tools/f1/remote.py shot` 看实时帧：已回到世界地图就是这一场已打完，不再启动会话。带 `--weekly-replay-slot` 从世界地图启动会再开一局同位置重玩，2026-11-20 r2s2 打完后就因此多开了一局。
- `--weekly-replay-slot` 只用于开始目标冒险的第一个会话，同一场冒险的续接会话一律不带它：带着它时，「继续冒险」页会以 `weekly_replay_active_adventure` 停下，世界地图则会再开一局重玩。不带它的会话在世界地图上仍可能按最低星级开一个未完成的周常，所以续接前看实时帧这一步不能省。
- 目标中所有冒险都达到目标写明的完成级别（默认「打完」，见「已定」）：写 brief，用 `update_goal` 标记完成。
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
- 只在看到明确的结束证据时退出：最近一条 goal 提示是 `✓ Goal …` / `✗ Goal …`（如 `Goal complete`、`Goal blocked`），或底栏显示 `✓ Goal …` / `✗ Goal …`，或 goal 的 agent 已消失。brief 较长时状态行会滚出读取窗口，只剩底栏，2026-11-20 r2s2 的看守因此没有退出。用户取消回合、两轮之间、底栏被截断等其他情况一律继续守着，用户手动 `/goal resume` 后它仍然有效；
- 读画面失败时，用 `herdr agent list` 区分瞬时读错与 agent 消失：agent 仍在则记日志重试；`herdr` 连续不可达达上限时退出并记日志；
- 最多 resume 10 次，到上限后退出，并在日志里说明原因。

2026-11-19 实测：一个 55 轮的测试 goal 在第 50 轮暂停后，看守自动 resume 一次，goal 跑到 `Goal complete` 后看守自行退出。2026-11-20 goal-jinx 实跑中，旧版看守因 67 列窄 pane 截断底栏误退出一次，另有两次所在 pane 被外部关闭而静默消失，于是有了下面两条规则。

**看守存活检查**：goal 每轮开始时用 `ps -p "$(cat logs/goals/watch-${HERDR_PANE_ID//:/-}.lock)"` 检查锁文件里的 PID 是否还活着；不在就按上面的命令重启（单实例锁保证不会起两个），并把新 PID 记进账本。**例外**：存在 `logs/goals/watch-<pane>.off` 时表示用户有意停用，不重启。用户要停看守时就创建这个文件，看守在一个读取周期内自行退出；删掉文件即恢复。

**看守归属**：看守 pane 由启动它的 goal 负责。其他 agent 结束自己的监测时不得关闭看守 pane；第五层 `improve` 发现看守消失时可以重启它，但不关闭它。

因此每轮尽量包含一次完整的「等待 → 修复 → 同步 → 重启」，等待放在轮内用 `status --wait` 完成，不为等待而结束一轮。
账本顶部的「当前状态」每轮结束前更新，暂停续接或上下文压缩后，Agent 先读这一段再继续。账本只用文件写入或编辑工具更新，不用 shell heredoc：实测 shell 写中文会截断甚至清空账本。

## 并发

goal 运行期间独占 Mac 主检出目录的 `main` 和 f1 设备锁。启动前置条件：本机工作区干净，f1 上没有非终态会话。
运行期间，除第四层自己外，任何 agent 都不向 `main` 合入或推送：要合入的改动放在分支或独立 worktree，等第四层结束、受阻或用户暂停它之后再合。2026-11-20 运行期间外部合入了运行时代码和规格改动，结果账本把别人的合入记成了 goal 的修复，规格改动 goal 也没有读到。
用户会在启动时把 Mac 和 f1 都交给 goal。

## 可选第五层与模型

- 第五层 `improve`（运行期只读记录、结束后收口、唤醒器、日志保留上限）见 [improve.md](improve.md)。默认只跑第四层，不需要读它。
- 各角色的模型选择与实测见 [models.md](models.md)。

## 启动

用户步骤：在外层对话确认目标 → 新开 Devin 会话并切到 Bypass → 粘贴：

```
/goal 按 workflows/dev-iteration.md 执行第四层循环。本轮目标：<一句话，例如「用 Elise 打完一轮每周冒险」>。完成级别：<打完 / 验收>。完成标准、授权、停止条件和续接方式均以该文件为准；先读该文件和 AGENTS.md，再创建或读取账本。
```

goal 第一轮：检查并发前置条件 → 创建或读取账本 → 启动看守 → 进入循环。开头一段时间用户会在旁边看。

## 已定

| 决策 | 结论 |
|---|---|
| 委派对象 | 开发迭代闭环（第四层），三层运行循环是它改进的对象 |
| 产出约束 | 先用文档约束：本规格 + `NOTES.md` |
| 目标来源 | 启动前用户在外层对话与 Agent 确认本轮目标，再用 `/goal` 启动，`/goal` 文本指向本规格和目标 |
| 完成标准 | 两级，由目标写明，**默认「打完」**。**打完（推进）**：可以中途停过、改过代码、接续后打完，到结算退出即达成。**验收**：同一 commit 一次会话从冒险开始前跑到 `adventure_victory` 且 `settlement_closed=true`，中途不改代码、无人介入；只有目标明确写「验收」时才要求。2026-11-20 goal-jinx 的目标文本写了验收，于是在打完后又开了一局，超出了用户「打完这一场」的本意 |
| 初态 | 不另设。Agent 用 `--bootstrap-f1 --auto-login` 启动，从 f1 当时的实际画面开始（模拟器关闭、主页、地图都可）；周常已完成时，只在目标冒险的第一个会话加 `--weekly-replay-slot`，续接会话不加 |
| 目标写法 | 用户在外层对话用一句话给出冒险和完成级别，例如「用 Elise 打完一轮每周冒险」或「用 Jinx 验收每周 1 号位」；Agent 展开成逐个冒险，按顺序推进，一个达标再开始下一个 |
| 验收起点 | 仅在目标要求验收时适用。验收会话必须在冒险开始之前启动（周常列表、世界地图、主页或模拟器关闭）。f1 停在冒险中途时，先按推进跑完这一局，再开新一局做验收 |
| 权限模式 | goal 会话用 Bypass（`devin --permission-mode bypass` 或 `/bypass`）。复核用前台 `subagent_general` |
| 账本与 brief | 账本 `logs/goals/<日期>-<目标简称>.md`（git 忽略），顶部「当前状态」只放查不到的内容：目标与完成级别、启动配置、各冒险阶段、同一卡点修复次数、看守 PID。启动配置在第一轮写入，之后只在变化时更新（例如中途 `/model` 换模型，写成「A→B」）：第四层的工具和模型（如 `devin swe-2-max`）、第五层的工具和模型（没有第五层写「无」）、启动 commit、上下文压缩阈值（未设写「默认」）、验证分层规则（照抄上文「循环」第 3 步当时的规则），供第五层收口写 `logs/improve/metrics.md` 和审计；会话 ID 和 commit 从最后一条轮次记录与 `git log` 读，不在顶部重复（实测两次运行顶部的 commit 和 pane 都没人更新）。下面逐轮追加：会话 ID、卡点、修复 commit、结果。goal 结束时 brief 追加在账本末尾并原样输出：每个冒险一行（验收/推进/未开始、会话 ID、commit），停在哪、为什么、需要用户决定什么（没有写「无」），账本与截图路径。每场冒险打完或验收后按「结束」一节写进 `docs/status.md` 并提交 |
| 模型 | 每轮的实际工具和模型由用户启动时指定，记入账本顶部的启动配置；没有指定时按 [models.md](models.md) 执行：第四层 `/goal` 可选 `Fusion`（Opus 5.5 Lead + SWE-2 Sidekick）或零额度 `SWE-2 High`（配 `improve` Opus 巡检兜底），第五层 `improve` 保持 `Opus 5.5`；卡点反复返工时用 `/model` 切到 `Fusion` 或 `Opus 5.5`，goal 不受影响 |
| 每周刷新 | 不处理。用户安排运行时间避开刷新，单次 goal 也不会跑到一周 |
| 每月挑战 | 本阶段不涉及，不进入目标 |
| 新能力 | 目标可以要求新功能（例如跨冒险任务层），按 issue #17 拆票推进，ADR、文档、issue 按需更新 |
