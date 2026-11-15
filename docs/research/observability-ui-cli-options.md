# 可视化壳与 Agent CLI：有界方案调研

> 讨论后的范围决定：当前只完善 CLI，不做可视化或 HTTP 服务。已实现部分见
> [`../cli.md`](../cli.md)；本文保留选型依据，下面的 GUI、SSE 及完整控制接口
> 仍是未实施提案，不能据此假设项目已支持。

本文面向 Windows 主运行、Mac 开发的方案讨论；依据当前源码与下列官方资料，不追逐版本号，也不作未经实测的体积、内存或速度排名。仅文档调研，未安装、打包、部署或连接设备。

## 建议

先把现有 Python 运行逻辑整理为共享 `RunSession` 控制与事件接口，再做 Typer 机器模式和 React 本地 Web 界面；需要安装器、托盘和窗口管理时，再选择 Tauri 或 Electron。若当前就需要桌面壳且愿意维护 Rust 工具链，可优先验证 Tauri；团队偏 Node.js 时 Electron 同样成立。

这些是调研时的建议；**FastAPI、SSE 与完整控制契约仍不能视为项目已有能力**。后续已经实现的 CLI 会话以 `docs/cli.md` 为准。若未来只需要 Python 工具窗口，且不要求复用 React 界面，PySide6 可减少语言栈。

## 当前源码基础

- [`events.py`](../../src/lorwright/util/events.py)：`emit(**fields)` 将字段 JSON 序列化后交给绑定 `event=True` 的 Loguru；字段自由，没有统一 schema、`run_id`、`seq` 或 UTC 时间戳。
- [`logger.py`](../../src/lorwright/util/logger.py)：人读日志已输出 stderr；事件写入按日期共享的 `events.jsonl`，其 sink 格式仅为消息。普通 stderr / run.log sink 未排除事件，因此事件也会出现在人读日志中，并非独立 stdout JSONL 协议；日期文件也不提供会话隔离。
- [`engine.py`](../../src/lorwright/loop/engine.py)：同步循环已有 tick、动作结果 waiting / timed_out、耗时、watchdog、截图与安全停止；`UNKNOWN` 不操作，过期画面跳过输入。`finally` 关闭设备并写停止日志，但这不等于完整生命周期事件。
- [`main.py`](../../src/lorwright/main.py)：已使用 Typer，`run` / `adventure` 通过 `KeyboardInterrupt` 停止；Rich `Console()` 也打印到 stdout。目前这些入口没有共享会话控制或纯机器输出模式，不能直接把 stdout 当 JSONL 消费。
- 现有 `ActionOutcome.WAITING` 是动作结果等待，watchdog 是局部游戏状态诊断；均不应直接当作会话健康状态或独立 heartbeat。

## 四条路线比较（事实据官方资料，价值与成本为方案判断）

| 路线 | 官方确认的基础 | 对本项目的价值 | 主要成本与边界 |
| --- | --- | --- | --- |
| Tauri + React + Python | `externalBin` 可捆绑外部程序，官方明确举例 Python CLI / API server + PyInstaller；需对应 target triple 的二进制，前端启动受 shell capability 约束。[1] | 复用 Web UI，Python 保留感知、决策与执行；壳管理进程与窗口。 | 增加 Rust、前端和 Python 三套构建；系统 WebView 在 Win/Mac 不同，需双平台验证；sidecar 打包、退出与事件桥接仍要设计。[1][2][3] |
| Electron + React + Python | main 是 Node.js 入口，renderer 渲染页面，通过 preload / IPC 暴露能力；utility process 本身运行 Node.js。[5] | Node.js 主进程适合管理 Python 子进程；React 界面可与本地 Web 共享。 | Python 仍须另行打包；不要将 utility process 误认为 Python 解释器。renderer 到进程控制应走受限接口，不能暴露任意 shell。[5] |
| PySide6 | Qt for Python 跨桌面平台；官方提供 `pyside6-deploy`，其封装 Nuitka，生成各平台程序或应用包。[6][7] | 可直接复用 Python 类型与逻辑，适合配置、状态、截图和日志工具窗。 | UI 技术改为 Qt Widgets / QML，不能直接复用 React；需避免同步引擎阻塞 UI，并验证 Qt 插件、资源和原生依赖打包。跨平台支持不等于 Mac 一次构建覆盖 Windows。 |
| 本地 Web → 后续桌面壳 | FastAPI / Starlette 提供流式响应，可据此实现 SSE；浏览器提供 UI，桌面壳可之后接入。[9][10] | 先验证观测与控制需求，推迟安装器选择；CLI 与 UI 共用 Python 会话。 | 要管理本地服务端口、启动、关闭、访问边界与订阅恢复；浏览器窗口关闭不等于任务取消。迁移时保留同一接口，替换启动与窗口层。 |

