# MAA 机制笔记

MAA（MaaAssistantArknights）和 MaaFramework 是成熟的手游自动化项目，对我们有借鉴意义。
这个目录**只记录机制与取舍，不搬运代码**（MaaFramework 是 LGPL-3.0，MAA 是 AGPL-3.0；
即使许可证允许，我们的场景也不同——它是回合制点按，我们是「按住再拖」的出牌 + 战斗决策）。

一份文档 = 一个机制点。不追求覆盖它全部功能，只挑对我们有意义的。

| 文档 | 一句话结论 |
|---|---|
| [01-input-primitives](01-input-primitives.md) | 输入后端只给 `down/move/up` 原语 + 能力声明，手势由上层组合；做不到就显式拒绝，不假装能做到 |
| [02-pipeline-dsl](02-pipeline-dsl.md) | 用「识别 → 动作 → 后继」节点图描述流程；`next` 顺序试、`on_error` 只有一跳，没有变量和循环 |
| [03-recognition](03-recognition.md) | 识别是一等公民：`roi` / `box` / `target` 三分 + `order_by` + `index`，「第几个」变成参数 |
| [04-screencap](04-screencap.md) | 截图通道决定循环节奏；`screencap -p` 是最慢的一档，帧时间戳比换通道更能防「点落在旧画面上」 |
| [05-resource-packs](05-resource-packs.md) | 模板与流程是数据；覆盖靠「加载顺序」而不是复制，版本标记放在包级而不是每张图 |
| [06-debugging](06-debugging.md) | 失败时留下能复现的证据：失败必存图、识别框画在图上、决策理由落盘、历史截图能回放 |

## 已经采纳的

| 机制 | 落点 |
|---|---|
| 输入原语 + 能力声明 | `src/lorwright/device/touch.py`：`TouchSurface.can_hold`、`EvdevSurface.build_script()`、`AdbInputSurface`（`can_hold=False`） |
| 坐标上限从设备读、缩放集中一处 | `discover_touch_device()` 解析 `getevent -pl`；`TouchDevice.to_raw()` 是唯一缩放入口 |
| 能力不足时显式拒绝 | `AdbInputSurface` 表达不了停顿 → 由 `can_hold` 声明，上层不再假设 |

## 值得做、还没做的

| 机制 | 为什么值得 | 代价 |
|---|---|---|
| **短边归一化**（MaaFramework `image_target_short_side_ = 720`） | 治我们「换分辨率就要全部重标定」的病：模板按归一化尺寸采一次，坐标反算回设备像素 | 中：`Layout` 全部要改成相对坐标，`digits` 字号要重验 |
| **帧时间戳 + 动作前 `max_age_ms` 校验** | 比换截图通道更能防「状态不明还点」：超龄就重截或退 `NO_OP` | 小 |
| **`screencap()` 打耗时日志** | 零成本，先量再优化 | 极小 |
| **`order_by` + `index`** | 把「手牌第几张」变成参数，而不是硬编码排序 | 小 |
| **debug 落盘 + 回放**（每帧图 + 识别框 + 动作 + 耗时，`ReplayDevice` 用历史截图跑真实循环） | 现在调一次手势要几分钟手工截图；有了回放就能 `pytest` 式回归 | 小 |

## 不采纳的

| 机制 | 原因 |
|---|---|
| 常驻触摸守护进程（minitouch / maatouch） | 我们设备固定、手势种类少；一次 `adb shell sh` 发完整手势更简单，少一个进程要管 |
| Pipeline JSON DSL（C++ 那套 Controller/Tasker/Agent） | 我们的核心是「一次截图 → 结构化状态 → 决策」，不是「找到 A 就点 A」。真需要时写 ~50 行节点表执行器即可 |
| 逐模板版本号 | MAA 自己也没做（只有包级 `version.json`），成本高于收益 |
| minicap / JPEG 通道 | 有损压缩会伤模板匹配，MAA 官方也不推荐 |

## 加新文档的规矩

1. 一个机制点一份文档，≤150 行，中文。
2. 必须写清来源（仓库 + 文件路径 + 许可证）和「对我们的意义」「不适用 / 不要照搬的地方」。
3. 结论要么有源码/文档支撑，要么显式标「未验证」。不写没有出处的推测。
4. 只提炼机制，不复制代码片段（可以写字段名、命令格式、协议格式）。
