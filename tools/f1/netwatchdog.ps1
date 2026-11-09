<#
F1 网络看门狗
================
每 2 分钟自检一次，断网时分级自救。不依赖任何外部服务，纯本地运行。

设计要点
--------
1. 健康判定必须用「真实 HTTP 请求」，不能只测 TCP 连接
   —— Clash 的 TUN 会假装接受任何 TCP 连接，TCP 通 ≠ 能上网。

2. 三项独立检测，至少两项通过才算健康：
   A. HTTP 204（真实请求，能验证整条链路）
   B. DNS 查询（验证解析链路）
   C. Tailscale 自身在线（验证远程可达性）

3. 分级升级，每级间隔 2 个检测周期（4 分钟），避免网络抖动误触发：
   L1 计数=3  重启 Clash Verge 服务（重建 TUN）
   L2 计数=5  关闭 TUN 模式（牺牲 LoR 保远程访问）
   L3 计数=7  重连 WiFi
   L4 计数=9  重启 Tailscale 服务

4. 恢复后清零计数；若 TUN 是看门狗关的，稳定 30 分钟后尝试重新开启：
   试开 60 秒，HTTP+DNS 正常就保留；不正常立即关回，并等 60 分钟再试。

5. 全部失败后退避 15 分钟，避免疯狂重启把系统搞得更乱。

部署
----
  schtasks /create /tn F1NetWatchdog /tr "powershell -NoProfile -ExecutionPolicy Bypass -File C:\Windows\Temp\netwatchdog.ps1" /sc minute /mo 2 /ru SYSTEM /rl HIGHEST /f
  schtasks /change /tn F1NetWatchdog /ri 2 /du 0001:00

日志：C:\Windows\Temp\netwatchdog.log（超 200KB 自动截断）
#>

$ErrorActionPreference = 'SilentlyContinue'

$LogFile   = 'C:\Windows\Temp\netwatchdog.log'
$StateFile = 'C:\Windows\Temp\netwatchdog.json'
$VergeYaml = 'C:\Users\Administrator\AppData\Roaming\io.github.clash-verge-rev.clash-verge-rev\verge.yaml'
$TsExe     = 'C:\Program Files\Tailscale\tailscale.exe'

# ---- 阈值（改这里就能调灵敏度）----
$FailToRestartClash = 3
$FailToDisableTun   = 5
$FailToReconnectWifi= 7
$FailToRestartTs    = 9
$BackoffMinutes     = 15
$StableMinutesForTun= 30
$TunTrialSeconds    = 60
$TunRetryMinutes    = 60

# ---------------------------------------------------------------- 工具

function Write-Log([string]$msg) {
    $line = '[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    if ((Get-Item $LogFile).Length -gt 200KB) {
        Get-Content $LogFile -Tail 300 | Set-Content $LogFile -Encoding UTF8
    }
}

function Get-State {
    $default = [ordered]@{
        fails           = 0
        tsFails         = 0
        tunDisabledByUs = $false
        tunReenableCount= 0
        stableTicks     = 0
        backoffUntil    = $null
        nextTunRetry    = $null
    }
    if (Test-Path $StateFile) {
        try {
            $raw = Get-Content $StateFile -Raw | ConvertFrom-Json
            # 必须先快照 Keys，否则边遍历边赋值会抛「集合已修改」
            $keys = @($default.Keys)
            foreach ($k in $keys) {
                if ($null -ne $raw.$k) { $default[$k] = $raw.$k }
            }
        } catch { Write-Log ("state file corrupt, reset: " + $_.Exception.Message) }
    }
    return $default
}

function Save-State($s) {
    $s | ConvertTo-Json | Set-Content $StateFile -Encoding UTF8
}

# ---------------------------------------------------------------- 健康检测

function Test-Http {
    # 用国内可达的 HTTP 端点：不依赖代理，也不受证书/TLS 版本影响
    foreach ($u in @('http://www.baidu.com',
                     'http://www.qq.com',
                     'http://connect.rom.miui.com/generate_204')) {
        try {
            $r = Invoke-WebRequest -Uri $u -TimeoutSec 6 -UseBasicParsing -ErrorAction Stop
            if ($r.StatusCode -eq 200 -or $r.StatusCode -eq 204) { return $true }
        } catch {}
    }
    return $false
}

function Test-Dns {
    # 先试系统 DNS（走路由器），再试公共 DNS
    try {
        $r = Resolve-DnsName 'www.baidu.com' -Type A -ErrorAction Stop
        if ($r) { return $true }
    } catch {}
    foreach ($srv in @('223.5.5.5', '119.29.29.29')) {
        try {
            $r = Resolve-DnsName 'www.baidu.com' -Server $srv -Type A -ErrorAction Stop
            if ($r) { return $true }
        } catch {}
    }
    return $false
}

