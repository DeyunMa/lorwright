# F1 运维脚本

这三个脚本是 f1 上的独立兜底，不参与 `lorwright` 的游戏内决策。

| 脚本 | 计划任务 | 运行身份 | 职责 |
|---|---|---|---|
| `netwatchdog.ps1` | `F1NetWatchdog`，每 2 分钟 | SYSTEM | 按链路、上游、代理、Tailscale 分类故障并对症恢复 |
| `gamewatchdog.ps1` | `F1GameWatchdog`，每 5 分钟 | SYSTEM | 模拟器进程、ADB、LoR 进程的最外层恢复 |
| `start-pie64.ps1` | `F1StartPie64`，手动/被调用 | Administrator + Interactive | 在交互式桌面启动 Pie64；已在跑时只记日志 |

## 只读盘点

在 f1 执行 `powershell -NoProfile -File tools/f1/audit.ps1`，输出 JSON：正式 Git
工作区的 HEAD、变更数量及非敏感变更文件的 SHA-256，部署目录大小及其中 `project`
检出的状态，以及进程命令行和计划任务动作中明确引用这些路径的记录。不会输出
命令行或任务参数，也不读取凭据、配置及日志文件。忽略文件、间接引用、环境变量、
服务和包含换行的文件名需要另行检查；目录大小遇到无权限项可能不完整。该脚本
仅供盘点，不能凭空结果认定目录可以删除。

## f1 离线时的重试

实机开发中遇到 f1 离线或 SSH 连接超时，先立即查询一次当前会话。若仍不可达，从首次失败起每隔 5 分钟重试一次，最多重试 5 次。SSH 查询一旦恢复，结束本轮重试，核对部署、控制进程、原会话和实时画面后继续当前冒险。若 5 次均失败，记录最后一次检查结果并结束本轮等待。

## 更新正式工作区

日常开发在 Mac，f1 的正式工作区为 `C:\Code\lorwright`；正常情况下在该目录
使用 `git pull --ff-only` 更新，先检查是否有未提交改动。当前 f1 的 origin 使用
HTTPS，已验证可 fetch。以下 bundle 流程用于远程仓库不可访问或旧工作区有待保全
改动时的受控恢复，不是日常更新方式。

`update-checkout.ps1` 面向现有 `C:\Code\lorwright`，要求先将含有
`refs/heads/main` 的 Git bundle 复制到 f1，且 bundle 的前置对象已存在于该仓库。
停止自动化会话，暂停可能重新启动会话的外部任务，并避免其他人同时修改工作区。
脚本保守拒绝任何 Python 或 lorwright 进程，以及正式工作区默认会话目录或当前
`LORWRIGHT_RUNS_DIR` 中的非终态记录；它不能阻止检查后其他进程启动，也不能发现
其他位置的孤立状态文件。运行前须自行核对所有部署目录和看门狗。

```powershell
powershell -NoProfile -File tools/f1/update-checkout.ps1 -Bundle C:\path\project.bundle
powershell -NoProfile -File tools/f1/update-checkout.ps1 -Bundle C:\path\project.bundle -Apply
```

默认预览验证 bundle 和 main，输出 HEAD、目标提交和变更数量；真正执行时 fetch
到 `FETCH_HEAD`，检查当前 HEAD 是目标祖先，再以 `stash push -u` 保存已跟踪和
未跟踪变更，最后 `merge --ff-only`。忽略文件（包括 `.env`、`.venv`）保留；若它们
阻碍合并则停止。目标已是当前 HEAD 时不会创建 stash。脚本的控制台输出是操作
日志，可由操作者重定向到受保护的位置；不要将日志和凭据提交到 Git。

