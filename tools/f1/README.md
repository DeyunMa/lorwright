# F1 运维脚本

这三个脚本是 f1 上的独立兜底，不参与 `lorwright` 的游戏内决策。

| 脚本 | 计划任务 | 运行身份 | 职责 |
|---|---|---|---|
| `netwatchdog.ps1` | `F1NetWatchdog`，每 2 分钟 | SYSTEM | HTTP/DNS/Tailscale 健康检查；Clash/TUN/WiFi/Tailscale 分级恢复 |
| `gamewatchdog.ps1` | `F1GameWatchdog`，每 5 分钟 | SYSTEM | 模拟器进程、ADB、LoR 进程的最外层恢复 |
| `start-pie64.ps1` | `F1StartPie64`，手动/被调用 | Administrator + Interactive | 在交互式桌面启动 Pie64；已在跑时只记日志 |

## 同步项目运行文件

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

`F1NetWatchdog` 的部署命令见脚本头部注释。

## 网络诊断边界

- 看门狗记录 HTTP、DNS、Tailscale、无线事件、Wi-Fi 信号快照、路由和恢复动作；网关探测指定 WLAN 源地址，并记录 Windows 选路，不能单凭 ICMP 超时判断路由器故障。
- 每轮额外尝试网关 TCP/53、223.5.5.5 TCP/53、1.1.1.1 TCP/443，跳过 HTTP 代理，通过 IP_UNICAST_IF 请求 WLAN 接口并绑定 WLAN 源地址，不修改系统路由；记录默认选路用于对照。尚未抓包验证实际出口，VPN/TUN 过滤仍可能影响结果。端口关闭或 TCP 被拦也会失败，TCP 成功不证明网页、DNS 查询或 Tailscale 正常。探测只用于记录，不参与恢复决策。
- Clash 应用 `logs/latest.log` 的摘要只统计最近五分钟的 WARN、ERROR 和已识别的 WebSocket 重置，不复制日志正文或节点信息。它不证明代理节点是否切换；节点变化需另行核实可用的实际数据源。
- 无线重连使用脚本中的 `$WifiProfile`，须在目标机以 SYSTEM 身份确认配置存在。`WlanConnect` 返回 0 只表示请求已提交，须另看无线事件及后续网络检测。
- 每轮有开始和正常退出耗时；没有结束记录只能提示中断或日志失败，不能单独断言系统挂起。退避期仍会记录 Clash 摘要，但原有网络探测和恢复动作按退避策略跳过。

## 边界

- `gamewatchdog` 只保证“模拟器在、ADB 在、LoR 进程在”；不判断游戏内 UI、不点击、不重开对局。
- LoR 客户端重启会回到 Riot 登录页，脚本会尝试 `lorwright login`；自动登录失败时只记录，不无限重试。
- 模拟器实例必须由交互式会话启动；`F1StartPie64` 使用 Administrator + Interactive，不能改成 SYSTEM。
- 默认不重启整机。
