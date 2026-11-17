# CLI 运行与排障

CLI 是当前的人和 Agent 入口，提供启动、参数、观测与停止；启动后由 `core/` 自主识别、决策、执行、验证和推进。Agent 在开发期根据证据补能力，不作为逐动作调度器。先查询运行状态与事件；需要定位视觉问题时，再查看事件引用的截图。所有命令均在运行程序的同一台电脑、同一个项目目录中执行；这里没有远程控制服务。GUI 待整体能力稳定后再做。

## 基础层与英雄层

- `core/runtime/` 属于通用基础层：会话生命周期、状态、事件、设备占用和停止请求；不包含英雄知识，不截图、不决定打法。
- `core/loop/` 编排冒险与战斗，报告观察事实和停止原因；`device → perceive → decide → act` 的职责保持不变。
- `core/champions/<name>/` 提供英雄牌表、识别回调、策略及偏好；运行会话仅记录所选英雄名。
- `cli/` 使用核心能力并以 Typer 提供命令；本阶段不加入 GUI、Web 服务或前端工具链。

## Agent 推荐流程

```bash
# 后台启动整个冒险；返回 run_id、PID 和启动日志位置。
lorwright sessions start --mode adventure --champion jinx --json

# 优先查询，不会连接 ADB、截图或读取游戏配置。
lorwright sessions status RUN_ID --json

# 最多等待 30 秒；遇到停止、停滞或失联提前返回一条状态 JSON。
lorwright sessions status RUN_ID --wait 30 --json

# 按序号增量读取；记录最后一个 seq，下一次传给 --after。
lorwright sessions events RUN_ID --after 120 --jsonl

# 请求安全停止；requested=true 只是请求已写入，随后再确认终态。
lorwright sessions stop RUN_ID --json
```

首次查询不要填写示例游标 `120`，省略 `--after` 或使用 `0`。省略 RUN_ID 时选择最近更新的会话；多次运行时应始终使用启动回执中的明确 ID。

恢复已在进行的金克丝战斗时，可根据可靠的对局记录指定已完成的起手步骤：

```bash
lorwright sessions start --mode battle --champion jinx --jinx-summoned --rockets-already-played 1 --json
```

`--rockets-already-played` 接受 0–2，必须与 `--champion jinx --jinx-summoned` 一起用于战斗模式。只在已核实火箭出牌结果时填写；重新启动不会自动继承此前会话的策略状态。

`events --follow --jsonl` 可供终端持续跟随，直到终态或失联；Agent 更适合有界的 `status --wait` 配合增量事件查询。查询命令成功只说明取得状态，不代表游戏目标完成。

## f1：从设备开机接入冒险

f1 必须已有 Windows 交互会话、`F1StartPie64` 计划任务和本项目的 Pie64
ADB 配置。运行时可在同一个设备锁内启动或接管模拟器与游戏：

```bash
lorwright sessions start --mode adventure --champion jinx --bootstrap-f1 --open-riot-login --json
```

程序先确认 `127.0.0.1:5555` 在线；未在线时触发交互式计划任务并限时等待。
ADB 在线后还要等待 Android 完成启动及游戏包可查询，再启动或接管 LoR、确认
前台并识别新画面。可选的 `--open-riot-login` 只在识别到登录方式页时，按已标定
坐标核实拳头图标清晰可见且未变暗，再点击一次 Riot 按钮；确认进入表单后返回
`stopped / login_required`，由用户完成登录后重新启动；该选项不填写账号密码。
按钮无法核实返回 `login_button_unverified`，跳转无法核实返回
`login_transition_unverified`，都不会重复点击。其他画面交给冒险循环
识别，未知画面不能盲点。f1 正式工作区为 `C:\Code\lorwright`，最近部署及会话见 [`status.md`](status.md)；
旧部署和备份已清理，历史路径不保证存在。需要读取指定配置文件时，可在启动命令前设置
`LORWRIGHT_ENV_FILE`，例如 PowerShell 中执行
`$env:LORWRIGHT_ENV_FILE = 'C:\Code\lorwright\.env'`（先确认该文件实际存在）。
未设置时仍读取当前目录的 `.env`；已设置的环境变量优先，指定文件不存在时会报错。
`--bootstrap-f1` 不适用于
回放或 desktop。计划任务触发成功不等于模拟器或游戏已准备就绪。

