# MAA 与 MaaFramework：闭环、未知状态与观察接口

研究日期：2026-11-15。仅阅读官方文档与源码，未运行上游项目，未访问或操作 f1；本文用于 lorwright 原则讨论，不代表实施方案或规则变更。按现有 `docs/research/*.md` 命名习惯保存一份专题笔记。

## 结论与证据边界

| 问题 | 官方机制与结论 | 对 lorwright 的适用性与局限 |
| --- | --- | --- |
| 谁推进自动化？ | MAA 的 `ProcessTask::run()` 自己循环识别候选、执行动作、选择后继；MaaFramework 的 `PipelineTask::run()` 同样在核心内推进。无需外部 agent 对每一步发命令。[M1][F2] | 程序负责已支持流程的闭环；agent 观察证据、诊断与补能力。这是架构借鉴，不表示 lorwright 已覆盖完整冒险。 |
| 局部未知要全局停机吗？ | 两者都允许先等待/重试，再进入指定错误分支；没有“任意一次识别失败就结束所有任务”的通用规定。MAA 的队列层还会在普通任务链失败后继续后续任务，但内部致命错误/停止另有处理。[M1][M3][F1][F2] | 将未知限制在受影响的动作和阶段；能证明安全的独立流程可以继续。不能从这些机制推导出未知画面可以点击、任意失败都应忽略，或必须无限等待。 |
| 点击完成就是业务成功吗？ | MAA 的 `SubTaskCompleted` 在动作、延迟、子任务完成后发出，普通 `ProcessTask` 没有自动验证任意游戏业务结果；MaaFramework 节点的 `completed` 来自 `act.success`，随后才按 `next` 识别下一状态。[M1][F2] | 输入完成与预期结果成立应分别记录。关键操作应通过后续可见状态验证；等待画面稳定也不能证明目标已达成。 |
| 事件适合 agent 观察吗？ | MAA 提供任务链/子任务开始、完成、错误、额外信息；MaaFramework 提供任务、候选列表、识别、动作、节点流转等通知及关联 ID。[M4][F3] | 适合作为机器观察接口，辅助区分等待、识别失败、输入失败和流程完成；事件本身不是自动恢复策略，也不能把框架成功事件直接解释为冒险通关。 |
| 必须先有 GUI 吗？ | MAA 导出创建实例、注册回调、添加任务、启动/停止的 C API；MaaFramework 官方 Python 示例直接绑定资源和控制器，提交任务并等待结果，不经过框架 GUI。[M5][F4] | GUI 不是核心闭环的前置条件。CLI 可提供启动、参数、状态、事件、停止；GUI 可另做配置和可视化。这里说的是工具界面，无 GUI 壳不等于目标游戏无需图形环境。 |

## MAA：任务候选与失败边界

MAA 指 **MaaAssistantArknights**。官方任务协议的 JSON 字段是 `next`、`onErrorNext`、`exceededNext`、`maxTimes`、`sub`、`subErrorIgnored`；不要与 MaaFramework 的 snake_case 协议混写。[M2]

- `next` 按顺序检测，执行第一个匹配候选；当前任务及 `sub` 完成后继续。源码 `find_first()` 获取图像并调用识别器，`find_and_run_task()` 在配置的重试次数内重试。单轮无匹配不是立即停机。[M1][M2]
- 正常成功转 `next`；达到次数上限转 `exceededNext`；识别重试耗尽时，源码使用**前一个执行节点**的 `on_error_next`，没有该恢复列表才报 `SubTaskError` 并返回失败。因此不能把 `onErrorNext` 描述成能捕获所有内部异常的通用 try/catch。[M1]
- `subErrorIgnored` 默认 false；显式开启才忽略子任务失败。`Stop` 会中断当前 ProcessTask；空后继可以正常结束。这些都是任务作者定义的边界。[M1][M2]
- 更外层 `Assistant::working_proc()` 将普通任务返回值映射为 `TaskChainCompleted` 或 `TaskChainError`，弹出当前任务并继续队列；`InternalError`、`InitFailed` 会触发停止。`AllTasksCompleted` 是队列处理完成通知，不能独立证明队列每项业务都成功。[M3]

这证明 MAA 已实际使用“识别候选 → 动作 → 后继/恢复”的核心流程，但不证明它在任意未知游戏状态下都有恢复能力，更不证明它使用了下面 MaaFramework 的所有新协议能力。[M1][M3]

## MaaFramework：轮询、超时与结果验证

MaaFramework 是基于 MAA 经验重写的独立自动化框架；官方说明并非直接使用 MAA 源码。以下字段与行为只归属于 MaaFramework。[F0]

