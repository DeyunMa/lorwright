# 第五层：外层记录与收口优化（`improve`）

可选层。第四层规格见 [dev-iteration.md](dev-iteration.md)；第五层必须遵守其中「并发」一节的单写者规则。

默认情况下，用户直接启动 Devin `/goal` 只运行第四层循环，没有第五层。

第五层（`improve`）由用户人工按需触发（例如通过外层 Agent 同时拉起第四层 `main` 与第五层 `improve`），采用两阶段分工，不破坏第四层的单写者独占前提：

- **第四层运行期（只读记录者）**：`improve` 只读观察第四层运行与账本，记录暴露出的规格漏洞、工具缺陷、重复脚手架和架构债；不修改仓库文件、不打断第四层推进（仅在看守进程意外退出等 1 级阻塞时做最小外部兜底）。
- **第四层结束或受阻后（收口优化回合）**：第四层释放工作区后，`improve` 接管 `main` 集中做一轮收口优化（修复记录项、跑回归、提交推送），让下一轮 `/goal` 站在更稳的底座上起跑。
  收口由 `improve` 自主完成：修复记录项、测试、提交、推送 `origin/main`、`python3 tools/f1/sync.py --apply` 同步 f1，全程按 [dev-iteration.md](dev-iteration.md) 的分层验证和 `AGENTS.md` 的提交规则执行，收口前跑一次完整回归。外层 Agent 只负责协调（拉起会话、转达用户决定），不接管收口改动。需要实机画面才能判断的打法和识别问题不盲修，写进 `logs/improve/notes.md` 的「下一轮 goal 注意事项」，留给下一轮 goal。

**启动第五层**：新开一个**干净的**会话做 `improve`（工具和模型按本轮启动配置，例如 Devin 或 agy），不要复用长上下文的旧会话：唤醒器每 30 分钟就让它完整跑一轮，长上下文会让每一轮都很贵。`improve` 第一轮先在 `logs/improve/notes.md` 写一节启动记录（第四层 goal 的 pane、第五层工具和模型、审查基线 commit），再确认第四层 goal 所在的 pane（`herdr agent list`），再用 herdr 在自己下方开一个 pane 运行唤醒器 `tools/goal/notify.py`（不用 AI，测试在 `tests/test_goal_notify.py`）：

```bash
P=$(herdr pane split --current --direction down --cwd "$PWD" --no-focus | python3 -c 'import sys,json;print(json.load(sys.stdin)["result"]["pane"]["pane_id"])')
herdr pane run "$P" "python3 tools/goal/notify.py <第四层 goal 的 pane> $HERDR_PANE_ID"
```

唤醒器每 60 秒读一次 goal 的画面，经 `herdr agent prompt` 给 `improve` 发两类消息，每条都会让 `improve` 完整跑一轮：
- `[improve-tick]`：默认每 1800 秒（30 分钟，`--tick-interval` 可调）一次。`improve` 按运行期规则只读检查，把观察追加到 `logs/improve/notes.md`；
  每次检查除了看进展、账本和看守，还要对上次检查以来的每个新提交过一遍审查清单（看 `git show` 的说明和 diff）：
  1. 提交说明写了完整回归的通过数；只写专项测试的记下来；
  2. 有没有放宽识别门槛或改判定方式；有就记下，收口时用 `tools/audit_corpus.py --compare` 对比本轮开始前后的全量语料；
  3. 新策略或新识别里的隐含假设：写死的坐标、"读不出就当作某个值"、"能识别名字就是英雄"这类推断；
  4. 同一类卡点的累计修复次数，和账本顶部的计数是否一致。
- `[improve-attention]`：goal 停在提问对话框（`↑↓ select · ↵ confirm`）等用户时，每个问题发一次，唤醒器继续运行。`improve` 看清问题后转告用户，或按 `AGENTS.md`「自主决策」代为回答；
- `[improve-notify]`：goal 连续 3 次读到已停止（不在回合内，不是 50 轮暂停，也不是在等提问），或 goal 的 agent 消失时发一次，送达后唤醒器退出。`improve` 按收口规则核对 goal 已结束、本机工作区干净、f1 无非终态会话，再按 `logs/improve/notes.md` 收口。