冒险命令或 `sessions start --mode adventure` 可同时传入 `--bootstrap-f1 --auto-login`，
自动打开 Riot 登录方式并在识别到表单时使用配置的凭据提交一次。缺少凭据、坐标或
画面过期时停止；提交后表单未消失会超时停止，不会重试。表单消失不代表登录成功，
后续画面仍由冒险循环识别。当前 ADB 文本输入支持可打印 ASCII（`%` 除外）；
其他字符会以 `login_credentials_unsupported` 停止。凭据通过标准输入传给 ADB，
不会放在宿主机的 ADB 进程参数中；会话事件和日志不记录凭据。Android 内的输入
命令仍会短暂携带文本。已有现有自动登录流程后进入游戏主页的局部实机记录，主页由后续新截图核验；模拟器关闭后的完整冷启动仍未验收。

Windows 后台工作进程使用脱离 SSH 作业对象的方式启动；如果宿主作业禁止
进程脱离，启动会失败并保留诊断，应改用支持脱离的交互环境或前台运行。
设备锁只约束本用户的 lorwright 会话；f1 原有 SYSTEM 看门狗和独立调试命令
不受该锁约束，排障时须留意它们的动作。

每周冒险按未完成候选中的最低星级选择，同星级使用会话 RNG 随机选择。当前视觉字库覆盖实拍 1.5/2 星；通过未完成时钟与完成勾合计三个位置确认列表，支持只剩一个或两个候选。未知星级仍停止；详情页还须独立核对星级与开始按钮。

## 读懂状态

`status` 是生命周期，`health` 是观测到的健康情况，两者分开读取：

| 字段 | 含义 |
| --- | --- |
| `run_id` / `pid` | 本次运行身份与进程；不要仅凭 PID 判断是否有进展 |
| `status` | `starting`、`running`，或 `completed / stopped / cancelled / failed` 终态 |
| `phase` / `reason` | 当前步骤、等待原因或最终停止原因；英文值用于稳定机器判断 |
| `message` | 当前阶段或停止原因的中文说明；机器判断仍使用 `phase` / `reason` |
| `details` | 读到的 UI、观察轮数、动作、策略或异常等上下文，以实际阶段为准 |
| `last_decision` | 最近一次 `decided` 的 `action`、`strategy`、`decision_reason`、`unknown_cards`，供后续等待/执行阶段追溯 |
| `heartbeat_age_s` | 距离运行观测线程最后一次心跳的时间 |
| `last_progress_age_s` | 距离上次报告可见进展的时间；心跳和重复截图不会刷新它 |
| `wait_reason` / `wait_phase` / `wait_deadline` | 保留当前等待的原因、阶段和截止时间；截图采集中也能查询 |
| `health` | `starting / running / waiting / stalled / unresponsive` 或终态 |
| `last_snapshot` / `last_event` | 最近诊断截图的路径与最近事件，便于先读文本再按需看图 |
| `seq` | 当前已保存的事件序号 |

`stalled` 表示在当前观察期限内没有足够进展，不是“游戏必然卡死”的证明，也不授权盲点。`unresponsive` 表示心跳失联或工作进程异常退出；已知进程退出且没有终态时会明确报告 `process_exited_without_terminal`。

建议处理顺序：

1. `running / waiting`：检查 phase、reason、等待截止时间及最后进展，继续有界等待。
2. `stalled`：增量读取事件，先看识别失败、过期帧、动作结果与恢复原因；必要时请求停止。
3. `stopped / failed / unresponsive`：读取最终原因与截图引用，再按需查看对应截图；不要直接重新启动并重复点击。
4. `cancelled`：确认请求确已到安全点生效。

`completed / battle_end` 只说明单场战斗出现结束画面，不证明战斗获胜或整个冒险通关。`completed / adventure_victory` 表示同时识别到最终结算页的胜利、完成时间和最短时间标签，保存结算截图后结束会话，不点击该页继续按钮；它证明已到冒险最终胜利页，是否全程无人介入仍须结合完整运行记录。`tick_limit / node_limit / iteration_limit` 表示调用预算耗尽。`adventure --max-nodes` 是外层观察轮数的上限，不能当作已完成的节点数。

