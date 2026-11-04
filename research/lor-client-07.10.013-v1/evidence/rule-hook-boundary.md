# 第二轮：规则钩子与实际虚函数绑定

**本包中两个目标合法性钩子直接返回true，选定的脚本/目标应用钩子直接返回；导出的客户端类型仍绑定这些基类实现。** 因此不能把这些共享接口当作完整规则引擎或AI模拟器。此结论只针对已核验的方法，不声称客户端没有其它规则校验。

## 原始实现与绑定

| 方法 | 地址 | 源文件offset | 元数据返回类型 | 精确机器码/行为 |
|---|---|---:|---|---|
| BaseGameState.IsValidTarget | `0x23614b0` | 37,082,288 | BOOLEAN | `mov w0,#1; ret` |
| BaseGameState.IsValidTargetForDiscardAsACost | `0x23614b8` | 37,082,296 | BOOLEAN | 同上 |
| BaseGameState.OnTargetRequired | `0x235abec` | 37,055,468 | VOID | `ret` |
| BaseGameState.UpdatePlayerGameStateView | `0x235a894` | 37,054,612 | VOID | `ret` |
| CardState.ProcessPendingScriptActions | `0x23c2848` | 37,480,520 | VOID | `ret` |
| CardState.ApplySelectedTargets | `0x23caebc` | 37,514,940 | VOID | `ret` |

数值offset以 `hooks.json` 内直接从索引取得的记录为准。每个证据片段仅4或8bytes，具有立即return的闭合控制流，不依赖“下一条metadata entry就是函数结束”的假设。不是把复杂函数截短后宣称无逻辑。

对第一条8-byte片段做REA/Ghidra独立核验：

```text
0x23614b0: mov w0, #0x1
0x23614b4: ret
```

REA Evidence：`ev_931e5cb9f0ae268c14a5d0a614e7b9aaedbff087fc8fef50cca502ef24e36bd7`，保存在 `IsValidTarget.rea.json`。反编译器推测返回类型为undefined8；本报告的BOOLEAN/VOID来自同一APK的method.returnType及原生Il2CppType.kind，不从伪代码猜C#签名。

## 继承范围

读取全部19,237个type definition的parentIndex，17,699个通过精确byval type index关联，884个通过ELF relocation和Il2CppGenericClass原生类型定义关联，654个明确无父类。本批没有未解析的parentIndex。完整逐类型来源保存在 `parents.jsonl`。

在本份导出元数据中，BaseGameState的后代链为：

```text
Shared.Game.BaseGameState
  → Client.Game.ClientGameState
    → Client.Deckbuilder.DeckbuilderGameState
```

CardState没有其它导出后代。选定4个类型共456个vtable槽项，455项解出method definition；BaseGameState的CreateNullCardData抽象槽105没有method用法编码，客户端在该槽提供其实现。36个槽项与方法声明slot不同，接口重复绑定原样保留，不将它们误判成损坏。

本报告六个目标的实际slot引用均已解出：IsValidTarget=91、IsValidTargetForDiscardAsACost=92；在ClientGameState与DeckbuilderGameState中仍指向同一基类method id23554/23555。OnTargetRequired与UpdatePlayerGameStateView也保留基类ret实现。CardState的两个脚本钩子在其vtable中直接绑定立即返回的方法。

160次槽位绑定符合脚本识别的平凡机器码模式；这是含继承重复项的槽位计数，不是160个独立规则，也没有把所有其它方法都归类为平凡实现。

## 对决策核心调查的含义

接口齐全、名字包含ValidTarget或Script，不代表它携带游戏完整的合法性和脚本计算。这与另两条线的实际结果需要合看：动作入口消费已有动作列表；网络消息会提供动作列表。仅移植本报告这几个函数，无法得到完整候选生成、模拟或AI评估。

仍未证明完整AI只在服务端。其它库内部、未解MonoBehaviour数据、运行时动态类型以及远端实现都在本次钩子证据的范围之外。本轮没有观察运行时dispatch，也没有修改或调用游戏内存。

## 验证与恢复

```sh
rtk /Users/mdy/.local/share/rea/unitypy-venv/bin/python stages/05-native-ai/round2/virtual-hooks/inspect_hooks.py
rtk /Users/mdy/.local/share/rea/unitypy-venv/bin/python stages/05-native-ai/round2/virtual-hooks/validate_hooks.py
```

执行目录是analysis根。第一条重建小型离线索引，运行只需数秒，原输入保持只读。第二条核对输入SHA、JSON Schema、19,237条父类来源、455个method vtable记录、6个完整短函数及REA汇编，并保存validation.json。原始片段已存在且内容不同会拒绝覆盖。

解析布局和v31 encoded method index算法来自先前保留的Il2CppDumper参考文件，引用文件SHA已锁定。`inspect_hooks.py`负责原生泛型父类解析；独立验证器逐条核对父类字段及其完整ledger，对泛型父类额外依赖重跑构建器的原生指针一致性检查，未将其误称为两个完全独立的泛型解析器。
