# LoR 原生规则调查

本轮已从本机 07.10.013 APK 解析出可定位的规则方法，并核验先遣和格挡的关键正常分支。尚未恢复完整官方 AI，也没有在运行中的游戏上执行这些方法。

## 输入与可复查索引

- `libil2cpp.so`：74,411,096 bytes，SHA-256 `0bf9a4f7b73effaeeb6a5cdee5de45038014991697ed0687bf8ad99ebbed1fa8`。
- 元数据：15,089,816 bytes，SHA-256 `2e08d966d5488a36e6cc452e30caa25b8494483dff6942d28fb47560016b1736`，版本 31。
- **权威索引为 `metadata-index-v3.sqlite`**。旧的无后缀、v2 SQLite 和早期查询 JSON 为探索产物，不应作为交付数据源；v3 修正了密文内零字节导致的字符串截断，并分别验证 fields / parameters 表。
- `index_il2cpp.py`：只读解析脚本。对照保留的 Il2CppDumper 原始格式声明，读取 77 个程序集、19,237 个类型、107,888 个方法、85,468 个字段、94,014 个参数。
- 112,615 个带 cache index 的名字使用 17 字节循环 XOR 编码。已按完整记录边界恢复；整个 pool 恰好消费到声明结尾。另有 51 个非 UTF-8 明文条目，保留原字节，不作为类/方法名解释。
- 100,081 个方法条目映射到 ELF 可执行地址；这不是 100,081 个独立实现，泛型共享、空方法和别名仍需区分。
- 方法地址映射来自代码生成模块、方法 token RID 与 ELF 的 `R_AARCH64_RELATIVE` 记录。原文件不变；地址为静态首选装载地址，不是运行时进程地址。

`inspect_native_rules.py` 另核对了唯一候选元数据注册表、实际字段偏移、原生 primitive 类型及压缩整数；`native-rule-constants.json` 含 5 组枚举、228 个值及其文件偏移。

## 已核验的规则

| 方法 | 原生 VA / 原文件偏移 | 结论与边界 |
|---|---|---|
| `Shared.Game.BaseGameState.AttackWouldBeScout` | `0x2363d48` / `0x235fd48` | 正常分支先拒绝本轮已用先遣，再遍历攻击区，遇到无 Scout 的单位返回 false；遍历完成后返回攻击区非空 |
| `Shared.Cards.CardState.StatePreventsBlock` | `0x23ccbb8` / `0x23c8bb8` | 非 Creature 返回 true；Creature 检查 Immobile、Reckless、Stunned |
| `Shared.Cards.CardState.GetFearsomeBlockingValue` | `0x23ccf6c` / `0x23c8f6c` | 两条指令，返回 3，伪代码可完整恢复 |
| `Shared.Cards.CardState.CanBeBlockedByCard`（3 个参数） | `0x23ccf7c` / `0x23c8f7c` | 汇编/调用点中有 Fearsome、Elusive、BlockElusive、Brash 等检查，以及结构化 ActionErrorFlag；尚未逐条验证完整错误路径 |

先遣分支的交叉证据：

1. 方法声明参数为 `playerID`，代码生成模块中的 RID 映射到 `0x2363d48`。
2. 原始汇编调用 `GetPlayerState`，读取返回对象 `+0xd0`，非零即返回 false。
3. 元数据注册表的字段偏移独立对应 `Shared.Game.BasePlayerState.ScoutHasBeenUsedThisRound = 0xd0`。
4. 汇编调用 `GetRegionState(9, 0)`；枚举 `RegionType.Attack = 9`。这里没有把 PlayerID 数值 0 解释成“我方”。
5. 对每个单位调用 `HasKeyword(0x7e)`；枚举 `KeywordFlags.Scout = 126`。无该关键词即 false。
6. 遍历结束调用 `RegionState.IsEmpty` 并取反。不能只判断“场上有先遣单位”就当作先遣攻击。

格挡分支的交叉证据：

- 读取 `CardTypeOverride`（`+0x48`），若为 Undefined，再从 Data（`+0x40`）读取基础类型。
- `CardType.Creature = 2`，`KeywordFlags.Immobile = 3`、`Reckless = 1`、`Stunned = 80` 与汇编立即数一致。
- 这些状态说明“拖不动”可能是规则禁止，需要感知层先识别，而不应不断重试输入。
- `ActionErrorFlag` 中可见 `AttackTokenFail = 5`、`NotEnoughMana = 26`、`ScaryBlockFail = 47`、`UnitIsStunned = 76` 等。视觉自动化目前并不能直接读取这些内部返回码；它们是设计诊断分类的参考。

