# Screencap：截图通道决定循环节奏

> 来源：`MaaXYZ/MaaFramework`（**LGPL-3.0**）`source/MaaAdbControlUnit/Screencap/`、
> `source/MaaAdbControlUnit/Manager/`、`source/MaaFramework/Controller/ControllerAgent.cpp`、
> `docs/en_us/2.4-ControlMethods.md`、`include/MaaFramework/MaaDef.h`；
> 对照 `MaaAssistantArknights/MaaAssistantArknights`（**AGPL-3.0**）
> `src/MaaCore/Controller/AdbController.cpp`。只提炼机制，不复制代码。

## 它解决什么问题

`adb exec-out screencap -p` 单帧几十到几百毫秒，而挂机场景要 1–5 fps 持续跑一整晚。
瓶颈不在识别，在**把一帧图像从设备搬到 PC**：PNG 编码在设备端做、压缩后仍有数 MB、
每帧新建一个 adb 客户端进程。MAA 的答案不是"优化 PNG"，而是提供 6 种通道，
连接时**实测每种通道的单帧耗时，选最快的那个**，并允许按兼容性逐级退化。

## 机制

### 六种通道（+ 模拟器直读）

| 方式 | 实现类（`Screencap/`） | 设备端命令 | 原理 | 速度 | 兼容 |
|---|---|---|---|---|---|
| EncodeToFileAndPull | `ScreencapEncodeToFileAndPull` | `shell screencap -p > /data/local/tmp/{TEMP_FILE}` + `pull` | 落盘再拉文件，PC 侧 `imread` | Slow | 高 |
| Encode | `ScreencapEncode` | `exec-out screencap -p` | PNG 走 stdout 管道 | Slow | 高 |
| RawWithGzip | `ScreencapRawWithGzip` | `exec-out screencap \| gzip -1` | 设备端 gzip，PC 侧解压得 raw | Medium | 高 |
| RawByNetcat | `ScreencapRawByNetcat` | `exec-out screencap \| nc -w 3 <host> <port>` | PC 起监听 socket 直收 raw，绕开 adb 转发 | Fast | 低 |
| MinicapDirect | `MinicapDirect` | push `minicap`+`minicap.so`，`-P WxH@WxH/0 -s` | 单次调用出一张 JPEG | Fast | 低 |
| MinicapStream | `MinicapStream` | 常驻 minicap + `forward tcp:1313 localabstract:minicap` | 独立线程持续读帧，取帧只读缓存 | Very Fast | 低 |
| EmulatorExtras | `MuMuPlayerExtras`/`LDPlayerExtras`/`AVDExtras`/`AndrowsExtras` | 无 adb | 直接读模拟器渲染面 | Very Fast | 仅特定模拟器 |

### 为什么 `screencap -p` 是最慢那档

`screencap` 不带 `-p` 时输出**裸 RGBA**，加 `-p` 才在设备端做 PNG 编码：设备 CPU 编码 +
体积仍大 + 每帧一个新 adb 进程 + 一次 `exec-out` 连接。`EncodeToFileAndPull` 更慢：
多一次落盘和 `adb pull` 往返。`RawWithGzip` 省掉 PNG 编码（只 gzip），`RawByNetcat`
再省掉 adb 的管道转发。这跟文档表里的 Speed 列一致，是实测口径不是理论值。

### 默认用哪个 / 什么时候退回 Encode

- MaaFramework：`MaaAdbScreencapMethod_Default` = 全集去掉 `RawByNetcat`/`MinicapDirect`/`MinicapStream`
  （`MaaDef.h:321`）。`ScreencapAgent::init()` 里 `speed_test()` 把每种各跑一次选最快，
  `kDropFirst` 让 RawByNetcat / MinicapStream 先丢一帧（首次慢、从缓存取不准）。
  所以"默认"= **EncodeToFileAndPull / Encode / RawWithGzip / EmulatorExtras 里实测最快的**，
  真机通常落到 RawWithGzip，模拟器落到 EmulatorExtras。
- 退回时机是 `parse()`/`init()` 失败即从候选里 `erase`（`ScreencapAgent.cpp`），
  最终只剩 `Encode` 能兜底——因为它不依赖 `nc`、`gzip`、minicap 预编译二进制、模拟器私有 API。