function Test-Tailscale {
    if (-not (Test-Path $TsExe)) { return $false }
    try {
        $j = & $TsExe status --json 2>$null | ConvertFrom-Json
        return ($j.Self.Online -eq $true) -and ($j.BackendState -eq 'Running')
    } catch { return $false }
}

function Test-Healthy {
    $http = Test-Http
    $dns  = Test-Dns
    $ts   = Test-Tailscale
    $score = [int]$http + [int]$dns + [int]$ts
    Write-Log ("health: http=$http dns=$dns tailscale=$ts  score=$score/3")
    return ($score -ge 2)
}

function Test-Internet {
    # TUN 试开只要求真实 HTTP + DNS；Tailscale 掉线有单独的处理路径。
    return (Test-Http) -and (Test-Dns)
}

# ---------------------------------------------------------------- 恢复动作

function Invoke-RestartClash {
    Write-Log 'L1: restarting clash-verge service'
    Restart-Service clash_verge_service -Force
    Start-Sleep -Seconds 10
}

function Invoke-DisableTun {
    if (-not (Test-Path $VergeYaml)) { Write-Log 'L2: verge.yaml not found, skip'; return $false }
    $c = Get-Content $VergeYaml
    if ($c -match 'enable_tun_mode:\s*true') {
        ($c -replace 'enable_tun_mode:\s*true', 'enable_tun_mode: false') |
            Set-Content $VergeYaml -Encoding UTF8
        Write-Log 'L2: TUN disabled in verge.yaml'
        Restart-Service clash_verge_service -Force
        Start-Sleep -Seconds 10
        return $true
    }
    Write-Log 'L2: TUN already off'
    return $false
}

function Invoke-EnableTun {
    if (-not (Test-Path $VergeYaml)) { return $false }
    $c = Get-Content $VergeYaml
    if ($c -match 'enable_tun_mode:\s*true') { return $true }
    if ($c -match 'enable_tun_mode:\s*false') {
        ($c -replace 'enable_tun_mode:\s*false', 'enable_tun_mode: true') |
            Set-Content $VergeYaml -Encoding UTF8
        Write-Log 'TUN re-enabled after stable period'
        Restart-Service clash_verge_service -Force
        Start-Sleep -Seconds 10
        return $true
    }
    return $false
}

function Invoke-ReconnectWifi {
    Write-Log 'L3: reconnecting wifi'
    $sig = @'
using System;
using System.Runtime.InteropServices;
public class WdgWlan {
  [StructLayout(LayoutKind.Sequential)]
  public struct GUID { public uint a; public ushort b,c; [MarshalAs(UnmanagedType.ByValArray, SizeConst=8)] public byte[] d; }
  [StructLayout(LayoutKind.Sequential)]
  public struct WLAN_CONNECTION_PARAMETERS {
    public int wlanConnectionMode; [MarshalAs(UnmanagedType.LPWStr)] public string strProfile;
    public IntPtr pDot11Ssid; public IntPtr pDesiredBssidList; public int dot11BssType; public uint dwFlags;
  }
  [DllImport("wlanapi.dll")] public static extern int WlanOpenHandle(uint v, IntPtr c, out uint n, out IntPtr h);
  [DllImport("wlanapi.dll")] public static extern int WlanCloseHandle(IntPtr h, IntPtr c);
  [DllImport("wlanapi.dll")] public static extern int WlanEnumInterfaces(IntPtr h, IntPtr c, out IntPtr l);
  [DllImport("wlanapi.dll", CharSet=CharSet.Unicode)] public static extern int WlanConnect(IntPtr h, ref GUID g, ref WLAN_CONNECTION_PARAMETERS p, IntPtr r);
}
'@
    if (-not ('WdgWlan' -as [type])) { Add-Type -TypeDefinition $sig }

    $profile = (Get-NetConnectionProfile | Where-Object { $_.InterfaceAlias -eq 'WLAN' }).Name
    if (-not $profile) {
        # 断开状态下拿不到 Profile 名，退回已知的默认
        $profile = 'CU_1001_5G'
    }
    Write-Log "L3: target profile = $profile"

    $neg = 0; $h = [IntPtr]::Zero
    if ([WdgWlan]::WlanOpenHandle(2, [IntPtr]::Zero, [ref]$neg, [ref]$h) -ne 0) { return }
    $list = [IntPtr]::Zero
    if ([WdgWlan]::WlanEnumInterfaces($h, [IntPtr]::Zero, [ref]$list) -ne 0) { return }
    $count = [Runtime.InteropServices.Marshal]::ReadInt32($list)
    $base  = [IntPtr]::Add($list, 8)
    for ($i = 0; $i -lt $count; $i++) {
        # WLAN_INTERFACE_INFO = GUID(16) + WCHAR[256](512) + state(4) = 532
        $p = [IntPtr]::Add($base, $i * 532)
        $g = [Runtime.InteropServices.Marshal]::PtrToStructure($p, [Type][WdgWlan+GUID])
        $cp = New-Object WdgWlan+WLAN_CONNECTION_PARAMETERS
        $cp.wlanConnectionMode = 0
        $cp.strProfile = $profile
        $cp.dot11BssType = 1
        [WdgWlan]::WlanConnect($h, [ref]$g, [ref]$cp, [IntPtr]::Zero) | Out-Null
    }
    [WdgWlan]::WlanCloseHandle($h, [IntPtr]::Zero) | Out-Null
    Start-Sleep -Seconds 15
}

