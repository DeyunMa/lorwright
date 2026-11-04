# Input：后端只给原语，手势由上层组合

> 来源：`MaaXYZ/MaaFramework` — `source/MaaAdbControlUnit/Input/`
> （`AdbShellInput`、`MinitouchInput`、`MaatouchInput`、`MtouchHelper`），
> 许可证 LGPL-3.0。**只提炼机制，不复制代码。**

## 它解决什么问题

输入设备的能力不一样：有的后端能一步做完「点一下」，有的只能「按下 / 移动 / 抬起」。
如果框架对外只暴露 `click(x, y)` 和 `swipe(x1, y1, x2, y2, duration)`，
那么**表达不了「按下、停一会儿、再移动」**——而这恰恰是很多游戏要求的拖拽手势。

MAA 的做法是把「手势」和「输入通道」拆开：

- 输入通道（Input unit）只提供**原语**和**能力声明**；
- 上层（ControllerAgent）按能力声明决定怎么组合手势。

## 机制

### 1. 能力标志代替假设

后端实现 `get_features()`，返回一个能力位集合。关键的一位是
`MaaControllerFeature_UseMouseDownAndUpInsteadOfClick`，语义是：

> 这个后端做不了「原子点击」，上层请改用 `touch_down` / `touch_up` 自己组合。

`MaatouchInput::get_features()` 返回它；`MinitouchInput` 同理。
于是 `MtouchHelper::click()` / `swipe()` 直接返回失败并打印：

> `deprecated: get_features() returns MaaControllerFeature_UseMouseDownAndUpInsteadOfClick,
> use touch_down/touch_move/touch_up instead`

**这是设计上最值得学的一点**：能力不足时不是「尽力而为地退化」，而是
**显式拒绝**，把责任交回上层。退化会悄悄发出一个被游戏吞掉的手势，
表现为「点了没反应」，极难排查。

### 2. 原语与协议

`MtouchHelper` 对下层的写法（格式串见 `MtouchHelper.h`）：

| 原语 | 报文 |
|---|---|
| `touch_down` | `d {contact} {x} {y} {pressure}` + `c` |
| `touch_move` | `m {contact} {x} {y} {pressure}` + `c` |
| `touch_up` | `u {contact}` + `c` |
| `key_down` / `key_up` | `k {key} d` / `k {key} u` + `c` |
| `input_text` | `t {text}` + `c` |

`c` 是 commit：命令先攒着，commit 才生效。所以「停顿」天然可以表达——
`d` → 等 → `m`… → `u`。

### 3. 坐标缩放集中在一处，上限从设备读

启动时读一屏设备信息（banner：最多触点数、`max_x`、`max_y`、压力上限），
再结合显示分辨率算出 `xscale_` / `yscale_`，之后所有坐标都过
`screen_to_touch()`。`screen_to_touch_impl` 还按 0/90/180/270 四个方向做了
旋转映射。

要点不是这段数学，而是**只有一个地方做缩放**，且上限来自设备而不是写死。

### 4. 二进制与生命周期

`MaatouchInput::init()`：`invoke_app_->init()` → `push(agent/universal/maatouch)` →
`chmod()` → `invoke_and_read_info()` 读 banner。析构时 `remove_binary()` 清场。
即「部署 → 授权 → 读能力 → 用 → 清理」这套生命周期是显式的。

## 对我们的意义（lorwright）

我们的病根正是这个：`adb shell input swipe` 是**原子手势**，从第 0 ms 就开始
插值移动，表达不了「按住 → 停顿 → 拖」。实测下来它只会被 LoR 判成长按预览
（详见 `docs/handoff.md` §4.6）。

因此按 MAA 的结构改造了 `src/lorwright/device/touch.py`：

| 概念 | 我们的实现 |
|---|---|
| 能力声明 | `TouchSurface.can_hold` |
| 原语 | `EvdevSurface._seq_down/_seq_move/_seq_up`（协议 B 事件序列） |
| 手势组合 | `EvdevSurface.build_script(hold_ms, drag_ms, steps)` |
| 退化后端 | `AdbInputSurface`（`can_hold = False`，只有 `input tap/swipe`） |
| 设备发现 | `discover_touch_device()` 解析 `getevent -pl`，取 `ABS_MT_POSITION_X/Y` 的 `max` |
| 坐标缩放 | `TouchDevice.to_raw()`，唯一入口 |

一个刻意的差异：MAA 用一个常驻二进制 + socket（`d`/`m`/`u`/`c` 报文），
我们**不引入二进制**，而是把整个手势拼成一段设备端 shell 脚本，一次
`adb shell sh` 执行完。原因：

- 我们只有一个固定目标（BlueStacks Pie64），不需要跨 ABI 分发；
- 每次 `adb shell` 都是新进程，**进程退出手势就断**，所以必须一次性发完，
  这反而让「一次调用 = 一个完整手势」的语义更简单；
- 少一个后台进程要管（存活、重连、残留）。

## 不适用 / 不要照搬的地方

- **不要照搬二进制 + 抽象 socket**。我们的脚本方案在「手势种类少、设备固定」时更简单；
  等需要多指同时操作（例如同时拖两个单位）时再考虑常驻进程。
- **不要照搬压力值**。Pie64 的 `BlueStacks Virtual Touch` 没有
  `ABS_MT_PRESSURE` / `ABS_MT_TOUCH_MAJOR`（`getevent -pl` 可验证），
  发了也没用；协议里这几个字段是「设备支持才发」。
- **不要照搬四方向旋转映射**。我们的截图尺寸即逻辑尺寸（`wm size 1920x1080`），
  没有旋转歧义；等真出现旋转再补。

## 参考位置

- `source/MaaAdbControlUnit/Input/MtouchHelper.h`：`kDownFormat` / `kMoveFormat` /
  `kUpFormat`、`screen_to_touch_impl`、`xscale_`/`yscale_`/`press_`
- `source/MaaAdbControlUnit/Input/MtouchHelper.cpp`：`read_info()` 解析 banner、
  `touch_down/move/up` 写入、`click()`/`swipe()` 的 deprecated 拒绝
- `source/MaaAdbControlUnit/Input/MaatouchInput.cpp`：`get_features()`、
  `init()` 的 push/chmod/banner 流程、`kTextFormat`
- `source/MaaAdbControlUnit/Input/MinitouchInput.cpp`、`AdbShellInput.cpp`：退化后端
- 对照：`src/lorwright/device/touch.py`（我们的实现）
