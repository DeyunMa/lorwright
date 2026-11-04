# Round 2 / action-path

**已确认这是输入动作映射与拖拽吸附路径；未发现完整人机决策算法。** 本轮不再停留于名字：已在完整 ELF 中定点反编译、核对全部 543 条 ARM64 指令，解出列表来源字段、过滤条件、具体 action 类型和几何选择标准。阶段保留 `partial`，其中这三个函数的有界分析为 verified。

## 三个函数的实际结果

| 函数 | metadata id | preferred VA | 文件 offset | 有界 bytes / 指令 |
|---|---:|---|---:|---:|
| BaseGameState.GetUntargettedAction | 23488 | `0x235f130` | 37073200 | 468 / 117 |
| BaconInputStrategy.GetAction | 40310 | `0x27da0bc` | 41771196 | 1124 / 281 |
| BaconInputStrategy.NearestBlockerAction | 40311 | `0x27da520` | 41772320 | 580 / 145 |

VA 是原 ELF 的 preferred coordinate。专属 Ghidra 项目加载基址为 `0x100000`，故 Ghidra 画面/assembly 地址要减该基址才等于上表；每条指令同时保留两套地址与真实文件 offset，避免混用。

原库 SHA256：`0bf9a4f7b73effaeeb6a5cdee5de45038014991697ed0687bf8ad99ebbed1fa8`。切片在 `raw-slices/`，完整机器指令、引用与伪代码在 `methods-23488-40310.decompiled.json`、`methods-40311.decompiled.json`。没有运行目标或读写游戏内存。

## GetUntargettedAction：筛选既有列表中的第一个匹配项

传入参数的 metadata 名为 `cs`。机器码先读取 `cs + 0xb0`，独立 IL2CPP field-offset table 明确对应 `CardState.ValidActions`。正常路径只迭代这张现成列表：

```csharp
// 分析者对正常路径的语义重建，非恢复的原始源码；不表示异常路径等价。
foreach (var action in cs.ValidActions) {
    if (action.TargetID != action.CardID && action.TargetID != null)
        continue;
    if (action is ActionActivateAbility)
        continue;
    return action;
}
return null;
```

这里的 `!=` 是该程序 `BaseNetID<T>.op_Inequality` 的语义调用，不是把 native 指针直接比较。`CardID`/`TargetID` 字段偏移分别为 `0x48`/`0x50`，类型均为 `Shared.Network.CardNetID`。关键分支源指令在 preferred `0x235f200`–`0x235f250`（Ghidra `0x245f200`–`0x245f250`）：两次比较后回到列表循环或进入类型检查；匹配则跳向返回块。

比较操作符与排除类型不是凭猜名对应：

