# NOTES：用户的世界与术语

grilling 会话的原始笔记。已核实的事实注明来源；待用户确认的标 `待确认`。

## 项目与环境（来自仓库文档，2026-11-19）

- LoRwright：用截图 + 规则 + ADB 输入自动推进《符文之地传奇》英雄之路（Path of Champions）。纯脚本决策，运行时无 AI（ADR-0004）。
- 开发机：Mac，主检出目录 `main` 分支，默认提交并推送 `origin/main`。
- 运行机：**f1**，Windows，Pie64 模拟器，正式工作区 `C:\Code\lorwright`，`git pull --ff-only` 同步。SSH 经 Tailscale。另有 SYSTEM 看门狗（网络、游戏进程）。
- f1 同步默认执行，无需逐次授权（f1 有未提交改动、非终态会话或无法快进时停止并报告）；操作实机须先获授权（AGENTS.md）。
- 会话接口：`lorwright sessions start/status/events/stop`，产物在 `logs/runs/<run_id>/`（status.json、events.jsonl、snapshots/）。终态 `completed / stopped / failed / cancelled`，带 `reason`。
- 离线回归：完整 Python 回归约 2285 项；库外测试数据 `../lorwright-test-data`，`python tools/test_data.py` 准备。
- 进度/验收记录：`docs/status.md`；接手入口：`docs/handoff.md`。
- 工单：GitHub issues，总 issue #17。

## 术语（用户/项目自己的叫法）

| 术语 | 含义 |
|---|---|
| 单场战斗 | 运行时第 1 层循环，`Engine` |
| 单次冒险 | 运行时第 2 层循环，`AdventureLoop`，地图节点 + 战斗 + 奖励 + 结算 |
| 跨冒险任务 | 运行时第 3 层循环，按任务选/切冒险、英雄、地图，冒险间重置。目标设计，未实现 |
| 第四层循环 | 用户的叫法：三层运行循环之外，由 Agent 在 `/goal` 下驱动的开发迭代循环，= 开发闭环的自动化版。规格见 `workflows/dev-iteration.md` |
| 开发闭环 | Agent 读会话证据 → 定位卡点 → 修复 → 回归 → 实机复验 → 更新 status（architecture.md#开发闭环） |
| 一轮每周冒险 | 用户用例：用指定英雄把 3 个周常各跑一遍（例：「用 Elise 完成一轮每周冒险」）；周常已完成时用 `--weekly-replay-slot 1/2/3` |
| 每周冒险 / 周常 | 3 个每周冒险；已完成后用 `--weekly-replay-slot 1/2/3` 重玩 |
| 每月挑战 | 另一类任务，原生 1080p 月度寻路尚无样本 |
| 英雄 | 当前有 Jinx、Elise 两个英雄包 |

## 用户使用的 Agent 工具

- `/goal`：用户在 **Devin CLI** 里用（不是 Codex）。`/goal <objective>` 跨轮持续推进，直到 Devin 报告完成或受阻；`/goal` 看状态，`/goal resume` 中断后继续，`/goal clear` 清除。**跑满 50 轮自动暂停**。（Devin CLI changelog v3000.11.92）
- 实测：50 轮 = 50 个 agent 回合（每次自动续上算一轮）；暂停提示 `Goal paused after 50 turns. Use /goal resume to continue.`；经 herdr `agent prompt <name> "/goal resume"` 可续上，轮次接着计数；agent 看不到轮次编号；goal 两轮之间 herdr `agent_status` 显示 `idle`，要读画面文字判断。
- herdr 0.9.5 支持 `--kind devin`；本机在 herdr 内运行（`HERDR_ENV=1`）。新开 devin 会先问主题和目录信任。
- Devin CLI 子智能体：`subagent_general` 可读写，不继承父对话历史；前台运行会暂停父 agent，可弹出审批；后台运行时未批准的工具自动拒绝。
- Devin CLI 权限模式：Normal / Accept Edits / Smart / Bypass；Autonomous 仅 `--sandbox`。无人值守且不进沙箱时用 Bypass。
- 本机另装有 codex-cli 0.169.0、lark-cli、gh；第四层循环不用 Codex、不用飞书。
- 目标确认流程：用户先在外层对话与 Agent 敲定本轮目标，再用 `/goal` 启动（2026-11-19 用户确认）。
- 同时有一个"主对话"在 main 上推进项目（2026-11-19）。
