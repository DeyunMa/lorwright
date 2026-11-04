# Debugging：失败时留下能复现的证据

> 来源：`MaaXYZ/MaaFramework`（**LGPL-3.0**）`include/MaaFramework/MaaDef.h`、
> `source/MaaFramework/{Vision/VisionBase,Task/PipelineTask,Task/Component/Recognizer}.cpp`、
> `source/MaaRecordControlUnit/RecordController.cpp`、`source/MaaReplayControlUnit/ReplayRecording/`、
> `docs/en_us/{5.1-Troubleshooting,2.2-IntegratedInterfaceOverview,2.3-CallbackProtocol}.md`；
> `MaaXYZ/MaaUtils`（**LGPL-3.0**）`include/MaaUtils/{Logger.h,LoggerUtils.h,Time.hpp}`、`source/Logger/Logger.cpp`；
> 社区工具 `MaaXYZ/MaaDebugger`（**MIT**）、`kqcoxn/MaaPipelineEditor`（**MIT**）。只提炼机制，不复制代码。

## 它解决什么问题

视觉自动化失败时的现场只有一个"屏幕没反应"。MAA 的答案不是"加打印"，而是把证据做成
**常开的三条管道**：策略化落盘（什么时候存、存哪、叫什么名）、带字段的日志（谁、多久、什么参数）、
以及**可回放的控制器**（把一次失败变成一串能重跑的截图）。判据很硬——issue 模板要求
`maafw.log` + `debug/vision/*.jpg` + 模板图 + 最小复现；少一样就不看。

## 机制

### 1. 三档开关，默认只留"失败证据"

`MaaGlobalSetOption`（`MaaDef.h:79-130`）里与调试相关的是七个选项：

| 选项 | 默认 | 实际作用（源码行为） |
|---|---|---|
| `LogDir` | 无 | 所有产物的根。Toolkit 封装成 `<cwd>/debug/`（`GlobalOptionConfig.h:22`） |
| `SaveDraw` | false | **唯一写盘开关**。开启后每次识别把可视化图写到 `debug/vision/` |
| `SaveOnError` | **true** | 动作失败/无效 node/错误处理循环时，把当前帧存 `debug/on_error/` |
| `DebugMode` | false | **不写盘**：让识别结果在内存里附带原图与 draw，且所有 task 当 focus、全量回调 |
| `StdoutLevel` | Error | 控制台级别；文件始终全量（`MAA_DEBUG` 编译期才默认 All） |
| `DrawQuality` | 85 | draw 图 JPEG 质量 |
| `RecoImageCacheLimit` | 4096 | 内存里保留多少条识别产物（`RuntimeCache::evict_reco_image_cache_if_needed`） |

关键分工（`VisionBase.cpp:75`、`Recognizer.cpp:106`）：

- `debug_draw_ = save_draw || debug_mode` —— **画框**只发生在内存里，每帧都画；
- `save_draws()` 开头 `if (!option.save_draw()) return;` —— **落盘**只认 `SaveDraw`；
- `debug_mode()` 时额外把整帧 PNG 塞进 `RecoResult.raw`，供 `MaaTaskerGetRecognitionDetail` 取。

所以"开 debug 会保存每帧截图"是错的：截图只在**识别发生的那一帧**落盘，且**只存叠加了框的整帧 jpg**
（不是裁剪图）——模板匹配把模板小图和得分画在右侧，OCR 画识别框。原图要靠 debug 模式从内存取。
另外：`5.1-Troubleshooting.md` 写的命名是 `{node_name}_{reco_id}_{timestamp}.jpg`，与源码不一致，
以源码为准（时间戳在前）。一次识别可能落多张 draw（原图 + 局部裁剪各一张）。

### 2. 落盘目录与命名

| 目录 | 内容 | 命名（源码） |
|---|---|---|
| `debug/maafw.log` | 主日志 | 固定名，>16 MB 轮转成 `maafw.bak.{ts}.log` |
| `debug/vision/` | 识别可视化 | `{YYYY.MM.DD-HH.MM.SS.mmm}_{node_name}.jpg`（`VisionBase.cpp:91`） |
| `debug/on_error/` | 失败帧 | `{同上时间戳}_{node_name}.png`（`PipelineTask.cpp:499`） |
| `debug/screencap/` | 显式截图动作 | `{ts}_{node_name}.{format}`（`Actuator.cpp:585`） |

### 3. 日志：自由文本 + 内联键值对，耗时靠作用域

