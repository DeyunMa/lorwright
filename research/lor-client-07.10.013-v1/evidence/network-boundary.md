# 协议与人机行动来源边界（Round 2）

已恢复一条真实网络消息进入客户端合法动作列表的静态链；尚未恢复 AI solver，也没有证明“最佳人机动作来自远端”。这两项结论必须分开。

## 已证实的接收链

`WebSocket.OnMessage → WebSocketBaseChannel.OnMessage(raw bytes → CurrentSerializer.DecodePacket interface) → MessageReceived → ReadQueue.Enqueue → WebSocketClientChannel.TryRead → NetworkClient.DrainChannel → Dispatch → CommandMap[type].DynamicInvoke → BaconInputStrategy.OnValidActionsMessage → ApplyValidActions → CardState.ValidActions.AddRange`。

这不是根据网络类名猜测。SetupSocket（22825）实际调用 WebSocket.add_OnMessage；OnMessage（23141）实际调用 MessageEventArgs.get_RawData，把返回字节交给 CurrentSerializer+0x18 的接口分发，之后把解码结果交给 MessageReceived+0x20。SetupSocket 同时注册闭包22840，其把传入对象 Enqueue 到 WebSocketClientChannel.ReadQueue+0x50。TryRead（22830）从同一 ReadQueue 取出对象；DrainChannel 在 VA 0x20642a0 调用 TryRead、在 0x2064334 调用 Dispatch。该链有接口/委托动态分发，但目标与实参由注册和字段读写闭合，而不是直接 B/BL 名字联想。

ValidActions 注册的关键点：40293 在 0x27d4400 加载 method-def usage，准确解为40371 `OnValidActionsMessage`；在 0x27d481c 将此 MethodInfo 作为委托构造参数；在 0x27d4838 加载 `SubscribeMessage<Shared.Messages.ValidActionsMessage>`，0x27d4858 调用共享 generic body 0x2b8b8dc。此 body 读写 NetworkClient.CommandMap+0x128；Dispatch 在0x2063ea8读取同一表、GetType+TryGetValue 后于0x2063f28 DynamicInvoke。没有声称此注册意味着每次游戏都会收到该消息，也没有抓包或请求线上服务。

## 动作列表如何落地

40371 保存 LastValidActions+0x138，然后尾调40374。40374先遍历游戏区域里的 CardState 并调用 ClearAllActions（25957）；再读消息 ActionMap+0x10，逐个 CardActionInfo：NetID+0x10→GetTableCard→TableCard.State+0x78；0x27e3558读取 CardState.ValidActions+0xb0，0x27e3560读取 DTO.ValidActions+0x18，0x27e3568执行 AddRange。InvalidActions+0xb8 与 DTO.InvalidActions+0x20 同理。

AddRange不是猜名：MethodInfo槽0x43bd128→RELA addend→usage→encoded0xc002ba0b→MethodSpec89349，定义61439 `System.Collections.Generic.List<T>.AddRange`，class_inst188的参数精确为 Shared.Game.BaseGameAction（类型3914）。全部原始表偏移在 slices/40374.json 的 method_references 和 collection-call-reference.json。

另有 EventValidActions+0x68 经40372/40373进入同一 ApplyValidActions，且40373会先与已持有列表求交集。故存在事件入口与本地调度，并不能把每个调用都当作新网络消息。此阶段证明“至少一条网络输入链存在”，不证明网络是唯一来源。

## NextAIAction 与 EventProcessor 的边界

BaseGameAction.get_NextAIAction（24714，0x238f218）读取+0xf8；set_NextAIAction（24715）在0x238f290写入该字段。Prev在+0x128，setter写点0x238f324。扫描本 ELF 全可执行节的直接 B/BL，对两个setter均无直接调用；这不能排除反射、虚调用、内联字段写入和未映射函数。原始字段类型flags分别0x6与0x86，不能代替自定义 Bacon 网络成员筛选实证。

ReadObject（22909）确实按注册成员循环读取，0x233ae3c调用 SetMemberValue（23012），后者会走 FieldInfo.SetValue / PropertyInfo.SetValue；因此“直接调用者为0”尤其不能当未使用证据。尚未证明 Next 字段被该协议注册，也未找出具有 BaseGameAction 类型约束的实际 solver 写入者。AI动作来自本地还是远端，保持未知。

EventProcessor.BaconUpdate（47150）检查暂停后PumpContainers；容器消息入队、分发到达委托、并Apply到Complete/Live状态；UpdatePrevisGameState会调ResyncGameStateForAiAndPrevis。此范围是状态/事件处理证据，没有恢复候选生成→评分→选择。客户端 SendGameActionRequest（10378）接收已有动作，经重复/状态检查调用SendInternal并更新SentFlag；成功/失败消息转事件与pending-action处理。它们不能证明AI决策位置。

## 可恢复与验证

本目录独立持有 64 个 metadata 方法切片、一个caller-observed共享generic范围、144 条所选目标直接B/BL引用、字段原始offset、usage/MethodSpec与输入SHA。原库SHA256 `0bf9a4f7b73effaeeb6a5cdee5de45038014991697ed0687bf8ad99ebbed1fa8`。每个切片JSON记录VA、原ELF文件offset、SHA256和metadata offset；ledger.jsonl将结论关联到这些证据。

validation.json已通过：8165 条指令逐字节回查、431 个字段offset、341 条 MethodInfo 引用、7 个 REA/Ghidra 输出回执；metadata-index只读扫描前后SHA一致。REA 6.7.0 / Ghidra12.1.4仅在独占临时raw-slice项目运行，项目随CLI关闭，无共享MCP target。反编译输出含 bad-data/PIC/unreachable 警告，所有关键结论以保留的原始指令和精确元数据链为准。函数尾界以“下一个不同metadata entry”裁切，不宣称控制流完整。

恢复命令见 summary.json 的 resume_commands。第一条输入/输出SHA相同则验证并跳过，输入或脚本变化会重新生成；第二条逐切片保留SHA checkpoint；第三条独立重验并出报告。需现有 Python capstone、UnityPy venv中的纯Python pyelftools、REA CLI 与既有JDK/Ghidra；无需新增安装。脚本只读原始资产；只写本目录；没有运行游戏、连接设备、访问游戏内存或修改主项目。

## 下一步

按summary.json限定的三个未解项继续即可。当前已足够形成可靠停点：合法动作消息来源已闭合；人机最终选步的来源仍未闭合。
