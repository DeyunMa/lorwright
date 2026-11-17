# 统一能力与分层循环审计

审计日期：2026-11-16，基线为本地 `main` / `2a68ee8`。审计当时 f1 暂停，未修改运行代码；已创建总 issue [#17](https://github.com/DeyunMa/lorwright/issues/17) 及缺少的实现票，复用 #10、#15 承接 T1、T5。GitHub 跟踪实施进度，本文保留审计证据与拆分依据；后续授权与实际改动见下方“后续实施记录”，当前状态见 [`../status.md`](../status.md)。

## 目标模型

用户期望由统一基础能力组合出自主循环：战斗动作 → 单场战斗 → 战斗结算 → 单场冒险 → 冒险结算 → 多场冒险。底层能力负责观察、语义动作及可见结果，循环负责顺序、上下文、截止和终态。英雄规则在适用的决策点优先，未命中时继续默认规则。

这组层次表达业务目标，不预设每层都要新增类或独立循环。是否抽取 Module，取决于真实重复、状态归属和调用关系；已实现的能力优先保留。

| 层次 | 应回答的问题 | 主要输入或产出 |
|---|---|---|
| 可见状态 | 当前可以可靠知道什么？ | UI 阶段、手牌/单位、双方血量、普通/法术法力、攻击权、读数有效性 |
| 单次动作 | 哪个动作现在适用，结果是否成立？ | 语义动作、必要证据、目标/确认交互、输入记录、待核验结果 |
| 单场战斗 | 如何反复行动直至战斗结束？ | 动作循环、英雄/默认策略、胜负或未知结束、停止原因 |
| 战斗结算 | 如何处理结果及后续奖励？ | 任务/奖励插页、选择与确认、明确后继 |
| 单场冒险 | 如何选择节点并组合战斗及节点交互？ | 当前节点＋有效连线、节点类型、旅行、子流程结果 |
| 冒险结算 | 本次冒险结果是什么，是否可离开结果页？ | 明确胜利/失败/停止、结果证据、回到入口的后继 |
| 多场冒险 | 下一次何时开始，何时停止？ | 目标、选择规则、完成数量/预算、每场结果、取消与有限重试 |

单位、血量、法力和攻击权是主要战斗信息；循环同时需要当前交互与待核验动作的上下文。英雄优先适用于合法候选的决策顺序，不能让未知界面、过期输入或未完成交互失去统一约束。规则可以在会话/子流程装配时注入，再在对应决策点运行，无需每次轮询重新加载。

## 审计方法与状态

由一个只读子智能体检查核心能力、循环、规则装配及测试，主线程核对关键引用。另通过 `gh issue list` 只读核对所有开放 issue 与已关闭事项。架构判断以当前代码和具体消费者为证据，局部实机及离线测试不代替端到端验收。

基线完整离线检查为 **1448 passed，零 failures / errors / skipped**。该结果证明已有回归通过，不证明拟议架构已经实现。

## 后续实施记录

用户次日授权先本地修改验证，再同步 f1 并继续。首个纵向改动为 `67aa705`：T1 增加本帧可见单位数量下界，零检出保留未知；T3 保留待确认出牌的原始 `ActionOutcome`、预期及截止，确认后允许延迟证据，附加交互不续期；结束回合后已有敌军继续增员可依据新鲜观测重新路由，不报告原动作成功。

本地完整回归 **1461 passed，零 failures / errors / skipped**，专项 **215 passed**，Ruff 通过。两个不同战斗实拍贯通 parser 到 Engine，前态删减单位明确标为合成；确认延迟和原预算使用合成序列。`main` 已推送，f1 正式目录快进至 `67aa705`，相关专项 **175 passed**。恢复时现场已回到登录页；现有自动登录流程后以新截图确认进入主页，未沿用旧战斗恢复参数。

自主冒险会话 `20261117T014309-ca7207857b14` 从主页继续冒险，经地图节点进入战斗并确认换牌；确认约 8.5 秒后首次稳定识别到己方行动时，已超过普通 8 秒动作窗口，以 `action_timeout` 停止。新增真实 Engine 合成时序在旧实现上失败两例；换牌确认纳入至少 20 秒独立阶段窗口，附加确认仍受父出牌截止限制。修复 `6d3dabe` 本地完整 1463、专项 228 项通过，已推送并快进同步 f1，目标环境专项 188 项通过，均零 failures / errors / skipped。后续实机结果以 [`../status.md`](../status.md) 为准。

恢复会话 `20261117T020400-b80b4f63bb22` 把一张 1 费牌记为 Jinx 并拖出，原帧实际是奈德麗形态选择，以 `unknown_target` 停止。已有八牌实拍也复现相邻卡面借名；`9f85e1b` 为 ORB 身份增加本牌费用徽章的几何归属，保留未知，不新增形态选择规则。本地完整 1464、最终专项 246、f1 专项 246 项通过，均零 failures / errors / skipped，已部署。之后单轮采样只见 UNKNOWN、零输入；图为游戏“重新连线中……”，部署后新图仍持续同页，未再启动冒险。

T1/T3 均仅完成这些部分，行动资格/集合完整性、其他目标/选择阶段及其余票仍未完成。T3 消费当前动作需要的 T1/T2 契约，不要求先完成整票；T6 可以先验证 Jinx 结果交接，不以整个 Elise 迁移完成为前提。实施按可验证流程推进，票间依赖不当作全量重构门槛。

下文“当前”与缺口均指原审计基线 `2a68ee8`，实施进度以本节及 GitHub ticket 为准。

## 当前骨架与应保留能力

| 层次 | 当前实现 | 结论 |
|---|---|---|
| 设备与观测 | `Device → Frame → StateParser → GameState` | 共享截图、状态和坐标模型已存在；字段证据还不完整 |
| 动作与战斗 | `Router → Action → Translator → ClickPlan → ActionOutcome`，由 `Engine` 驱动 | 已有小 interface 和实际行为，保留并完善多阶段生命周期 |
| 地图导航 | `reachable_nodes → node_kind → pick_map_node` | 当前节点与连线已统一；视觉形状检测和业务类型识别应继续分工 |
| 战斗结算与节点 | `AdventureLoop` 内的结果页、奖励与节点处理器 | 已能组合推进多种页面；转场观察、场景认可和结果表达仍分散 |
| 单次冒险 | `AdventureLoop.run()` 调用战斗及节点流程 | 主要骨架已接通，尚未全程无人值守验收 |
| 冒险最终页 | `_complete_adventure` 保存胜利证据并返回 | 仅完成胜利识别，未完成退出最终页和启动下一次 |
| 多冒险 | 当前 CLI/runtime 每会话执行一次 battle 或 adventure | 尚无队列、次数、逐次结果和跨冒险重置 |

保留 `None` 弃权、`NO_OP` 等待、局部未知限制局部动作、结果未知时有界停止，以及 runtime 与游戏决策分工。Jinx 的火箭/重建后验、Elise 的蜘蛛评分和进攻偏好仍留在英雄包；通用的候选资格、阶段交接与结果核验由共享能力提供。

## 已核验的主要问题

### 1. 可见状态尚未表达“未知、确认空、确认可行动”的区别

[GameState 与 Unit](../../src/lorwright/core/models.py#L102) 使用空单位列表、`can_attack=True`、`stunned=False` 等默认值；[StateParser](../../src/lorwright/core/perceive/state.py#L118) 与 [to_units](../../src/lorwright/core/perceive/units.py#L234) 没有生产单位集合完整性及完整行动资格的证据。列表为空同时可能是空场、未配置、遮挡或漏检。攻击令牌的布尔值也没有区分“确认没有”和“未读到”；`max_mana` 暂被赋为当前法力。

这些字段被候选满场判断、攻击/格挡和动作后验消费，影响的不只是显示。应扩展现有观测契约，明确每项事实的来源与未知含义，并按具体动作迁移消费者。不能靠把缺省值改名为已识别来完成能力。

### 2. 多阶段动作的父动作与附加交互没有完整生命周期

[ActionOutcome](../../src/lorwright/core/loop/outcome.py#L140) 只在敌方空场变为有单位时交接结束回合后继；敌方已有单位再增加仍等待。[Engine](../../src/lorwright/core/loop/engine.py#L262) 在确认动作成功的同一帧立即核验原出牌，尚缺证据就 `staged_play_unverified`，没有继续观察最终结果的阶段。

主线程纯内存复核：敌方单位 1→2、UI 和法力不变时，结束回合后验先 `waiting`，到截止 `timed_out`。[现有后验测试](../../tests/test_action_outcome.py#L34) 和 [确认后停止测试](../../tests/test_engine_outcome.py#L833) 锁住了部分现行限制；全套通过不能代替所需的新行为测试。

应保留单次输入、`NEEDS_INPUT` 和原截止，将“父动作待结果 → 附加输入 → 最终结果”统一为有界生命周期。状态变化只允许有依据的重新路由，不能一律视为成功。

### 3. 英雄能力声明小于实际依赖，Elise 冒险路径有明确缺口

[ChampionPack](../../src/lorwright/core/champions/base.py#L42) 仅声明牌表、偏好及 `make_policy`；实际消费者还通过 `getattr` 取视觉、地图身份及奖励 hook。[JinxPack](../../src/lorwright/core/champions/jinx/__init__.py#L34) 有地图头像和所选英雄识别，[ElisePack](../../src/lorwright/core/champions/elise/__init__.py#L30) 没有。

[继续冒险](../../src/lorwright/core/loop/adventure.py#L396) 在缺少所选英雄识别时停止；[_find_next](../../src/lorwright/core/loop/adventure.py#L636) 在没有头像 hook 时却把 `hero=None` 传入导航，从而使用历史诊断的中心推断。相同缺项在不同消费者中得到不同处理。

应按 loop 声明必需/可选能力，在装配时检查；生产导航需要明确当前位置证据。保留现有英雄包发现机制，不另建插件框架。Elise 缺失视觉能力仍需实拍素材和验证。

### 4. Elise 重复承担通用阶段与出牌尝试状态

[SpiderAggroPolicy](../../src/lorwright/core/champions/elise/policy.py#L121) 自管 `_pending_play/_pending_cost/_unplayable/_needs_target`，用后续牌数推断出牌失败，并自行处理确认、攻击行和结束回合。这与 Engine 统一后验存在第二套生命周期；Engine 先等待或停止时，旧的“下次 decide 换牌”逻辑未必能运行。

主线程复核：场上已有 6 个单位、手持可支付单位时，Elise 提出 `PLAY_CARD`，共享 `PlayUnitPolicy` 弃权。按费用记失败也可能影响同费用其他牌；策略还缺少明确的新战斗记忆清理。

应保留蜘蛛排序、评分和全员进攻偏好，候选合法性及动作阶段复用共享能力。策略记忆由已核验结果和显式战斗生命周期推进。

### 5. 冒险丢弃 Frame 时效，各处理器分别维护转场观察

[AdventureLoop._frame](../../src/lorwright/core/loop/adventure.py#L1176) 只返回 `frame.image`，[_tap](../../src/lorwright/core/loop/adventure.py#L1163) 没有执行前帧龄检查。战斗的帧时效约束尚未覆盖冒险点击。场景认可同时存在于主循环、[_recognized_after_home](../../src/lorwright/core/loop/adventure.py#L579) 和节点转场；多个处理器各自实现一次输入、轮询、允许后继及停止。

当前有限次数等待确实会结束，但 `_wait(..., wait_s=...)` 主要报告观测期限，不是共用的单调时钟截止；截图和识别耗时可扩大实际等待。应先抽取小 interface 的冒险观测/转场能力，保留 Frame、设计图及坐标变换，再迁移两个真实消费者。各页面视觉判据和业务后继继续独立。

### 6. 英雄优先与默认继续的组合语义不一致

战斗的 [Router](../../src/lorwright/core/decide/router.py#L61) 已实现英雄策略先行、`None` 后继续。问题在局部接线：[_battle_layers](../../src/lorwright/cli/app.py#L384) 中 `PlayUnitPolicy` 排在 `HeroFirstPolicy` 前。主线程复核：专属起手弃权后，3 费 Jinx 与 1 费单位同时可出，实际命中 `play_unit` 选择便宜单位；[装配测试](../../tests/test_battle_layers.py#L39) 也固定了这个顺序。这是默认规则内部“先出英雄”原则的接线偏差，不表示英雄包策略整体失去优先权。

[卡牌奖励](../../src/lorwright/core/loop/adventure.py#L972) 则按专属 hook 是否存在选择实现，hook 返回 `None` 后停止，默认规则不会继续。但 Jinx 的 `None` 还可能表示证据不足，不能简单使用 `hero_pick(...) or default_pick(...)`。需要统一“不适用”“有决定”“证据不足/等待”的含义，再按适用 loop 装配。

### 7. CI 尚未提供当前代码的自动验证

[最新远端运行](https://github.com/DeyunMa/lorwright/actions/runs/43881673733) 对应 `9ada4ab`，状态为 failure。GitHub 检查注解确认作业在启动前受账户侧限制；步骤列表为空、失败日志未取得，未执行 pytest。该结果不能解释为当前测试失败，也不等于本地两个新提交经过 CI。

另从 [workflow](../../.github/workflows/tests.yml#L16) 可见它仍按“测试只依赖纯逻辑”安装少量依赖，与当前视觉/CLI 测试及 [项目依赖](../../pyproject.toml#L6) 不一致。这是恢复执行后需核对的问题，不能当作本次未启动的原因。账户侧详细信息不写入公开 issue；本地完整回归 **1448 passed** 单独记录。

## 改造顺序与已发布 ticket

总 issue 为 [#17：统一基础能力与分层自主循环](https://github.com/DeyunMa/lorwright/issues/17)。八项子任务如下；完整实施范围、验收条件及后续进度以 GitHub 为准。本轮只拆票，尚未实施架构改造。

| 本地 ID | GitHub ticket | 依赖 |
|---|---|---|
| T0 | [#18：有效 CI 与真实验证入口](https://github.com/DeyunMa/lorwright/issues/18) | 无，独立处理 |
| T1 | [#10：共享状态与动作必要证据](https://github.com/DeyunMa/lorwright/issues/10) | 无，复用旧票 |
| T2 | [#19：英雄能力与规则结果](https://github.com/DeyunMa/lorwright/issues/19) | 无，可与 T1 并行 |
| T3 | [#20：多阶段动作生命周期](https://github.com/DeyunMa/lorwright/issues/20) | T1、T2 |
| T4 | [#21：Elise 共享能力与规则顺序](https://github.com/DeyunMa/lorwright/issues/21) | T1–T3 |
| T5 | [#15：冒险观测、转场与奖励](https://github.com/DeyunMa/lorwright/issues/15) | T1、T2，复用旧票 |
| T6 | [#22：结算结果与交接](https://github.com/DeyunMa/lorwright/issues/22) | T3–T5 |
| T7 | [#23：有界多冒险与最终验收](https://github.com/DeyunMa/lorwright/issues/23) | T6 |

以下保留拆分时的范围与验收摘要。

### T0：恢复有效 CI 并对齐真实验证入口

- 范围：处理作业执行前提，再核对干净环境依赖和测试命令；账户侧事项由用户处理。
- 验收：新提交能在 CI 实际进入安装及 pytest，完整套件与 Ruff 有明确结果；区分启动失败、依赖失败和测试失败。
- 依赖：无；与架构设计并行。已发布为 [#18](https://github.com/DeyunMa/lorwright/issues/18)，独立跟踪 CI。

### T1：统一可见状态与动作必要证据

- 范围：在现有 `GameState/Reading` 上表达单位集合可见性、空场与拒识、资格未知、帧时效和字段真实语义；逐个迁移满场、攻击/格挡和动作后验消费者。
- 验收：同一状态契约可供英雄与默认规则使用；未知不伪装为可攻击或空场；无关血量/牌名未知仍允许有依据的动作；真实感知与决策接线有组合测试。
- 依赖：无。复用 [#10](https://github.com/DeyunMa/lorwright/issues/10)，素材矩阵关联 [#13](https://github.com/DeyunMa/lorwright/issues/13)。

### T2：声明按 loop 使用的英雄能力与规则结果

- 范围：声明战斗、地图身份、继续冒险、奖励的现有 hook，定义不适用、决定及证据不足的组合语义；装配时报告能力缺项。
- 验收：Jinx、Elise 均能列出支持与缺失能力；适用规则英雄优先，不适用时默认继续；证据不足不会被普通 fallback 误当授权；缺关键能力在输入前明确停止。
- 依赖：无，可与 T1 并行。已发布为 [#19](https://github.com/DeyunMa/lorwright/issues/19)，关联 #5、#15、#16；前置检查部分关联 #12。

### T3：统一多阶段动作与有界结果生命周期

- 范围：父动作、目标/确认/选择附加输入、最终结果使用同一生命周期，保留原截止与一次输入限制；先处理已有敌军后增员、确认后证据延迟。
- 验收：明确后继重新路由；延迟证据可在期限内被接受；持续未知按原预算停止；无重复输入、无原牌提前计数、无阶段无限续期。新行为回归在旧代码失败。
- 依赖：T1、T2。已发布为 [#20](https://github.com/DeyunMa/lorwright/issues/20)，跟踪 [#5](https://github.com/DeyunMa/lorwright/issues/5) 的实现工作，关联 [#6](https://github.com/DeyunMa/lorwright/issues/6)。

### T4：Elise 复用默认能力并核对实际规则顺序

- 范围：保留蜘蛛评分、换牌与进攻偏好，迁移共享候选资格、攻击声明及阶段处理；用结果回调和战斗边界管理策略记忆；修正默认“先出英雄”接线。
- 验收：英雄规则有决定时优先，弃权时默认继续；满场不提出无依据的单位出牌；同费用不同牌不共用失败身份；跨战斗记忆清理；由真实 Engine 驱动，不能只直接调用 policy 验收。
- 依赖：T1–T3。已发布为 [#21](https://github.com/DeyunMa/lorwright/issues/21)，跟踪 #5 的实现工作，与 #10 的观测结果对接。

### T5：统一冒险观测、转场与奖励规则接入

- 范围：共享 Frame/场景事实/坐标变换/截止，先迁移节点进入和一种奖励，再迁移其他现有处理器；按 T2 接入英雄与默认奖励规则，移除生产导航的诊断推断路径。
- 验收：过期图不点击；同帧场景事实在调用方一致；一次输入后只观察允许后继；缺失英雄身份明确报告；奖励不适用与证据不足各走对应路径。Elise 视觉能力有样本才宣称支持。
- 依赖：T1、T2。更新 [#15](https://github.com/DeyunMa/lorwright/issues/15)，入口消费者关联 #16；现有节点业务与视觉条件保留。

### T6：明确战斗、奖励与冒险结算结果

- 范围：区分战斗结束、可确认胜败、奖励交互完成、到账未知、冒险最终胜利、退出最终页和失败/停止；在现有 `LoopResult` 及事件上明确交接契约。
- 验收：上层只依据明确子流程结果继续；`battle_end` 不当作获胜，回图不当作到账，最终页识别不当作全程无人介入；真实 Engine + AdventureLoop 的组合序列覆盖正常、失败、未知与取消，最终页退出有独立证据。
- 依赖：T3–T5。已发布为 [#22](https://github.com/DeyunMa/lorwright/issues/22)，关联 #15、#16。

### T7：有界多冒险编排与最终验收

- 范围：在单次冒险外组合选择、运行、结算及下一次；支持明确目标/次数、逐次结果、停止条件与每次重建英雄状态；每周选择复用既有低星优先、同星随机。
- 验收：离线组合覆盖两次完成、第二次失败、用户取消、无可选副本、最终页未退出及预算耗尽；前一次未完成结算不启动下一次。之后分别实机验收 Jinx、Elise 单冒险，再验收连续冒险。
- 依赖：T6；实际连续运行须在单冒险达到验收门槛后进行。已发布为 [#23](https://github.com/DeyunMa/lorwright/issues/23)，复用 [#16](https://github.com/DeyunMa/lorwright/issues/16) 的入口能力，保留原月本/周本目标。

弃牌完整闭环、缺失的英雄视觉素材、真实自动登录和冷启动继续独立跟踪；它们分别消费动作、英雄能力或前置自检契约，不并入一次无边界重写。顺序上先完成共享契约和两个真实消费者，再扩大迁移；无需新增通用插件框架、GUI 或网络服务。


## 现有 issue 的状态偏差

以下保留审计时发现的状态偏差及更新方向。七张既有 issue 均已按此更新标题和正文，#10、#15 同时作为总 issue 的正式子任务；未关闭任何尚未满足验收的票。发布后重新读取核验了全部 14 张 issue 的标题、正文和八项正式子任务关系。

| Issue | 已过期的描述或范围 | 整理方向 |
|---|---|---|
| [#5 单场战斗](https://github.com/DeyunMa/lorwright/issues/5) | 仍称没有成功的 `play_card`、手势为唯一硬阻塞 | 更新已完成实机动作及完整单场记录；保留连续两局无人介入验收，跟踪当前视觉/后验稳定性 |
| [#6 异常恢复](https://github.com/DeyunMa/lorwright/issues/6) | 仍将重放上次动作作为 L1 恢复 | 更新为有证据的重新观察/路由、有限恢复和明确停止；输入结果未知时保持禁止盲目重发 |
| [#10 场面识别](https://github.com/DeyunMa/lorwright/issues/10) | 仍称双方单位恒空，并将单位槽位当作固定位置 | 更新单位及数值已有实现、光效/遮挡缺口、相对卡片几何与未知状态；关键词覆盖另行核实 |
| [#12 前置自检](https://github.com/DeyunMa/lorwright/issues/12) | 早期网络/冻结诊断方案未与当前启动及停止契约对齐 | 保留前置检查目标，区分只读诊断、可执行恢复与真实登录/冷启动验收 |
| [#13 采集清单](https://github.com/DeyunMa/lorwright/issues/13) | 仍指向旧交接清单、旧 960 地图基准及缺少治疗师素材 | 改为按能力/失败模式组织的实拍证据矩阵，注明已有样本和缺失场景 |
| [#15 节点与奖励](https://github.com/DeyunMa/lorwright/issues/15) | 仍称节点只有“旅行→第一选项→离开”兜底 | 更新已覆盖节点与奖励；剩余工作围绕统一交互契约和未覆盖能力 |
| [#16 顶层入口](https://github.com/DeyunMa/lorwright/issues/16) | 仍以旧素材和单命令主页导航为主要范围 | 保留月/周入口目标，区分单场入口与多冒险编排，后者须依赖明确的单场结果 |

已关闭的 [#14 地图 1080p 迁移](https://github.com/DeyunMa/lorwright/issues/14)、[#9 出牌手势](https://github.com/DeyunMa/lorwright/issues/9)、[#11 攻击与格挡手势](https://github.com/DeyunMa/lorwright/issues/11) 作为已有能力参考；后续稳定性问题依据新失败证据跟踪。
