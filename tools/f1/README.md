# F1 运维脚本

这三个脚本是 f1 上的独立兜底，不参与 `lorwright` 的游戏内决策。

| 脚本 | 计划任务 | 运行身份 | 职责 |
|---|---|---|---|
| `netwatchdog.ps1` | `F1NetWatchdog`，每 2 分钟 | SYSTEM | HTTP/DNS/Tailscale 健康检查；Clash/TUN/WiFi/Tailscale 分级恢复 |
| `gamewatchdog.ps1` | `F1GameWatchdog`，每 5 分钟 | SYSTEM | 模拟器进程、ADB、LoR 进程的最外层恢复 |
| `start-pie64.ps1` | `F1StartPie64`，手动/被调用 | Administrator + Interactive | 在交互式桌面启动 Pie64；已在跑时只记日志 |

## 部署

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

## 边界

- `gamewatchdog` 只保证“模拟器在、ADB 在、LoR 进程在”；不判断游戏内 UI、不点击、不重开对局。
- LoR 客户端重启会回到 Riot 登录页，脚本会尝试 `lorwright login`；自动登录失败时只记录，不无限重试。
- 模拟器实例必须由交互式会话启动；`F1StartPie64` 使用 Administrator + Interactive，不能改成 SYSTEM。
- 默认不重启整机。