行格式（`LoggerUtils.h:140`）：`[时间][LVL][Px<pid>][Tx<tid>][文件名][L<行>][函数名] 消息`。
级别 8 档 `Off/Fatal/Error/Warn/Info/Debug/Trace/All`，缩写 `FTL/ERR/WRN/INF/DBG/TRC`。
**不是结构化日志**——字段靠 `VAR(x)` 展开成 `[x=值]` 内联在消息里，JSON 值会被 `dumps` 后拼进去；
所以 `LogInfo << "reco" << VAR(result)` 等于把整条识别结果 JSON 写进日志（`Recognizer.cpp:112`）。
耗时没有独立字段，靠 `LogFunc` 宏（`Logger.h:167`）：进入打 debug，离开打 trace 并带
`duration_since(start)`——开 trace 才有整条时间线。启动写版本/构建时间/系统/工作目录；
超过 7 天的 `.log/.jpg/.png` 后台自动删（`Logger.cpp:122`）。

### 4. 失败时默认保留什么

`save_on_error` 默认 **true**，所以零配置下失败至少留下：`debug/maafw.log`（含每步识别结果）
+ `debug/on_error/{ts}_{node}.png`。崩溃另存系统 CrashDump（`.dmp`）。识别类问题必须补
`debug/vision/` 的 draw 图 + 模板原图 + 原始截图——文档把前两项列为"必需"，第三项"建议"。

运行时侧还有按 id 回查的通道：`Node.Recognition.*` / `Node.NextList.*` / `Controller.Action.*`
回调带 `task_id/reco_id/name`，凭 `reco_id` 可 `MaaTaskerGetRecognitionDetail`（box、detail_json、
raw、draws）、`MaaTaskerGetActionDetail`（**实际传给 controller 的参数 JSON**）、
`MaaTaskerGetWaitFreezesDetail`（`elapsed_ms` + 每帧 `reco_id`）。耗时只在 WaitFreezes 有，
`RecoResult` 结构里没有耗时字段。

### 5. 可视化调试器

| 工具 | 能做什么 | 做不到 |
|---|---|---|
| MaaDebugger（NiceGUI，`localhost:8011`） | 连接/截图、选入口节点跑任务、`Pipeline Override` 临时改参数；每次识别生成 `/reco/{reco_id}` 页：draw 图 + `detail_json` + 节点数据；全局 `Tasker.set_debug_mode(True)` | 无断点/单步；无热改源文件（只 override 一次运行）；README 标注正在重构 |
| MaaPipelineEditor（Web + LocalBridge） | 流程级调试：**完整运行 / 从选中节点运行 / 单节点运行 / 仅识别 / 仅动作 / 固定图识别**；画布上高亮执行路径与耗时；"节点线"逐条加载截图、动作详情；调试日志面板直读 `maafw.log`；Pipeline Override JSON；Recorder 把真人点击录成节点草稿 | 明确写了**不支持断点、暂停、单步**；改文件后要保存才生效（运行中用磁盘版本） |

"热改 pipeline"实际是 `Pipeline Override`（运行时覆盖参数/next），不是热重载源文件。

### 6. 回放/复现：官方是一等公民

`MaaRecordControllerCreate(inner, path)` 包住真实控制器，逐行写 JSONL：
`{type, success, timestamp(相对启动 ms), cost(ms), param}`，截图另存
`{stem}-Screenshot/screencap_{n}.png`。`MaaReplayControllerCreate(path)` 按序喂回：
`screencap` 返回历史图，其它动作按记录的 `cost` `sleep` 后返回记录的 `success`（不碰设备）。
顺序不对就报 `record type mismatch`；**任务提前结束直接 `std::abort()`**——把它当确定性回归测试用。
官方测试 `test/pipeline/module/{PipelineSmoking,BatchOcrRepro}.cpp` 就是这么跑的；MPE 的"固定图识别"是同一思路的轻量版。

## 对我们的意义（lorwright）

现状：调出牌手势靠手工 `screencap` → 拷 PNG → 本地看图，一次实验几分钟；`loop/engine.py:88` 只在
watchdog 判 `stuck` 时 `save_snapshot()` 存一张图；`util/events.py` 每 tick 一行 JSON
（ui/layer/action/clicks/stuck/ms）；`tools/analyze.py` 只做计数与均值。缺口很明确：**没有识别框、
没有决策理由、没有动作参数、没有正常 tick 的图**——"为什么这帧判成 BATTLE 而不是 MULLIGAN"
这类问题只能靠复现运气。

最小可用方案（照 MAA 的分工，不照它的实现）：

1. **两级开关**（写进 `config/settings.yaml` 的 `debug:` 段）：`save_frames: false`（正常 tick 不存图，
   环形只留最后 N 帧）+ `save_on_error: true`（stuck/UNKNOWN/动作异常必存）。对应 MAA 的
   `SaveDraw` / `SaveOnError` 默认值差异——失败证据常开、全量证据按需。