## 反编译证据及限制

`FocusedLoR.java` 在原始 ELF 的副本上定向反汇编，按原文件偏移定位，输出六个目标的汇编和伪代码。目标函数边界以邻近 IL2CPP 方法入口约束，可能遗漏非连续共享尾块；完整共享函数、异常路径、外部库和类型签名没有全部恢复。

`focused-bounded-decompilation.json` 保留 Ghidra 地址、原始映射、指令和调用目标的元数据候选。其部分伪代码仍将未知异常调用误判为 PIC/不可达路径；**规则结论以边界内汇编、枚举和字段偏移交叉核验为准，不能直接把伪代码复制成实现。** 最早的 `focused-decompilation.json` 没有相邻方法边界约束，含无关延伸块，只保留作探索记录。

REA 对原文件中逐字节一致的方法切片也完成了 Ghidra 静态反编译；`rea-slices/provenance.json` 保留来源偏移、切片 SHA 和外部范围限制：

| 文件 | REA Evidence |
|---|---|
| `rea-slices/AttackWouldBeScout.rea.json` | `ev_06a7a9bbea7c196052b7cf2ec34b1afda9d5988bd6547c481b75f8394d5d45b0` |
| `rea-slices/StatePreventsBlock.rea.json` | `ev_7bfc82753846a639df7d1f913fbb683c0003a248ad15988f0d119aa13d3e5441` |
| `rea-slices/GetFearsomeBlockingValue.rea.json` | `ev_a5d7d7b26a75ff59a9f2fba49666c991e58e967997c53f9163751e2affa51f1e` |

切片外的代码与数据并未装入分析图像，Scout / StatePreventsBlock 伪代码有 Bad instruction / PIC 警告；只有 Fearsome 常量返回完全自包含。切片证据不表示整库分析已完成。

最初整库默认自动分析约 19 分钟后仍无成功响应，出现大量 GCC exception-table 反汇编诊断，已主动取消并释放本任务进程。`broad-analysis-status.json` 和对应错误 JSON 明确记录 cancelled；没有把它当成功 Evidence。

## AI 找到了多少

已定位声明/方法入口：

- `Shared.Game.ActionDeclareAIAttackers`、`ActionDeclareAIBlockers`、`EventAIBlockersDeclared`；
- `BaseEvent.SkipDuringAIEvaluation` 及几个事件覆写；
- `Client.UI.PrevisManager`，以及牌组选择配置 `AiDeckGroup` / `AiDeckSelectionStrategy` / `AiDifficulty`；
- `Shared.Cards.CardState.GetCostScore`、`GetSpellCostScore`。

后两者也有独立切片 REA 结果，费用评分路径出现 `1.5`、`3.0` 等折算常量。但类型调用和实际调用者尚未完整还原，不能把它当作“官方完整 AI 评分函数”移植。对应 Evidence 为 `ev_d89b24111b4be36c62c4941af8118089a922bca3db220a69d7261fca984a8cdc` 和 `ev_dc110059014d9be792c6a0b20321b319828b069fa05f5bf4a57653a12af5685f`。

对 Assembly-CSharp 类型/方法名中 AI、Ai、Score、AIEvaluation、Heuristic、Minimax、BestMove、BestAction、Simulate 等的有界检索，没有定位到一个已核验的完整动作选择/搜索器。`ai-types-v2.json` 与 `evaluation-methods.json` 保存候选；名字缺席不证明逻辑不存在，也不能证明它必定在服务器。

## 对项目的使用方式

将上述内容作为**离线规则依据、图标语义和测试用例来源**。现有截图 → GameState → 语义动作 → ADB 的运行路径可以继续保留；无需让机器人运行时加载原生库或执行逆向工具。

建议优先形成：先遣本轮使用标记与攻击集合条件、不能格挡的状态、威吓最低攻击力的离线用例。感知层没读到这些状态之前，不应把“知道官方规则”当成“程序已经能判断实际场面”。本轮没有修改项目代码、读取游戏内存或操作设备。