“先 Web”是当前推荐的实施顺序，不表示最终一定需要 HTTP：桌面壳也可直接桥接子进程 JSONL。若无需浏览器独立使用，初版就采用进程管道会少一个常驻服务。

## Windows / Mac 开发与发布约束

- Tauri 开发需要 Rust；Windows 还需要 Microsoft C++ Build Tools 与 WebView2，桌面 macOS 可使用 Xcode Command Line Tools；React 前端另需其构建工具链。[2]
- Tauri Windows 使用 WebView2，macOS 使用 WKWebView；不能据此承诺像素、渲染或资源消耗完全一致。[3]
- Tauri 可生成 MSI / NSIS 安装器；MSI 构建要求 Windows，文档也给出 NSIS 交叉构建路径。不要概括成 Tauri 所有部分都禁止交叉构建。[4]
- **Python 侧才是这里明确的跨编译约束**：PyInstaller 不是 cross-compiler；Windows 产物在 Windows 构建，Mac 产物在 Mac 构建。即使壳能交叉构建，也不能据此从 Mac 得到完整 Windows Python sidecar。[11]
- 建议后续采用 Win / Mac 分开的构建与验收任务；Mac 日常开发可用回放和假事件，Windows 验证安装、设备工具路径、进程退出及实际依赖。此处未执行任何构建。
- 对外分发还需处理签名；Tauri 文档要求 macOS 分发签名，App Store 外分发另需 notarization，并提供 Windows 签名指引。开发依赖不应被当成终端用户必装工具。[12]
- 不以框架名字推断体积或性能；需要带本项目 Python、原生库、模板资源的真实产物，才能测冷启动、内存、安装和升级成本。

## 共享 Python RunSession 契约提案

`CLI / HTTP适配器 / 桌面桥 → RunSession → 现有冒险循环与 Engine`；UI 不复制决策、不直接控制设备。会话只编排运行、取消、状态与事件，感知/决策/执行边界保持原有职责。

- 最小接口：`start(config) -> run_id`、`status(run_id)`、`subscribe(run_id, after_seq)`、`cancel(run_id, request_id)`；先支持单活动运行，拒绝对同一设备的并发控制。跨 CLI 调用控制需由常驻 supervisor 接收请求，不能假定另起一个 CLI 就能访问内存对象。
- 统一事件信封：`schema_version, run_id, seq, ts_utc, type, payload`；`run_id` 唯一，`seq` 在单次运行内严格递增，UTC 用带 `Z` 的 ISO 8601。耗时和 deadline 使用 monotonic 时钟，不用墙钟差值推算。
- 生命周期建议：`created → starting → running → cancelling → cancelled`，或从执行阶段进入 `completed / failed / stopped`；终态唯一、带原因。`completed` 必须有目标完成证据；达到 tick/node 上限或安全停止应为 `stopped`，不能冒充通关。
- `waiting` 表示正常等待动作后验、动画或人工处理，带 `reason / since / deadline`；`stalled` 表示超过该阶段进展期限，带最后进展和证据。二者是独立于生命周期的健康字段，不把同一画面立即判为卡死。
- `heartbeat` 带当前阶段、最后进展时间、最后事件序号；独立于阻塞工作循环发出。进程活着不等于有进展，heartbeat 不得替 stalled 清零；观测链失联也要和工作停滞区分。
- 可观测事件优先覆盖：阶段变化、感知摘要、决策及原因、输入已发送、动作后验、等待、停滞、截图引用、异常与终态；截图用 artifact 引用，避免把图片塞进高频事件。
- 取消为协作式：先确认 `cancel_requested`，在动作前及完整手势后的安全点停止新输入，收尾设备并发终态。不能在按住/拖拽中间直接杀进程；后端应在异常收尾释放触点。请求 ACK 不等于已取消，超时未退出须明确报告，不能伪造终态。
- Windows 控制不依赖 Unix signal；stdin JSONL 或本地控制 API 都映射同一取消请求。Ctrl+C 也走该路径；重复 request_id 幂等，过期 run_id 明确拒绝。
- 事件持久化与订阅来自同一有序源；慢消费者使用有界队列，控制/终态事件不得静默丢失。断开订阅不自动取消任务，重连按 seq 补读；历史过期返回显式 gap 与当前快照。

