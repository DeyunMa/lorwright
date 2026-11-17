# 接手入口

更新日期：2026-11-17。当前目标是完成整个冒险，遇卡点继续修复、验证、提交、同步 f1 和恢复；这些操作已有用户授权。用户在暂停后已明确要求继续。项目直接在 `main` 更新。本次冒险经历开发恢复，不能计全程无人值守。

## 先读什么

当前能力、运行代码、会话与验证以 [`status.md`](status.md) 为准。本页仅保留接手动作。持续规则见 [`../AGENTS.md`](../AGENTS.md)，命令见 [`cli.md`](cli.md)，架构见 [`architecture.md`](architecture.md)，环境及部署参考见 [`environment.md`](environment.md) 与 [`../tools/f1/`](../tools/f1/)。

## 当前接手动作

1. 查看状态页的最新 checkpoint，核对 f1 `C:\Code\lorwright` 的版本、工作区、控制进程与会话锁；保留独立改动。入口为 `.venv\Scripts\lorwright.exe`。
2. 当前运行代码 `dd6a692` 已部署，本地完整 1824、f1 单位/卡面专项 95 通过。后续会话 `20261117T121036-e413c248e6e9` 从奖励详情超时页经首页重新入战，在普通单位出牌核验处停止。当前补固定单位结算窗口，并按用户要求让子智能体落实同帧已核验生命框的通用证据传递；验证和部署进度以状态页为准。
3. 先核对该会话状态与关联新图，再继续战斗、奖励及剩余节点，直到明确 `adventure_victory`。旧场已召唤参数没有用于新会话；中局恢复必须重新核对同场证据，新战换牌应重置策略。
4. 卡点先看关联事件与新帧，再修复实际识别或闭环能力。实拍离线、合成状态序列、部署、实机分支与完整冒险分别记录。局部修改做相关检查；共享感知或实际退化再扩大验证。

## 保持的边界

- 输入已发送不等于动作成功；未知画面有界等待，期限到达停止，不重发旧输入。明确结算背景才可取得既有单次阶段观察预算。
- 全帧含账户信息，只留 f1 `logs/` 或库外诊断；入库仅安全裁剪并实际查看，来源见 [`../tests/fixtures/README.md`](../tests/fixtures/README.md)。
- 完整数字范围、多位数基础能力仍有 P0 缺口。Jinx、Elise 各自整个冒险无人值守均未验收；测试通过、单场获胜或开发恢复不能替代该目标。GUI 暂缓。
- `docs/research/mission-console.prototype.html` 为无关未跟踪文件，保留并排除提交。

## 历史与其余工作

[总 issue #17](https://github.com/DeyunMa/lorwright/issues/17) 与 [统一能力审计](research/capability-loop-audit-20261116.md) 提供能力缺口背景。弃牌更多数量及外观、选择形态、Elise 迁移、冷启动、多冒险与跨冒险重置仍待验收；当前事实查状态页，不沿用历史“当前”结论。

历史资料：[开发期历史](history/status-development-loop-20261116.md)、[更早交接](history/handoff-before-control-loop-20261115.md)、[更早状态](history/status-before-control-loop-20261115.md)、[更早架构](history/architecture-before-control-loop-20261115.md)。