2. **一次 run 一个目录**：`logs/<date>/run_<HH-MM-SS>/`，内含 `frames/`、`debug.jsonl`、`run.log`。
   每 tick 一行 `debug.jsonl`：`tick, ms, ui, layer, action, clicks, boxes[{name,roi,score}], plan, frame`。
   命名沿用我们已有的 `{tag}_{时间戳}`，改成 `{tick:04d}_{phase}.png` 便于二分定位。
3. **框要画在图上**：`perceive/locate.py` 已算出匹配位置与分数，`StateParser.parse()` 顺路把 `boxes`
   收集进 debug 旁路对象（别污染 `models.py`），engine 存图时叠加。这是 `VisionBase::draw` 的最小
   等价物，也是"识别错了还是决策错了"的分界线。
4. **决策理由落盘**：`Router.decide()` 已返回 `layer`，再加一个 `reason: str` 就够定位"为什么这帧走了
   L1 而不是 JEV"；动作参数用 `act/translate.py` 的 `ClickPlan` 原样记。

复现（我们有现成起点）：`tests/fixtures/screens/` + `test_perception.py` 已在用固定图跑感知。升级成
MAA 式回放即可：给 `device/base.py` 的 `Device` 协议加 `ReplayDevice`，按目录顺序吐帧、`click/swipe`
只记不执行，engine 加 `--replay <dir>` 就跑真实主循环而不碰 ADB/游戏。配套 `manifest.jsonl`
（每帧 + 期望 state/action），就把"手势调试"从手工截图变成 `pytest --replay` 式回归。

## 不适用 / 不要照搬的地方

- **别照抄 `DebugMode` 的"所有 task 当 focus"**：那是给 MAA 的 UI 客户端做树状展示用的。我们
  `UIState.UNKNOWN` 时兜底是 `NO_OP`（AGENTS.md 硬约束），回调越多越容易诱导"看到就点"。
- **别把证据放内存**：MAA 靠 `RecoImageCacheLimit=4096` 的进程内缓存 + `reco_id` 回查。我们进程要
  跑一整晚，图片必须落盘 + 环形淘汰；`reco_id` 这种"运行期句柄"也不适合当复盘入口，用 tick 号。
- **别照抄 `std::abort()`**：MAA 回放是回归测试，顺序不符即失败。我们的回放要用来探索，
  默认宽松（记录 diff、继续跑），只在 `--strict` 下断言。
- **别用 JPEG 85 存我们的帧**：MAA 存 jpg 是给人看框；我们量坐标/取色需要无损 PNG。
- **别引入 GUI**：MaaDebugger（NiceGUI）和 MPE（React+LocalBridge）都是重前端。我们的等价物是
  `lorwright run --replay DIR --dump` + `tools/analyze.py` 读 `debug.jsonl`，符合"先 CLI + 日志"。

## 参考位置

- 选项定义与语义：`MaaFramework/include/MaaFramework/MaaDef.h:55-130`；
  `docs/en_us/2.2-IntegratedInterfaceOverview.md:24-45`
- draw 生成/落盘分支：`source/MaaFramework/Vision/VisionBase.cpp:50-100`
- 失败存图：`source/MaaFramework/Task/PipelineTask.cpp:64-90, 480-505`
- 识别结果结构与 raw：`source/MaaFramework/Task/Component/Recognizer.cpp:106-118`、
  `source/include/Common/TaskResultTypes.h:15-27`
- 日志格式与轮转：`MaaUtils/include/MaaUtils/LoggerUtils.h:120-155`、
  `MaaUtils/source/Logger/Logger.cpp:96-200`；文件名与 `LogFunc` 常量 `Logger.h:11-12, 167`
- 配置默认值：`source/MaaToolkit/Config/GlobalOptionConfig.{h,cpp}`（`config/maa_option.json`）
- 回调字段：`docs/en_us/2.3-CallbackProtocol.md:130-320`
- 录制/回放：`source/MaaRecordControlUnit/RecordController.cpp`、
  `source/MaaReplayControlUnit/ReplayRecording/{ReplayController,RecordParser}.cpp`、
  `test/pipeline/module/{PipelineSmoking,BatchOcrRepro}.cpp`
- 排查清单（issue 要求什么证据）：`docs/en_us/5.1-Troubleshooting.md`
- 社区工具：`MaaXYZ/MaaDebugger`（`src/MaaDebugger/maafw/__init__.py:73`、
  `webpage/reco_page/__init__.py`）、`kqcoxn/MaaPipelineEditor`
  （`DocumentStation/docs/01.指南/20.本地服务/{30.MPE Recorder,40.流程级调试}.md`）
