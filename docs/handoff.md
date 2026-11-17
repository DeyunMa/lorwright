# 接手入口

更新日期：2026-11-17。当前 Jinx「煞星傳送門」冒险已完成，最终页明确显示「勝利」、S 评级；本次经历开发修复和恢复，不能计全程无人值守。项目直接在 `main` 更新。通关后已按用户顺序完成手牌 CLI 与共享费用序列的本地验收；不要为了验证重新开启冒险。

## 先读什么

当前能力、运行代码、会话与验证以 [`status.md`](status.md) 为准。本页仅保留接手动作。持续规则见 [`../AGENTS.md`](../AGENTS.md)，命令见 [`cli.md`](cli.md)，架构见 [`architecture.md`](architecture.md)，环境及部署参考见 [`environment.md`](environment.md) 与 [`../tools/f1/`](../tools/f1/)。

## 当前接手动作

1. 最终维克特战斗 `20261117T143149-6ac9275c6a8f`：807 条事件，`completed / battle_end`；独立任务结算图确认获胜。随后冒险 `20261117T143600-d08db5454d81`：44 条事件，`completed / adventure_victory`；独立最终页为 S、生命 43/46、金币 1860、完成时间 2:49:58。两份完整事件的信封、run_id 和连续 seq 已核验。
2. `hand --view expanded|collapsed` 已通过真实 Engine 合成状态与正式 CLI 实拍离线回放验收：固定整体截止、最多一次视图输入、连续两张新鲜目标帧；已有控制者时受设备锁保护。它不插入正在运行的父出牌，不装配普通策略或重连重启。命令与错误退出见 `cli.md`。
3. 共享费用序列已覆盖手牌、弃牌及奖励的双位数解码与可见残笔拒绝，原分类阈值保留；真实十费徽章、缺失字模和部分倾角误分类仍待验收，不能宣称完整 0–10 已解决。后续按实际卡点补证据，不机械扩展全量测试或性能优化。
4. 通关使用 `108e2a2`；后续能力代码已安全快进部署 f1 `4effec9`，Windows 同组手牌 473 / 数字 225 项通过。现场仍为最终胜利页，无活动控制者；正式 hand 实机 `20261117T150254-5aa585a8cb45` 共 33 条事件，零输入，固定截止后 `stopped / hand_view_unverified`，没有点击继续。任何后续部署先核对 `C:\Code\lorwright` 的版本、工作区、控制进程与会话锁，保留独立改动；不要运行旧的冒险恢复脚本。GitHub Actions 最新失败是账户 billing 锁定导致 job 未启动，需账户侧处理，弱化断言无法修复。
5. 卡点先看关联事件与新帧，再修复实际识别或闭环能力。实拍离线、合成状态序列、部署、实机分支与完整冒险分别记录。局部修改做相关检查；共享感知或实际退化再扩大验证。

## 保持的边界

- 输入已发送不等于动作成功；未知画面有界等待，期限到达停止，不重发旧输入。明确结算背景才可取得既有单次阶段观察预算。
- 全帧含账户信息，只留 f1 `logs/` 或库外诊断；入库仅安全裁剪并实际查看，来源见 [`../tests/fixtures/README.md`](../tests/fixtures/README.md)。
- 完整数字范围、多位数基础能力仍有 P0 缺口。Jinx、Elise 各自整个冒险无人值守均未验收；测试通过、单场获胜或开发恢复不能替代该目标。GUI 暂缓。
- `docs/research/mission-console.prototype.html` 为无关未跟踪文件，保留并排除提交。

## 历史与其余工作

[总 issue #17](https://github.com/DeyunMa/lorwright/issues/17) 与 [统一能力审计](research/capability-loop-audit-20261116.md) 提供能力缺口背景。弃牌更多数量及外观、选择形态、Elise 迁移、冷启动、多冒险与跨冒险重置仍待验收；当前事实查状态页，不沿用历史“当前”结论。

历史资料：[开发期历史](history/status-development-loop-20261116.md)、[更早交接](history/handoff-before-control-loop-20261115.md)、[更早状态](history/status-before-control-loop-20261115.md)、[更早架构](history/architecture-before-control-loop-20261115.md)。
