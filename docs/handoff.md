# 接手入口

当前目标：按用户最新授权，程序自动退出「煞星傳送門」最终胜利结算，再进入剩余每周冒险持续战斗；卡点由 Agent 修复、验证、同步并恢复。已确认游戏获胜与 S 评级，但旧 `completed / adventure_victory` 仅证明到达最终页，没有退出结算。结算及完成标记修复已部署 f1 `7efd85c`，独立新图为 2/3 完成；`20261118T024821-a3639a07edd4` 已自主完成首战；奖励费用 6 字模缺口已由 `8080573` 修复部署，`20261118T025748-f4785c9bdd2f` 已领奖回图，seq 51 的辅助英雄 `support_undecided` 已由 `d50606c` 费用 4 字形修复，恢复 `20261118T030413-094cf6ff8da7` 已完成下一战、领奖回图并到商店，seq 552 为 `panel_transition_timeout`，完整事件已核验。新商人背景使标题灰度匹配失败，`6f80f7b` 金色字迹修复已部署，本地及 Windows 各 292 项相关检查通过。新会话 `20261118T032032-67bcb3478a19` 已单次离店、核验回图并进入「林地守護者」战斗，随后 seq 489 为 `action_readiness_unverified`，完整事件已核验且监测结束；`88bc251` 修复宽高亮框内攻击者漏检，本地及 Windows 各 399 项通过。battle 恢复 `20261118T033434-68266b51b097` 的 113 条事件及独立胜利任务结算图已核验，adventure `20261118T033647-3238438657d0` 已处理战后奖励并进入英雄道具宝箱，seq 140 为 `panel_transition_timeout`；完整事件与独立新图已核验；六字标题变体修复保留原 0.94、亮度与残差核验，原停止帧红绿及本地 309 项通过，待部署恢复；实机结果以 `status.md` 最新记录为准。本次经历开发恢复，不能计全程无人值守。项目直接在 `main` 更新。

## 先读什么

当前能力、运行代码、会话与验证以 [`status.md`](status.md) 为准。本页仅保留接手动作。持续规则见 [`../AGENTS.md`](../AGENTS.md)，命令见 [`cli.md`](cli.md)，架构见 [`architecture.md`](architecture.md)，环境及部署参考见 [`environment.md`](environment.md) 与 [`../tools/f1/`](../tools/f1/)。

## 当前接手动作

1. 最终维克特战斗 `20261117T143149-6ac9275c6a8f`：807 条事件，`completed / battle_end`；独立任务结算图确认获胜。随后冒险 `20261117T143600-d08db5454d81`：44 条事件，`completed / adventure_victory`；独立最终页为 S、生命 43/46、金币 1860、完成时间 2:49:58。两份完整事件的信封、run_id 和连续 seq 已核验。
2. `hand --view expanded|collapsed` 已通过真实 Engine 合成状态与正式 CLI 实拍离线回放验收：固定整体截止、最多一次视图输入、连续两张新鲜目标帧；已有控制者时受设备锁保护。它不插入正在运行的父出牌，不装配普通策略或重连重启。命令与错误退出见 `cli.md`。
3. 共享费用序列已覆盖手牌、弃牌及奖励的双位数解码与可见残笔拒绝，原分类阈值保留；真实十费徽章、缺失字模和部分倾角误分类仍待验收，不能宣称完整 0–10 已解决。后续按实际卡点补证据，不机械扩展全量测试或性能优化。
4. 当前运行基线为 f1 `88bc251`，先查询上述明确会话，再读增量事件与关联截图。程序已进入剩余冒险，不能部署覆盖活动控制程序；后续修复先确认终态、核对 `C:\Code\lorwright` 的版本、工作区、控制进程与会话锁，保留独立改动。不要运行旧冒险恢复脚本，也不沿用上一场起手/Jinx/火箭参数。GitHub Actions 最近核实的失败是账户 billing 锁定导致 job 未启动，弱化断言无法修复。
5. 卡点先看关联事件与新帧，再修复实际识别或闭环能力。实拍离线、合成状态序列、部署、实机分支与完整冒险分别记录。局部修改做相关检查；共享感知或实际退化再扩大验证。

## 保持的边界

- 输入已发送不等于动作成功；未知画面有界等待，期限到达停止，不重发旧输入。明确结算背景才可取得既有单次阶段观察预算。
- 全帧含账户信息，只留 f1 `logs/` 或库外诊断；入库仅安全裁剪并实际查看，来源见 [`../tests/fixtures/README.md`](../tests/fixtures/README.md)。
- 完整数字范围、多位数基础能力仍有 P0 缺口。Jinx、Elise 各自整个冒险无人值守均未验收；测试通过、单场获胜或开发恢复不能替代该目标。GUI 暂缓。
- `docs/research/mission-console.prototype.html` 已按用户要求从工作区移除，原未跟踪内容保存在 scoped stash；不要恢复。

## 历史与其余工作

[总 issue #17](https://github.com/DeyunMa/lorwright/issues/17) 与 [统一能力审计](research/capability-loop-audit-20261116.md) 提供能力缺口背景。弃牌更多数量及外观、选择形态、Elise 迁移、冷启动、多冒险与跨冒险重置仍待验收；当前事实查状态页，不沿用历史“当前”结论。

历史资料：[开发期历史](history/status-development-loop-20261116.md)、[更早交接](history/handoff-before-control-loop-20261115.md)、[更早状态](history/status-before-control-loop-20261115.md)、[更早架构](history/architecture-before-control-loop-20261115.md)。