function Invoke-RestartTailscale {
    Write-Log 'L4: restarting Tailscale service'
    Restart-Service Tailscale -Force
    Start-Sleep -Seconds 10
}

# ---------------------------------------------------------------- 主流程

$state = Get-State

# 退避期内直接退出
if ($state.backoffUntil) {
    try {
        if ((Get-Date) -lt [datetime]$state.backoffUntil) {
            Write-Log "in backoff until $($state.backoffUntil), skip"
            exit 0
        }
    } catch {}
    $state['backoffUntil'] = $null
}

if (Test-Healthy) {
    if ($state.fails -gt 0) {
        Write-Log "RECOVERED after $($state.fails) consecutive failures"
    }
    $state['fails'] = 0

    # 稳定计数：只有 TUN 是我们关的才需要跟踪
    if ($state.tunDisabledByUs) {
        $state['stableTicks'] = [int]$state['stableTicks'] + 1
        if ($state.stableTicks -ge [int]($StableMinutesForTun / 2)) {
            $retryAt = $null
            if ($state.nextTunRetry) {
                try { $retryAt = [datetime]$state.nextTunRetry } catch {}
            }
            if ($retryAt -and (Get-Date) -lt $retryAt) {
                Write-Log "TUN retry waiting until $($state.nextTunRetry)"
            } else {
                $state['tunReenableCount'] = [int]$state['tunReenableCount'] + 1
                $enabled = Invoke-EnableTun
                $state['stableTicks'] = 0
                if (-not $enabled) {
                    Write-Log 'TUN trial could not enable TUN; keeping it OFF'
                    $state['nextTunRetry'] = (Get-Date).AddMinutes($TunRetryMinutes).ToString('o')
                } else {
                    Start-Sleep -Seconds $TunTrialSeconds
                    if (Test-Internet) {
                        Write-Log 'TUN trial OK; keeping TUN enabled'
                        $state['tunDisabledByUs'] = $false
                        $state['nextTunRetry'] = $null
                    } else {
                        Write-Log "TUN trial failed (attempt $($state.tunReenableCount)); disabling again"
                        Invoke-DisableTun | Out-Null
                        $state['tunDisabledByUs'] = $true
                        $state['nextTunRetry'] = (Get-Date).AddMinutes($TunRetryMinutes).ToString('o')
                    }
                }
            }
        }
    }

    # 网络通但 Tailscale 掉线 → 单独处理（不触发完整升级链）
    if (-not (Test-Tailscale)) {
        $state['tsFails'] = [int]$state['tsFails'] + 1
        Write-Log "internet OK but Tailscale offline (tsFails=$($state.tsFails))"
        if ($state.tsFails -ge 2) {
            Invoke-RestartTailscale
            $state['tsFails'] = 0
        }
    } else {
        $state['tsFails'] = 0
    }
    Save-State $state
    exit 0
}

# 不健康
$state['fails'] = [int]$state['fails'] + 1
$state['stableTicks'] = 0
Write-Log "UNHEALTHY, consecutive fails = $($state.fails)"

if ($state.fails -eq $FailToRestartClash) {
    Invoke-RestartClash
}

if ($state.fails -eq $FailToDisableTun) {
    if (Invoke-DisableTun) { $state['tunDisabledByUs'] = $true }
}

if ($state.fails -eq $FailToReconnectWifi) {
    Invoke-ReconnectWifi
}

if ($state.fails -eq $FailToRestartTs) {
    Invoke-RestartTailscale
}

if ($state.fails -ge $FailToRestartTs) {
    $state['backoffUntil'] = (Get-Date).AddMinutes($BackoffMinutes).ToString('o')
    $state['fails'] = 0
    Write-Log "ALL RECOVERY FAILED, backing off $BackoffMinutes min"
}

Save-State $state