- `next` 是有序识别候选，命中后执行相应动作。未命中时按 `rate_limit` 重新截图/检测，直到 `timeout`；`timeout` 约束**当前节点的后继列表识别**，不是每个候选节点自身的识别时限。[F1][F2]
- 动作失败、后继识别超时、没有可用候选，可进入 `on_error`。恢复候选识别命中后退出错误处理状态，并可继续其后继链；恢复列表仍无法处理错误则任务失败。不能概括为“on_error 只能执行一个节点且不能继续”。[F1][F2]
- 流程可由后继图反复访问节点；`[JumpBack]` 还可在处理一条支链后回到父节点重新识别。这是有定义的流转能力，不等于能自动理解未建模场景，也不必据此为 lorwright 引入 DSL。[F1][F2]
- `PipelineTask::run_next()` 将节点完成判定设为动作返回的 `act.success`；要证明点击后已进入战斗、出牌已结算等业务结果，应由任务作者把相应可见状态写进后继识别。`post_wait_freezes` 判断画面变化程度，不能代替语义上的结果验证。[F1][F2]

## 通知与界面的职责

MAA 的核心有工作线程和消息队列；`msg_proc()` 调用外部回调，任务推进不依赖界面逐步确认。[M3] MaaFramework 通知包含 `Tasker.Task.*`、`Node.NextList.*`、`Node.Recognition.*`、`Node.Action.*`、`Node.Transition` 等不同层级，并携带 `task_id` 及相应节点/识别/动作标识；它们很适合向观察方解释“正在等哪个候选、哪个动作失败”。具体事件集应按集成版本确认。[F3]

MaaFramework 文档要求回调快速返回并自行保证线程安全，不能在回调里等待当前操作或销毁相关对象；异步处理前需复制回调数据。因此“回调复制事件 → 外部消费”适合作为观察边界，不能让慢速 agent 推理阻塞执行线程。持久化、重连、JSONL schema 等是应用层另需定义的契约，不能仅凭框架有回调就宣称已具备。[F3]

GUI 的价值是帮助人查看配置、截图与进度；是否建设应由这些需求决定。官方 API 与无框架 GUI 示例已经足以支持“先让核心自主跑通，再通过 CLI/事件观察”的原则，但不构成 lorwright 现有 CLI 功能或实际可靠性的验证。[M5][F4]

## 官方来源（本次实际读取）

下列源码/文档是移动分支快照，访问日期为 2026-11-15；未来行为可能变化。MaaFramework `main` 查询时的 SHA 为 `218bfabcc502bc5e152af36bceebe016792d9686`；MAA 仅核对 `dev` 文件，未固定其提交号。以链接所列项目和文件为事实归属，不使用搜索结果中的第三方文章作证据。

- [M1] MAA 源码，`ProcessTask.cpp`：https://raw.githubusercontent.com/MaaAssistantArknights/MaaAssistantArknights/dev/src/MaaCore/Task/ProcessTask.cpp
- [M2] MAA 官方任务协议，`task-schema.md`：https://raw.githubusercontent.com/MaaAssistantArknights/MaaAssistantArknights/dev/docs/zh-cn/protocol/task-schema.md
- [M3] MAA 源码，`Assistant.cpp`：https://raw.githubusercontent.com/MaaAssistantArknights/MaaAssistantArknights/dev/src/MaaCore/Assistant.cpp
- [M4] MAA 官方回调协议，`callback-schema.md`：https://raw.githubusercontent.com/MaaAssistantArknights/MaaAssistantArknights/dev/docs/zh-cn/protocol/callback-schema.md （该页提示可能过时，任务循环行为以 [M1][M3] 源码交叉核对。）
- [M5] MAA 公共接口，`AsstCaller.h`：https://raw.githubusercontent.com/MaaAssistantArknights/MaaAssistantArknights/dev/include/AsstCaller.h
- [F0] MaaFramework 官方 README，项目定位及与 MAA 的关系：https://raw.githubusercontent.com/MaaXYZ/MaaFramework/main/README.md
- [F1] MaaFramework 官方任务流水线协议：https://raw.githubusercontent.com/MaaXYZ/MaaFramework/main/docs/zh_cn/3.1-%E4%BB%BB%E5%8A%A1%E6%B5%81%E6%B0%B4%E7%BA%BF%E5%8D%8F%E8%AE%AE.md
- [F2] MaaFramework 源码，`PipelineTask.cpp`：https://raw.githubusercontent.com/MaaXYZ/MaaFramework/main/source/MaaFramework/Task/PipelineTask.cpp
- [F3] MaaFramework 官方回调协议：https://raw.githubusercontent.com/MaaXYZ/MaaFramework/main/docs/zh_cn/2.3-%E5%9B%9E%E8%B0%83%E5%8D%8F%E8%AE%AE.md
- [F4] MaaFramework 官方 Python 集成示例，`demo1.py`：https://raw.githubusercontent.com/MaaXYZ/MaaFramework/main/sample/python/demo1.py
- [F5] MaaFramework 分支快照查询：https://api.github.com/repos/MaaXYZ/MaaFramework/commits/main

本次没有性能、恢复成功率或真实游戏端到端实测；结论仅涉及已核实的控制机制及其适用边界。
