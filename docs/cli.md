# CLI 运行与排障

CLI 是当前的人和 Agent 入口。先查询运行状态与事件；需要定位视觉问题时，再查看事件引用的截图。所有命令均在运行程序的同一台电脑、同一个项目目录中执行；这里没有远程控制服务。

## 基础层与英雄层

- `runtime/` 属于通用基础层：会话生命周期、状态、事件、设备占用和停止请求；不包含英雄知识，不截图、不决定打法。
- `loop/` 编排冒险与战斗，报告观察事实和停止原因；`device → perceive → decide → act` 的职责保持不变。
- `champions/<name>/` 提供英雄牌表、识别回调、策略及偏好；运行会话仅记录所选英雄名。
- CLI 继续使用 Typer；本阶段不加入 GUI、Web 服务或前端工具链。

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

`events --follow --jsonl` 可供终端持续跟随，直到终态或失联；Agent 更适合有界的 `status --wait` 配合增量事件查询。查询命令成功只说明取得状态，不代表游戏目标完成。

## 读懂状态

`status` 是生命周期，`health` 是观测到的健康情况，两者分开读取：

| 字段 | 含义 |
| --- | --- |
| `run_id` / `pid` | 本次运行身份与进程；不要仅凭 PID 判断是否有进展 |
| `status` | `starting`、`running`，或 `completed / stopped / cancelled / failed` 终态 |
| `phase` / `reason` | 当前步骤、等待原因或最终停止原因；英文值用于稳定机器判断 |
| `details` | 读到的 UI、观察轮数、动作、策略或异常等上下文，以实际阶段为准 |
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

`completed / battle_end` 只说明单场战斗出现结束画面，不证明战斗获胜或整个冒险通关。`tick_limit / node_limit / iteration_limit` 表示调用预算耗尽。`adventure --max-nodes` 是外层观察轮数的上限，不能当作已完成的节点数。

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
同种实际设备入口由一个会话控制；回放按目录独立。更换日志目录不会绕开占用约束。

用环境变量 `LORWRIGHT_RUNS_DIR` 指定其他运行根目录；会话查询命令也支持 `--root PATH`。前台运行和查询必须使用同一根目录。运行状态不持久化完整配置或账号密码。

停止请求不会杀进程，必须等当前完整输入结束后才停止新输入。若设备调用阻塞，请查看心跳与进展，保留诊断；请求 ACK 不代表手势已中断。无法响应的进程不会被 CLI 自动强杀或重启游戏。

历史日期日志仍可由 `python tools/analyze.py logs/日期` 读取；新会话使用 `python tools/analyze.py logs/runs/RUN_ID`，只统计其中的战斗事件。