## 决策、局部未知与阻塞

`None` 表示策略弃权，后续策略继续；`NO_OP` 表示当前确需等待。未知牌可以跳过，英雄或组合优先不能无限阻塞已知动作；不要求所有新卡提前建档。程序只限制依赖未知信息的动作，不能凭费用猜未知交互。读数要求应与动作匹配，例如支付能力和攻击所需依据不同。

本轮代码已在 `decided` 阶段报告 `action`、`strategy`、`decision_reason` 和 `unknown_cards`（未识别牌名的手牌索引，不代表这些牌都阻塞）；输入完成通过 `input_sent` 阶段记录。动作前提不足时，等待/停止原因是 `action_preconditions_unverified`，并给出 `missing_readings`；它也可能包含位置或优先权等非数字前提。停止时通过 `snapshot` 提供截图引用，状态侧同时保留 `last_snapshot`。阶段上下文在 `phase` 事件的 `payload` 与状态 `details` 中；状态另用顶层 `last_decision` 保存最近决策，并用 `message` 提供中文说明。

人读 `sessions status RUN_ID` 汇总生命周期/健康、当前说明、最近决策、等待剩余时间、截图与事件游标。人读 `sessions events` 隐藏低层轮询及重复阶段说明，但每次实际输入和结果验证仍保留；加 `--verbose` 显示完整原始事件。`--json` / `--jsonl` 保持结构化输出，JSONL 不过滤或去重，`schema_version=1` 的事件信封不变，说明字段为增量扩展。

任务完成奖励是随机出现的可选插页。程序以固定标题和图标识别，任务名称和奖励内容可变化；出现才处理，识别“繼續”后单次点击并有界等待后继，不要求固定顺序。原页不变或后继未知会以 `task_reward_transition_unverified` 保存截图停止；缺少按钮为 `task_reward_continue_missing`。

卡牌奖励选择新增 `reward_decision` 事件，记录所有候选的 `slot`（从 0 开始）、名称、`preview_cost`、品质，以及选中项和理由。奖励页停止时新增一次 `perception_diagnostic`，记录预期场景、截图、实际匹配分数、阈值和失败检查项；同一证据也放在状态 `details.recognition_diagnostic`，人读状态直接显示摘要。当前诊断覆盖页面标题、副标题和选择按钮；若页面检查均通过而候选或后验失败，仍须结合原停止原因及截图判断。

动作结果事件 `action_outcome` 区分 `waiting`、`needs_input`、`succeeded` 与 `timed_out`。`needs_input` 表示后继需要重新路由，不等于原动作已成功：例如 `hand_expansion_interrupted` 为展开等待遇到明确结算提示，`confirmation_prompt_changed` 为确认阶段切换，`opponent_unit_appeared` 为同一已知 UI/手牌视图下，本帧敌军检出数量较前态增加，包含已有单位再增员。此时仍不能证明前态确为空场或场面已经完整识别。确认交互成功后，原出牌可继续报告 `waiting`，直到独立核验或原截止到达。新增实现是否已部署或实机触发，以 [`status.md`](status.md) 为准。

可用 `sessions events RUN_ID --after SEQ` 增量读取；`--jsonl` 保留完整结构，`sessions status RUN_ID --json` 提供当前状态。诊断只读，不改变动作前提，也不会重复点击。

核心等待与停止原因如下；停止不依赖外部查询：