stash 不会自动恢复，因为旧文件可能与新版本冲突。更新或中断后先检查
`git status`、`git log -1` 和 `git stash list`，按记录的 stash 哈希确认内容；
需要恢复时使用 `git stash apply <stash-hash>`，检查并解决冲突，确认所需内容
已安全保留后再自行处理 stash。若中断发生在 stash 输出前，按 `f1-update-` 标记
查找。fetch 可能已更新 `FETCH_HEAD`；重试前先核对 HEAD 和 stash，不要用
reset、clean 或删除文件来排除冲突。此流程不自动归并旧目录的独有改动，也不
更新看门狗、虚拟环境或安装依赖。

同步前在开发环境完成适用的自动化回归。同步后核对目标提交、工作区、控制进程和会话状态。获准继续实机操作时先检查实时画面，再按当前验收目标观察后继和终态。

## 归档历史部署

`archive-deployments.ps1` 默认只预览；`-Mode Archive -Batch <名称>` 完整复制
并校验历史部署，`-Mode Cleanup -Batch <名称> -ConfirmRemoval` 再次校验后移除
原目录。归档保留完整代码、实机截图和日志，可能含私人数据；含 `.env`、`.git`
或链接的目录会跳过。操作前须停止写入并检查外部引用，脚本无法消除并发风险。

## 隔离部署（仅在用户同意保留独立实验现场时）

f1 只保留 `C:\Code\lorwright` 一份项目，日常同步不创建部署目录。用户同意的实验现场用完后按下文归档清理。
本机运行 `python tools/f1/deploy.py --host f1 --name RUN_NAME` 预览；追加
`--apply` 后，脚本在 f1 的 `C:\Code\lorwright-deployments\RUN_NAME` 新建目录，
上传运行源码、工具脚本、模板和项目配置，逐文件校验 SHA-256 并保存清单和回执。
目录名已存在时拒绝覆盖；失败目录保留用于排查，重试时使用新名称。该脚本
不会修改 f1 已有工作区、虚拟环境或看门狗，也不会上传 `.env`。使用现有
Python 环境运行时，将新目录的 `src` 放入 `PYTHONPATH` 并以新目录为工作目录。

## 部署看门狗

把三个 `.ps1` 放到 `C:\Windows\Temp\`，然后创建任务：

```powershell
$startAction = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -ExecutionPolicy Bypass -File C:\Windows\Temp\start-pie64.ps1'
$startPrincipal = New-ScheduledTaskPrincipal -UserId 'Administrator' -LogonType Interactive -RunLevel Limited
$startSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'F1StartPie64' -Action $startAction -Principal $startPrincipal -Settings $startSettings -Force