- MAA(Arknights)：`AdbController::screencap` 首次 `UnknownYet` 时按 **RawByNc → RawWithGzip → Encode**
  顺序计时（`AdbController.cpp:568-663`），并回传 `FastestWayToScreencap` / `ScreencapCost` 事件。

### 截图与输入的并发：串行，没有优先级

MaaFramework 没有专门的截图锁，串行来自架构：`ControllerAgent` 的**所有**动作
（click/swipe/screencap/…）都进同一个 `AsyncRunner<Action>`（`Base/AsyncRunner.hpp`：
单工作线程 + `std::list` FIFO 队列）。**截图在跑，点击就在队列里等。**
唯一例外是 `MinicapStream`：拉流在自己的 `pull_thread_`，队列里的 `screencap()` 只是
`cond_.wait_for(2s)` 等下一帧。

MAA(Arknights) 是显式锁：`call_command` 全程持 `std::unique_lock m_callcmd_mutex`
（`AdbController.cpp:130`），截图和输入共用同一把锁 → 同样串行；adb server 当连接池用，
但 `exec-out` 每次仍是新的 adb 客户端进程，没有长连接复用。

结论：两者都**接受"截图阻塞输入"**，做法是把阻塞时间压到几毫秒级（RawByNc / Extras），
而不是异步化。

### 图像格式与解码（`ScreencapHelper.cpp`）

- `decode_png`：先校验头尾魔数 `\x89PNG` / `\xAE\x42\x60\x82`，再 `cv::imdecode` → BGR。
- `decode_raw`：前 8 字节 = `uint32 width, height`（小端），随后 `4*w*h` 字节 RGBA；
  `header_size = size - 4wh` 容忍前导垃圾；`cvtColor(RGBA2BGR)`；**用最后一个像素
  `alpha == 255` 判断花屏/错位**，不等于 255 直接判失败。
- `decode_gzip`：`gzip::decompress` 后直接走 `decode_raw`。
- Minicap：每帧 `uint32 size` + JPEG，只校验 SOI/EOI（`decode_jpg(..., false)`）；
  `MinicapDirect` 用 `trunc_decode_jpg` 从 `FF D8 FF` 截断。
- 缩放**不在通道层**：`ControllerAgent::postproc_screenshot` 统一 `cv::resize` 到目标尺寸
  （默认短边 720，`INTER_AREA`，`MaaCtrlOption_ScreenshotTargetShortSide` 默认 720）；
  通道返回的是原始分辨率。
- 行尾污染：Windows 下 adb 输出会被写成 CRLF 破坏二进制，`process_data` 会学习并剥离 `\r`
  （`EndOfLine::CRLF/LF`），失败后再试一次解码。

### 失败处理

- 重试/重连（`AdbControlUnitMgr::screencap`，`Manager/AdbControlUnitMgr.cpp:129`）：
  **3 次重连 × 10 次重截**；重截间隔 `500ms * j`，重连间隔 `5000ms * i`；
  重连前 `connection_.kill_server()`；首次截图失败直接返回（`screencap_available_ == false`）。
- 超时：`UnitBase::startup_and_read_pipe` 默认 **20s**；RawByNetcat 单次只给 **1s**
  （注释写明"连不上的时候会一直卡着"）；MinicapStream 单帧 1s、等帧 2s，
  失败后退避 10ms→1000ms 且每 1 分钟才打一次日志。
- 分辨率变化：`_screencap` 比对上次 `image_resolution_`，变了就 `on_image_resolution_changed`
  逐级通知（`ScreencapAgent` 转给 active unit，minicap 需重推 `display_width_/height_`）；
  `ControllerAgent::postproc_screenshot` 另有一份检测，尺寸变了重算目标尺寸。
- 花屏：raw 的 alpha 校验 + PNG 头尾校验 → 解码失败 → 上层重截 → 仍失败则重连。

## 对我们的意义（lorwright）

现状（`src/lorwright/device/adb.py:87`）：每帧 `subprocess.run(adb exec-out screencap -p)`，
新进程、新连接、PNG 全量传输，`cv2.imdecode` 得到 1920×1080 BGR。
`loop.tick_ms=200` 压不住：`engine.py:107` 是 `sleep(max(0, tick_ms - elapsed_ms))`，
即 **tick_ms 只是下限，实际周期 ≈ 截图耗时**。当前机器无设备连接，单帧真实耗时
**未实测**（推断：几百毫秒量级，属 MAA 表里的 "Slow" 档）。

值不值得做 raw/gzip 通道——按收益排序：