细节：
- 只在 `improve` 的 Herdr 状态为 `idle` / `done` 时发消息，不往正在进行的对话或回合里插话：定时消息遇忙跳过本次，结束消息每次读取后重试直到送达。用户正在 `improve` 输入框打字而 agent 仍为 `idle` 时，消息会和已输入的文字一起提交。
- 判断 goal 是否在回合内看输入框占位文字和转圈行，不看底栏的 `Goal running`（窄 pane 会截断底栏）。
- 日志和单实例锁：`logs/improve/notify-<goal pane>.log|.lock`；重复启动的第二个唤醒器读到锁即退出。
- 唤醒器在送达 `[improve-notify]` 后退出。用户之后 `/goal resume` 让第四层继续时，`improve` 要按上面的命令重新启动唤醒器。
- 用户要在运行中途有意停掉唤醒器时，创建 `logs/improve/notify-<goal pane>.off`，唤醒器在一个读取周期内自行退出；删掉该文件后才可重新启动。
- 收口接手时，先确认看守和唤醒器的进程都已退出（`ps -p "$(cat <锁文件>)"`），再用 `herdr pane close` 关掉它们留下的空 pane。只关进程已退出的 pane，不结束仍在运行的看守。
- 收口改动在第四层释放工作区之后才合入 `main` 并推送。第四层运行期间若要预先开发，放在独立 worktree 的分支里，不从 worktree 推送 `origin/main`，否则第四层下一次 push 会被拒、`tools/f1/sync.py` 的目标比对也会失败。
- **收口量化指标（元改进闭环）**：`improve` 每次收口结束前，从刚结束的第四层账本与 `git log` 提取一行记录追加到 `logs/improve/metrics.md`（git 忽略，永久保留），用于跨轮对比不同模型与第五层改动是否真的降低了摩擦：
  - 字段：`日期 / 目标`、`配置`、`结果与耗时（验收/受阻）`、`实机会话数 / 代码修复 commit 数 / 环境重跑数`、`单卡点平均修复轮数`、`工具与环境阻塞占比`、`上轮收口项验证与本轮新增收口项`。
  - `配置` 用于审计每次 goal 的运行条件，写五项：第四层的工具和模型（如 `devin swe-2-max`）、第五层的工具和模型（如 `agy gemini-4-neon-medium`）、启动 commit、上下文压缩阈值（未设写「默认」）、验证分层规则（如「每次修复受影响文件+冒烟，push 后后台全量」或「每次修复全量」）。第四层的启动配置从账本顶部读，第五层的从 `notes.md` 启动记录读。运行中途换模型时写成「A→B」。

## 日志与截图保留上限

为防止长周期运行下 1080p 截图无限膨胀，同时保留第四、五层复盘所需的文本记录，按「覆盖约 3 场冒险的调试体量」设以下保留上限，由 `tools/logs_cleanup.py`（默认 dry-run，加 `--apply` 才实际清理，测试在 `tests/test_logs_cleanup.py`）执行：

| 目录 / 文件 | 保留策略 | 估算上限 | 清理时机与边界 |
|---|---|---|---|
| `logs/goals/*.md`、`logs/improve/notes.md`、`logs/improve/metrics.md` | **永久保留** | 极小（纯文本） | 不自动删除，用于复盘第四、五层效率与元改进趋势 |
| `logs/goals/watch-*.log`、`logs/improve/notify-*.log` | 单文件超 **5 MB** 时截断保留末尾 1 MB | ≤ 5 MB / 文件 | 第五层收口时可执行 `python3 tools/logs_cleanup.py --apply` |
| Mac `logs/f1-pulls/<run_id>/` | 保留最近 **50 个 run**（约 3 场重调试冒险；保留 `live.png`） | ~80–150 MB | 第五层收口时执行 `python3 tools/logs_cleanup.py --apply`（有价值失败帧已按 `docs/offline-validation.md` 登记进库外测试集） |
| Mac `logs/` 根目录散落截图与 `f1-material-*` / `lorwright-sync-*` | 默认不动；显式加 `--include-legacy` 清理 7 天前历史文件 | 按需 | 手动确认后执行 |
| f1 `C:\Code\lorwright\logs\runs\` | 保留最近 **100 个终态 run**（跳过非终态会话） | ~200–300 MB | 属于「删除或归档 f1 数据」，仅在用户明确授权后执行 `python3 tools/logs_cleanup.py --f1 --apply` |