$gameAction = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -ExecutionPolicy Bypass -File C:\Windows\Temp\gamewatchdog.ps1'
$gameTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$gamePrincipal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$gameSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'F1GameWatchdog' -Action $gameAction -Trigger $gameTrigger -Principal $gamePrincipal -Settings $gameSettings -Force
```

`F1NetWatchdog` 的部署命令见脚本头部注释。任务配置使用 5 分钟执行上限，上一轮未退出时跳过重叠轮次，避免单个探测挂起后长时间占住计划任务。

## 网络诊断边界

- 故障层由绑定 WLAN 接口、绕过 Clash 的 TCP 探测判定：网关 TCP/53 有应答或被拒即局域网可达，超时再用 `ping -S` 兜底；223.5.5.5、119.29.29.29 的 TCP/53 任一连通即外网可达。fake-ip 下系统 DNS 总返回本地假地址，已不作健康依据。1.1.1.1 在 f1 网络中始终超时，已移除。分类与动作表见脚本头部，`tools/f1/test-netwatchdog.ps1` 在 f1 上运行覆盖分类、动作表及 `-Simulate -DryRun` 全流程。
- 2026-11-19 至 20 的断网经此分类均为 link：网关 TCP 与 ICMP、直连 223.5.5.5 同时超时，WiFi 仍显示关联、信号 88–89%。驱动断开事件多为 0x48005「动态密钥交换未能在配置的时间范围内成功」。Clash 重启与关闭 TUN 对这类故障无效；重连 WiFi 后 1–2 分钟恢复。
- 看门狗不再改写 `verge.yaml` 开关 TUN：Clash Verge 界面持有内存配置，外部改写不生效，还会让 `enable_tun_mode` 与实际状态不一致。2026-11-20 已把被旧逻辑改成 `false` 的值恢复为 `true`。
- Clash 应用 `logs/latest.log` 的摘要只统计最近五分钟的 WARN、ERROR 和已识别的 WebSocket 重置，不复制日志正文或节点信息。
- Tailscale 持续离线时重启服务，冷却 15 分钟；先将冷却截止写入状态文件，再重启。
- 无线重连使用脚本中的 `$WifiProfile`，须在目标机以 SYSTEM 身份确认配置存在。`WlanConnect` 返回 0 只表示请求已提交，须另看无线事件及后续网络检测。
- 每轮有开始和正常退出耗时；没有结束记录只能提示中断或日志失败，不能单独断言系统挂起。link 故障不退避；其他故障连续 8 次后退避 15 分钟，退避期只记录 Clash 摘要。

## Clash 与 Tailscale

f1 的 Clash Verge 开着 TUN，默认路由经 Meta 网卡。2026-11-19 的日志显示，Tailscale 的控制面、STUN 和 DERP 流量曾随规则走代理节点，出口 IP 在国内地址和多个境外节点间切换；代理不可用时控制面连接持续超时，远程访问和 LoR 一起断开。当前订阅的规则增强文件（`profiles.yaml` 中当前订阅 `option.rules` 指向的文件）已在 `prepend` 加入 `tailscaled.exe`、`tailscale-ipn.exe`、`tailscale.exe` 三条 `PROCESS-NAME ... DIRECT`，修改前的文件备份在 `C:\Code\lorwright-evidence\clash-backup-20261119`。更换订阅或重建规则增强后需重新核对。

2026-11-20 的调整，修改前文件备份在 `C:\Code\lorwright-evidence\clash-backup-20261120`：

| 项 | 位置 | 值 |
|---|---|---|
| 顶层 `ipv6` | 界面内核配置 `config.yaml` | `false`（f1 无 IPv6，netcheck `v6=false`） |
| `dns.ipv6` | 当前订阅的合并增强文件（`option.merge`） | `false` |
| `enable_tun_mode` | `verge.yaml` | 恢复为 `true` |

改完后经计划任务以交互身份重启 Clash Verge 界面，运行配置重新生成，核对 `ipv6`、`dns.ipv6`、TUN、Tailscale 直连规则与国内 HTTP 均正常。`dns.fake-ip-filter` 无论写在合并增强还是脚本增强里，此版本 Clash Verge 都不会写入运行配置，Tailscale 域名仍解析为 198.18.x.x；脚本增强已回滚，该项未生效。TUN 的 `stack: mips` 经 mihomo v1.19.33 `-t` 校验可接受，未改。`allow-lan: true` 当前没有局域网客户端，按用户是否需要再定。

无线网卡（Realtek 8852BE）高级属性：`Roaming Aggressiveness` 从 `4. Medium` 调到 `2. Lowest`，`Multi-Channel Concurrent` 从 `Enabled` 调为 `Disabled`。脚本先记录旧值，重启网卡后 120 秒内网关不通会自动回滚；实际 12 秒恢复。

## 边界

- `gamewatchdog` 检查模拟器、ADB 和 LoR 进程。它遵循网络看门狗尚在生效的退避时间。故障计数只在状态文件更新时间距当前不足 6 分钟时压住游戏恢复，过期会记入日志。ADB 进程探测报错时记录探测失败，本轮不重启 LoR。`-DryRun` 只记录能否看到模拟器进程，跳过 ADB 和恢复写入。
- LoR 客户端重启会回到 Riot 登录页，脚本会尝试 `lorwright login`；自动登录失败时只记录，不无限重试。
- 模拟器实例必须由交互式会话启动；`F1StartPie64` 使用 Administrator + Interactive，不能改成 SYSTEM。
- 默认不重启整机。