- 全 ELF global `0x43911b0` 经 `R_AARCH64_RELATIVE` 指到 usage cell；原字 `0xc0003c41`，v31 解码为 MethodSpec index 7712，表项精确对应 method id 22784：`Shared.Network.BaseNetID`1.op_Inequality`。
- 类型 global `0x43b6508` 的 usage 字为 `0x20006e63`，解码为 Il2CppType index 14129，原生类型表/metadata 精确对应 `Shared.Game.ActionActivateAbility`。
- 迭代器 hidden method-info 同样解到 `List<T>.GetEnumerator`、`Enumerator.MoveNext`、`Dispose`。

每个 global 的源 offset、relocation 后地址、usage cell 源 offset、编码值、MethodSpec 源 offset 与方法/类型 identity 都在 `action-field-offsets.json`。算法调用路径没有构建 action、没有全量动作/目标组合生成，也没有 score、排序或 best-action 循环。它的“遍历”只是在已经给出的列表中找第一个可用输入动作。

## GetAction：把选中的 TableCard 与手势状态映射成动作

本函数以 `TableCard` 为输入，先 `get_NetID`，从 `BaconInputStrategy.LiveGameStateProxy +0xc8` → proxy 的 `GameState +0x10` 取状态，再通过虚调用读取该卡。虚调用 offset `0x528` 对应 vtable slot 63，metadata 精确方法是 `BaseGameState.GetCard`（id 23461）；该 slot 的 metadata 源 offset 为 `5205368`。此次没有把间接调用当作已恢复的游戏规则引擎。

正常输入路径按这些分支选择：

1. 从该卡 `ValidActions` 中取第一个 `BaseCastGameAction`；没有则调用上述 `GetUntargettedAction`。
2. 当手势已跨阈值，或该卡已经在场时，如果候选为空或是 `ActionRemoveFromStack`，尝试 `NearestBlockerAction`，有结果则使用它。
3. 无候选时还包含唯一 valid 项、首个 invalid 项的 UI 回退；首个 invalid 若是 `ActionDeclareBlocker` 会被排除。唯一 valid 项的使用还受阈值分支约束，不能简化成无条件选唯一项。
4. `InputState.ThresholdCrossed == false` 时，有额外输出门槛：`ActionRemoveFromStack` 可保留；其它动作若卡在 Hand(8)、Spell(10)、BackRow(11)、Summon(13)，会返回 null。机器码位掩码为 `0x2d`（以 RegionType 8 为起点）。

`BaseInputStrategy.<Input>k__BackingField` 与 `InputState.<ThresholdCrossed>k__BackingField` 都是 `+0x38`，已由各自的 field-offset table 单独确认，不是把相同偏移误当同一字段。四个关键类型 global 完整解码为 `BaseCastGameAction`、`ActionRemoveFromStack`、`ActionDeclareBlocker`、`ActionActivateAbility`。

本函数能消费 InvalidActions，恰好说明其职责包括错误反馈/手势解释；返回了一个动作并不等于本地已经完成全部规则验证。它不评价蜘蛛收益、伤害、斩杀、交换价值等局面战术目标。

## NearestBlockerAction：屏幕位置吸附，不是战术最优阻挡

该函数按顺序扫 `cs.ValidActions` 和 `cs.InvalidActions` 两张列表，仅保留 `ActionDeclareBlocker`。随后：

- 取动作的 `TargetID`，通过 `TableManager.GetTableCard` 找屏幕上的目标卡。
- 对目标卡和正在拖动的卡调用 `GetCurrentPosition` → `ProjectWorldPositionToTable`。
- 计算两者投影坐标的横/纵绝对差。选择横向距离更小的项，同时要求横距 `< 目标宽度 / 1.5`、纵距 `< abs(BLOCK_THRESHOLD_LINE)`。
- 初始最近距离是 float max `0x7f7fffff`；每次满足三个条件才更新候选和最近横距；遍历耗尽返回该候选。

`BaconInputStrategy.BLOCK_THRESHOLD_LINE` field 是 `+0x220`。隐式转换 global 的 MethodSpec 精确解到 `PlatformDependentValue<T>.op_Implicit`。常数 1.5 在原始 ARM64 `fmov s12,0x3fc00000`，之后与 `GetSizeTarget` 的返回值相除；它是几何吸附宽度阈值，不能叫 AI 评分权重。

这些判断也逐指令核对：Ghidra `0x028da6e0`/`0x028da6f4` 的 `fabd`、`0x028da6f0` 的 `fdiv`、`0x028da700`–`0x028da724` 的三组比较及 `csel`/`fcsel` 更新。Ghidra 未正确恢复完整 Vector ABI，所以未以伪代码的 float 参数名宣称精确原始函数签名；坐标差/宽度/阈值这一语义来自真实调用目标、向量寄存器与比较链共同验证。

## 完整 ELF 分析方式及限制

专用项目 `ghidra-project/LoRActionPath` 是已有 `LoRFocusedBounded` 的独立副本；旧项目和冻结的 Phase05 没有改动。不用共享 MCP target；`analyzeHeadless -noanalysis` 加本目录 `ActionPathLoR.java`，只对指定 metadata 方法做指令与反编译。脚本核验 Ghidra 导入库 SHA，再核验 file offset→唯一 analysis address 与 base+preferred VA 一致。外部函数保留独立不透明边界，重要泛型通过静态 MethodSpec 另行解析。

初次探索中，Ghidra 对没有签名的异常恢复 helper 把最终 BL 当作会继续返回，伪代码因此越出方法混入后续函数。已明确处理为**分析边界修正**：位于所选方法最后一条的 BL，仅在专属分析数据库中设 `FlowOverride.CALL_RETURN`，防止跌入下一 metadata 方法；原始文件/指令 bytes 完全不变。每个实际应用点在结果中写 `analysis_boundary_override`。因此不能把异常分支最后 helper 的伪代码返回值当作已还原的真实行为。最终三函数伪代码已无 PIC construction 警告和越界 LAB 标签；机器码正常路径是主证据。

OnValidActionsMessage/ApplyValidActions 曾在发现生产者线索时完成了一次很小的原始探索，收到协议分支避重说明后立即停止。`methods-40371-40374.*` **不在本报告的三函数语义/验证范围内**；其中 tail-B 的伪代码有跨函数展开，不能拿它替代协议分支的独立证据。消息分发、ActionMap → ValidActions/InvalidActions 的生产/传输链由另一分支负责；本分支不重复扩展 UI 函数。

## 验证、恢复与下一条线索

`validation.json` 已通过：543 条指令逐条与原 ELF 4-byte bytes、VA 和文件 offset 比对，直接 B/BL 的 signed imm26 目标回算；三个切片全长覆盖；253 个 field-offset table 原始 int32；13 个 metadata usage cells 及 methodSpec identity；三份 Python AST。完整脚本/输入/反编译输出 SHA 也核对。验证说明这三个有界函数的证据可复查，不说明完整人机算法已经恢复。

恢复顺序：

```bash
rtk python3 /Users/mdy/Code/my-own/lorwright-artifacts/analysis/stages/05-native-ai/round2/action-path/run_action_path.py
rtk python3 /Users/mdy/Code/my-own/lorwright-artifacts/analysis/stages/05-native-ai/round2/action-path/run_action_path.py --ids 40311
rtk /Users/mdy/.local/share/rea/unitypy-venv/bin/python /Users/mdy/Code/my-own/lorwright-artifacts/analysis/stages/05-native-ai/round2/action-path/derive_action_fields.py
rtk python3 /Users/mdy/Code/my-own/lorwright-artifacts/analysis/stages/05-native-ai/round2/action-path/validate_action_path.py
```

原有完成 marker 只有在所有 source/script/output identity 相同才复用；失败时留下 partial/status/log。专属 Ghidra project 可保留续接。后续若发现 shared action 层与非 UI evaluator 的连接，可查非重叠候选 `BaseCastGameAction.PickValidAction`，id 24709、VA `0x238eca0`、文件 offset `37268640`；本轮未分析它，不称其为 AI。最小命令是 `run_action_path.py --ids 24709`，仅应在新证据证明继续这一 shared 层有价值时执行。

当前行动链已明确到“既有列表→输入筛选→几何落点”，仍缺完整合法候选生成、战斗规则执行、局面评分、搜索以及最终战术选择。不能靠继续复读 UI 吸附机制填补这些缺口。