1. **先量再改**：给 `screencap()` 打耗时日志（分位数），否则所有优化都是猜。
   这是唯一现在就该做的事，成本近乎为零。
2. **RawWithGzip 是性价比最高的一档**（对应 `screencap | gzip -1`）：不依赖 `nc`、不依赖
   minicap 二进制，Python 侧 `gzip.decompress` + 8 字节头解析 + `np.frombuffer(...).reshape`
   + `cvtColor`，比 PNG 省掉设备端编码。注意 raw 1080p 是 8MB，**不配 gzip 反而更慢**。
3. `screencap -p /sdcard/x.png` + `pull` 方向是**错的**：那是 MAA 表里更慢的
   EncodeToFileAndPull，多一次落盘和往返。不要照这个思路改。
4. Minicap 对我们是**负收益**：JPEG 有损会直接伤模板匹配，MAA 官方文档明确写
   "not recommended"；而且我们要 push 二进制 + `.so`，架构/sdk 矩阵维护成本很高。
5. EmulatorExtras 不可用：我们主路径是 macOS + 真机 ADB，那些是 Windows 模拟器私有接口。

关于"状态不明不点击"：慢截图的主要危害不是帧率低，而是**决策基于旧画面**——
从截图到点击可能已过数百毫秒，点击会落在已经变化的界面上。我们的
`act.tap_wait_ms/drag_wait_ms` 只覆盖了动作后的稳定等待，没有覆盖动作前的帧龄。
真正该补的机制是：**给帧打时间戳，动作前校验 `age <= max_age_ms`，超龄就重截一帧再决定**；
拿不到新帧就退 `NO_OP`（与 `UI 状态 UNKNOWN 时绝不点击` 同一条原则）。
这比换通道更能防"点错地方"，且不依赖任何 adb 技巧。**（该机制尚未实现。）**

## 不适用 / 不要照搬的地方

- **Minicap 全家**：预编译二进制矩阵 + `adb forward` + JPEG 有损，对模板匹配是纯负担。
- **RawByNetcat**：要求设备端有 `nc`（toybox 未必带）且 PC 与设备 IP 可达；USB 真机场景不成立。
- **EmulatorExtras**：Windows 模拟器私有 API，跨平台不可用。
- **3 次重连 × 10 次重截 + 20s 超时**：那是给"跑一整晚、无人值守"设计的；
  我们单次 run 有 watchdog + 恢复策略，重试应更短更保守，否则一次花屏会卡住十几秒。
- **CRLF 修正逻辑**：那是 Windows 特有坑；我们跑在 macOS，暂不需要（但 `decode` 失败时
  别静默 `None`，我们的 `screencap()` 现在抛 `RuntimeError`，方向是对的）。
- 许可：MaaFramework 是 LGPL-3.0、MAA 是 AGPL-3.0。学机制、写自己的实现没问题；
  直接搬运 C++ 代码既无收益也会带入许可义务。

## 参考位置

| 内容 | 路径 |
|---|---|
| 通道实现 | `MaaFramework/source/MaaAdbControlUnit/Screencap/{Encode,EncodeToFile,RawWithGzip,RawByNetcat}.cpp`、`Screencap/Minicap/{MinicapBase,MinicapDirect,MinicapStream}.cpp` |
| 解码/花屏/行尾 | `Screencap/ScreencapHelper.cpp`（`decode_raw` / `decode_gzip` / `decode_png` / `process_data`） |
| 选最快通道 | `Manager/ScreencapAgent.cpp`（`init()` → `speed_test()`，`kDropFirst`） |
| 重试/重连/分辨率 | `Manager/AdbControlUnitMgr.cpp:129` `screencap()`、`_screencap()` |
| 串行队列 + 缩放 | `MaaFramework/Controller/ControllerAgent.cpp`（`postproc_screenshot`）、`Base/AsyncRunner.hpp` |
| 超时默认值 | `Base/UnitBase.cpp:48` `startup_and_read_pipe`（默认 20s） |
| 方法枚举/默认集合 | `include/MaaFramework/MaaDef.h:288-323` |
| 官方取舍表 | `docs/en_us/2.4-ControlMethods.md`（Adb Screencap 一节） |
| MAA 对照实现 | `MaaAssistantArknights/src/MaaCore/Controller/AdbController.cpp:513` `screencap()`、`:130` `m_callcmd_mutex` |