| 原因 | 含义与期限 |
|---|---|
| `unknown_ui` / `no_action` | 当前界面未知或策略明确等待；期限为 `loop.action_timeout_s` |
| `unknown_target` | 已进入目标选择但要求未知；有界重识别，期限内不猜目标 |
| `action_preconditions_unverified` | 所选动作缺少必要证据；在 `missing_readings` 列出缺失项，期限为 `loop.action_timeout_s` |
| `action_readiness_unverified` | 当前动作相关证据未连续两张新鲜帧稳定；从首次等待起使用固定 `loop.action_timeout_s`，UI 或候选变化不续期 |
| `battle_result_transition` | 原动作截止前取得双区域结算背景证据，进入一次最多 60 秒只读观察；不重放输入或通知原动作成功 |
| `battle_result_transition_unverified` | 上述阶段到期仍未确认结束，保存截图停止；返回战斗时仍适用原动作截止 |
| `action_plan_unavailable` | 无法生成有效输入计划；期限为 `loop.action_timeout_s` |
| `stale_frame` / `frame_expired_during_decision` | 重新截图，持续过期达到 `loop.max_frame_age_s` 后停止 |
| `enemy_turn` | 等待对手，最长 60 秒；超过观察预算不等于已证明网络故障 |
| `action_timeout` | 输入已发出，但在动作观察期限内未验证结果；保存证据并停止，结束回合也不自动重发 |
| `game_reconnecting` | ADB 实机会话明确识别重连标题与退出按钮后暂停输入，连续观察 300 秒；普通 UNKNOWN 不进入此路径 |
| `reconnect_restart_transition` | 本会话单次重启 LoR 后，最长 120 秒等待新鲜、可识别的主页、地图或战斗；登录复用已启用的 `--auto-login` |
| `reconnect_restart_failed` / `reconnect_restart_unverified` | 重启命令失败，或未核验重启后的游戏场景，停止并保留证据 |
| `reconnect_recovery_exhausted` | 单次重启后再次连续重连五分钟，停止，不再自动重启 |

ADB 的 battle/run 与 adventure 共用重连监测，包括奖励等交互中的后继截图。重连证据消失或帧过期即结束本段连续计时；未重启时原动作截止保持不变，不因网络等待宣告动作成功。达到五分钟后先退出旧交互栈，再通过既有 `Device.restart_app` 关闭并启动 LoR；不重启模拟器。重启后重新创建循环和策略，不重放旧动作或沿用旧的中局恢复参数。登录页需要本次启动原有的 `--auto-login` 授权，否则以 `login_required` 停止。每个会话最多重启一次；此专项恢复不依赖普通卡住恢复的 `recovery.allow_client_restart`，也不改变它。回放与 desktop 不启用重连重启。本轮没有指数退避或网络监测。

结束回合与让过仍要求连续两张新鲜帧的场景、提示、展开态，以及手牌和各排单位的位置/数量稳定；卡名、费用、单位数值或关键字的识别波动不阻断该固定按钮输入，路由器逐帧重新选择动作。未知界面、集合变化、缺失位置、攻击令牌或空手确认变化仍须重新稳定。其他动作继续核验自身的牌或单位身份、数值与位置。

核心用单调时钟限制等待；重复轮询不延长期限。已验证的动作结果或新的已识别场景可开启独立观察窗口。结束回合、换牌确认、独立战斗确认，以及已展开且有可见单位卡证据的实际出牌，动作观察期限至少为 20 秒；单位出牌包含召唤与触发动画，预算从本次输入后固定建立，UNKNOWN 轮询不续期。仅展开手牌、无单位外观依据的出牌及其他输入使用配置的动作期限，英雄专属后验也可要求更长窗口。出牌的附加确认受父动作原截止限制，不能因确认或提示切换重新获得完整预算。`health=stalled` 是观测状态，与 `status=stopped` 终态分别读取，不能把健康提示当作已经停止。离线与实机范围见 [`status.md`](status.md)。

当前单张弃牌提示下，程序识别可选卡面、重复插画和费用，连续两帧核实相关证据后只点选一次；沿普通动作期限等待明确返回战斗，UNKNOWN 动画和未关闭的弃牌页均不算成功，到期以 `action_timeout` 保存证据停止。候选或必要费用拒识分别为 `discard_candidates_unverified` / `discard_cost_unverified`；AdventureLoop 可从弃牌页交接 Engine。实拍已确认本次点击会直接关闭选择，无额外确认按钮；历史 `discard_sample` 仅为开发采样停止，不能据此宣告弃牌或冒险完成。其他弃牌数量及外观未验收，更多范围见 [`status.md`](status.md)。

冒险从已打开的节点面板恢复时，先识别面板并核验「旅行」或「戰鬥」按钮，再执行一次相应操作及后继场景核验；不要求先回地图重新选节点。已完成面板仍按原流程关闭；面板操作未知时以 `panel_unknown` 保存截图、零输入停止。仅有地图而节点点击未打开面板时，仍以 `map_panel_not_open` 停止，不猜按钮位置。