## CLI 与 SSE 适配提案

- 沿用 Typer，其官方文档覆盖类型驱动参数、子命令、help 与补全；它解决命令组织，不会自动提供上述运行协议。[8]
- 提议机器模式（如 `--output jsonl`）：stdout 只含 UTF-8、每行一条合法 JSON 并及时 flush；stderr 保留人读日志，关闭机器输出中的颜色、进度条、Rich 提示及交互询问。普通人读模式可保留。
- 先有前台 `run` 事件流；若需要独立 `status / cancel / events --after-seq` 命令，再通过 supervisor 连接活动会话。明确配置错误、执行失败、安全停止、取消的退出码，发布机器可读 schema 与命令能力说明。
- FastAPI `StreamingResponse` 接受同步或异步迭代器并流式发送，但原始流不自动等于 SSE；SSE 要遵守 `text/event-stream` 的 `id / event / data` 帧格式。[9][10]
- SSE 实施依据 Starlette `StreamingResponse` 文档：其只承诺流式响应体；同页把 `EventSourceResponse` 列为第三方响应。建议先明确帧编码、游标与保活责任，再决定是否采用专用 SSE 库，不依赖特定 FastAPI 新 API。[10]
- 若采用 SSE：`POST /runs`、`GET /runs/{id}`、`POST /runs/{id}/cancel` 管控制，`GET /runs/{id}/events` 单向推送；事件 id 映射 run_id + seq，重连游标与补读由服务实现。SSE keepalive 注释只保连接，不能代替会话 heartbeat / 进展证据。
- 本地服务仅监听 loopback，校验来源与本地会话凭证；不要把“localhost”当成任意网页都可发控制请求的理由。同步 Engine 放独立工作执行单元，不能阻塞异步 API；流连接取消也不等于底层手势安全取消。[9]

## 讨论与后续验证范围

建议先决定：是否必须浏览器独立使用、初版是否需要安装器、由谁维护 Rust/Node/Qt，以及任务在 UI 关闭后继续还是请求安全退出。随后用保存截图与假事件验证事件排序、CLI 纯 JSONL、等待/停滞区分、订阅恢复及手势边界取消；再做 Windows 包的最小试验。本次只核对源码与官方文档，未验证这些提案的运行效果。

## 官方资料（本次实际读取）

[1] Tauri v2 外部二进制 / Python sidecar：https://v2.tauri.app/develop/sidecar/
[2] Tauri 开发依赖：https://v2.tauri.app/start/prerequisites/
[3] Tauri WebView 差异：https://v2.tauri.app/reference/webview-versions/
[4] Tauri Windows 安装与构建：https://v2.tauri.app/distribute/windows-installer/
[5] Electron Process Model：https://www.electronjs.org/docs/latest/tutorial/process-model
[6] Qt for Python Deployment：https://doc.qt.io/qtforpython-6/deployment/index.html
[7] pyside6-deploy / Nuitka：https://doc.qt.io/qtforpython-6/deployment/deployment-pyside6-deploy.html
[8] Typer 官方文档：https://typer.tiangolo.com/
[9] FastAPI StreamingResponse：https://fastapi.tiangolo.com/advanced/custom-response/
[10] Starlette Responses（官网抓取遇 TLS 错误，已读取官方仓库文档）：https://www.starlette.io/responses/#streamingresponse ；https://raw.githubusercontent.com/Kludex/starlette/main/docs/responses.md
[11] PyInstaller 跨编译限制：https://pyinstaller.org/en/stable/ （同样核对官方仓库：https://raw.githubusercontent.com/pyinstaller/pyinstaller/develop/README.rst）
[12] Tauri 发布与签名：https://v2.tauri.app/distribute/