金幣寶箱详情以完整标题和「取走寶藏」文字联合核验，单次领取后等待面板关闭并返回地图；未知或未关闭页面不算成功，到期以 `gold_chest_transition_unverified` 保存截图，不重复点击。`gold_chest_map_transition` 仅证明交互结束，`reward_credited_verified=false`，不根据预览金额推断到账。

若头像遮挡短路径，导致两端安全留白之间没有可验证取样区，程序可在核实地图缩放控件、当前节点和未完成亮环后，每次冒险运行仅放大一次取证。只有新帧按原规则重新核实出可达节点，才报告 `map_zoom_transition` 并允许选点；没有新证据时以 `map_zoom_unverified` 停止，不重复放大或猜点。放大后的地图须继续核验完整控件；当前节点由头像附近检测到的圆节点及其可见完成勾或光环共同确认，不能仅按头像的固定像素偏移推断。重叠圆候选按可见中心和光环覆盖率区分；每条分支仍独立核验连续亮线与目标。目标锁图标在候选节点范围内同时检查原尺寸与已实拍的 1.3 倍尺寸，亮线连续性及锁定拒绝阈值保持。

## 前台与离线回放

原有入口仍可直接运行，现会创建独立会话：

```bash
lorwright adventure --champion jinx --max-nodes 30 --jsonl
lorwright run --champion elise --max-ticks 50 --jsonl

# 只读本地截图，输入只记录，不连接或控制游戏。
lorwright run --replay tests/fixtures/screens --max-ticks 3 --jsonl
lorwright adventure --replay tests/fixtures/mapnav --max-nodes 1 --jsonl
```

这些现有 fixture 目录是独立场景集合，不是连续录像；上述回放仅验证命令与观测链路，不能作为冒险完成证据。精确复现某次行为时使用有序的专用截图目录。

前台不带 `--jsonl` 时输出人读信息；带此选项时 stdout 仅输出 UTF-8 JSONL，日志进入 stderr。不要把 `console.log` 当 JSONL 解析，它用于查看启动期间的日志与异常。

每条会话事件含 `schema_version, run_id, seq, ts_utc, type, payload`；序号在一次运行内递增。
若创建会话前失败，前台机器模式输出 `type=error, seq=0`，此时 `run_id` 可以为空。`session_started` 表示进入会话，`phase` 报告阶段，战斗事件保留动作与结果，`health` 提示状态变化，`session_finished` 是唯一终态。输入已发送和动作成功分别记录。

前台退出码：`0` 为单场目标结束或调用者预算耗尽，`1` 为执行/启动失败，`2` 为命令参数错误，`3` 为需要介入的安全停止，`130` 为协作取消或 Ctrl+C。判断冒险结果仍须检查终态与原因，不能只看退出码。

## 运行文件与并发

默认文件位于已被 Git 忽略的目录：

```text
logs/runs/<run_id>/
  status.json       # 原子更新的当前状态
  events.jsonl      # 按顺序追加的机器事件
  console.log       # 后台启动时的 stdout/stderr 诊断
  snapshots/        # 按需保存的截图
  stop.request      # 外部停止请求，存在时在下一个安全点处理
```

后台启动还保留进程回执。设备占用锁放在本机用户缓存下的 `lorwright/device-locks/`
（Windows 为 `LOCALAPPDATA`，Mac 为 `~/Library/Caches`），不随项目或日志根目录改变。
ADB 与 desktop 会话共用一个交互设备锁，避免同时控制同一模拟器；回放按目录
独立。更换日志目录不会绕开占用约束。

用环境变量 `LORWRIGHT_RUNS_DIR` 指定其他运行根目录；会话查询命令也支持 `--root PATH`。前台运行和查询必须使用同一根目录。运行状态不持久化完整配置或账号密码。

停止请求不会杀进程，必须等当前完整输入结束后才停止新输入。若设备调用阻塞，请查看心跳与进展，保留诊断；请求 ACK 不代表手势已中断。无法响应的进程不会被 CLI 自动强杀或重启游戏。

历史日期日志仍可由 `python tools/analyze.py logs/日期` 读取；新会话使用 `python tools/analyze.py logs/runs/RUN_ID`，只统计其中的战斗事件。
