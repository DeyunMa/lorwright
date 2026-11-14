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
   C. Tailscale 自身在线（不证明其他设备可以连接）

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

日志：C:\Windows\Temp\netwatchdog.log，轮转文件 .1 至 .9，合计不超过 1 GB。
#>

$ErrorActionPreference = 'SilentlyContinue'

$LogFile   = 'C:\Windows\Temp\netwatchdog.log'
$StateFile = 'C:\Windows\Temp\netwatchdog.json'
$VergeYaml = 'C:\Users\Administrator\AppData\Roaming\io.github.clash-verge-rev.clash-verge-rev\verge.yaml'
$TsExe     = 'C:\Program Files\Tailscale\tailscale.exe'
$ClashLog  = 'C:\Users\Administrator\AppData\Roaming\io.github.clash-verge-rev.clash-verge-rev\logs\latest.log'
$WifiProfile = 'CU_1001_5G' # 已保存的 WLAN 配置名称，不是网络位置名称
$runTimer = [Diagnostics.Stopwatch]::StartNew()

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
    # 每段 90 MiB、共 10 段；互斥锁保护重叠的计划任务。
    $line = '[{0}] pid={1} {2}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss.fff zzz'), $PID, $msg
    if ($line.Length -gt 8192) { $line = $line.Substring(0, 8192) + ' [truncated]' }
    $bytes = [Text.Encoding]::UTF8.GetByteCount($line + [Environment]::NewLine)
    $mutex = $null
    $locked = $false
    try {
        $mutex = New-Object System.Threading.Mutex($false, 'Global\F1NetWatchdogLog') -ErrorAction Stop
        try { $locked = $mutex.WaitOne(5000) }
        catch [System.Threading.AbandonedMutexException] { $locked = $true }
        if (-not $locked) { [Console]::Error.WriteLine('netwatchdog log error: lock timeout'); return }
        if ((Test-Path $LogFile) -and ((Get-Item $LogFile).Length + $bytes -gt 90MB)) {
            for ($i = 9; $i -ge 1; $i--) {
                $source = if ($i -eq 1) { $LogFile } else { "$LogFile.$($i - 1)" }
                $target = "$LogFile.$i"
                if (Test-Path $source) { Move-Item -Path $source -Destination $target -Force -ErrorAction Stop }
            }
        }
        [IO.File]::AppendAllText($LogFile, $line + [Environment]::NewLine, (New-Object Text.UTF8Encoding($false)))
    } catch {
        [Console]::Error.WriteLine("netwatchdog log error: $($_.Exception.Message)")
    } finally {
        if ($locked -and $mutex) { try { $mutex.ReleaseMutex() } catch {} }
        if ($mutex) { try { $mutex.Dispose() } catch {} }
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
            Write-Log ("http probe endpoint=$u status=$($r.StatusCode)")
            if ($r.StatusCode -eq 200 -or $r.StatusCode -eq 204) { return $true }
        } catch {
            $ex = $_.Exception
            $innerType = if ($ex.InnerException) { $ex.InnerException.GetType().FullName } else { '' }
            Write-Log ("http probe endpoint=$u exception=$($ex.GetType().FullName) status=$($ex.Status) error=$($ex.Message) inner=$innerType innerError=$($ex.InnerException.Message)")
        }
    }
    return $false
}

function Test-Dns {
    # 先试系统 DNS（走路由器），再试公共 DNS
    try {
        $r = Resolve-DnsName 'www.baidu.com' -Type A -ErrorAction Stop
        if ($r) { Write-Log 'dns probe resolver=system result=ok'; return $true }
    } catch { Write-Log ("dns probe resolver=system error=$($_.Exception.Message)") }
    foreach ($srv in @('223.5.5.5', '119.29.29.29')) {
        try {
            $r = Resolve-DnsName 'www.baidu.com' -Server $srv -Type A -ErrorAction Stop
            if ($r) { Write-Log ("dns probe resolver=$srv result=ok"); return $true }
        } catch { Write-Log ("dns probe resolver=$srv error=$($_.Exception.Message)") }
    }
    return $false
}

function Test-Tailscale {
    if (-not (Test-Path $TsExe)) { Write-Log 'tailscale probe executable missing'; return $false }
    try {
        $j = & $TsExe status --json 2>$null | ConvertFrom-Json
        Write-Log ("tailscale probe backend=$($j.BackendState) online=$($j.Self.Online) health=$(@($j.Health) -join '|')")
        return ($j.Self.Online -eq $true) -and ($j.BackendState -eq 'Running')
    } catch { Write-Log ("tailscale probe error=$($_.Exception.Message)"); return $false }
}

function Write-NetworkDiagnostics {
    # 诊断只在探测失败时运行；所有主动探测均有限时，不参与健康判定。
    try {
        Get-NetIPInterface -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object { $_.ConnectionState -eq 'Connected' } | ForEach-Object {
                Write-Log ("diagnostic ip-interface index=$($_.InterfaceIndex) interface=$($_.InterfaceAlias) metric=$($_.InterfaceMetric) dhcp=$($_.Dhcp)")
            }
        Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction Stop | ForEach-Object {
            Write-Log ("diagnostic route-detail interface=$($_.InterfaceAlias) index=$($_.InterfaceIndex) nextHop=$($_.NextHop) routeMetric=$($_.RouteMetric) interfaceMetric=$($_.InterfaceMetric)")
        }
        $route = Find-NetRoute -RemoteIPAddress '1.1.1.1' -ErrorAction Stop | Where-Object { $_.DestinationPrefix }
        foreach ($r in $route) {
            Write-Log ("diagnostic selected-route target=1.1.1.1 interface=$($r.InterfaceAlias) index=$($r.InterfaceIndex) prefix=$($r.DestinationPrefix) nextHop=$($r.NextHop)")
        }
    } catch { Write-Log ("diagnostic route error=$($_.Exception.Message)") }
    try {
        $gateway = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction Stop |
            Where-Object { $_.InterfaceAlias -eq 'WLAN' -and $_.NextHop -ne '0.0.0.0' } | Select-Object -First 1 -ExpandProperty NextHop
        if ($gateway) {
            $source = Get-NetIPAddress -InterfaceAlias 'WLAN' -AddressFamily IPv4 -ErrorAction Stop |
                Where-Object { $_.IPAddress -notlike '169.254.*' } | Select-Object -First 1 -ExpandProperty IPAddress
            if ($source) {
                $actualRoute = Find-NetRoute -RemoteIPAddress $gateway -ErrorAction Stop | Where-Object { $_.DestinationPrefix } | Select-Object -First 1
                & ping.exe -4 -S $source -n 2 -w 1500 $gateway | Out-Null
                Write-Log ("diagnostic gateway-icmp target=$gateway source=$source selectedInterface=$($actualRoute.InterfaceAlias) exitCode=$LASTEXITCODE")
            } else { Write-Log 'diagnostic gateway-icmp result=no-wlan-ip' }
        } else { Write-Log 'diagnostic wlan-gateway-icmp result=no-gateway' }
    } catch { Write-Log ("diagnostic wlan-gateway-icmp error=$($_.Exception.Message)") }
    try {
        $stats = Get-NetAdapterStatistics -Name 'WLAN' -ErrorAction Stop
        Write-Log ("diagnostic wlan-counters received=$($stats.ReceivedBytes) sent=$($stats.SentBytes) rxErrors=$($stats.ReceivedPacketErrors) txErrors=$($stats.OutboundPacketErrors) rxDiscards=$($stats.ReceivedDiscardedPackets) txDiscards=$($stats.OutboundDiscardedPackets)")
    } catch { Write-Log ("diagnostic wlan-counters error=$($_.Exception.Message)") }
    try {
        $tun = Select-String -Path $VergeYaml -Pattern '^\s*enable_tun_mode:\s*(true|false)\s*$' -ErrorAction Stop | Select-Object -First 1
        if ($tun) { Write-Log ("diagnostic configured-tun=$($tun.Matches[0].Groups[1].Value)") }
        else { Write-Log 'diagnostic configured-tun=unknown' }
    } catch { Write-Log ("diagnostic configured-tun error=$($_.Exception.Message)") }
}

function Write-WlanEvents {
    # 无线短暂断开可能发生在两次健康检查之间；每次检查都读取关键事件。
    try {
        $since = (Get-Date).AddMinutes(-5)
        $events = Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-WLAN-AutoConfig/Operational'; StartTime=$since; Id=11006,8001,8002,8003} -MaxEvents 30 -ErrorAction Stop
        foreach ($event in $events) {
            $xml = [xml]$event.ToXml()
            $fields = @()
            foreach ($field in $xml.Event.EventData.Data) {
                if ($field.Name -in @('ReasonCode', 'ReasonText', 'Reason', 'ErrorCode')) {
                    $fields += ("$($field.Name)=$($field.'#text')")
                }
                if ($field.Name -in @('PhyType', 'Dot11PhyType', 'AuthenticationAlgorithm', 'AuthAlgorithm', 'CipherAlgorithm', 'SecurityHintCode', 'OneXEnabled')) {
                    $fields += ("$($field.Name)=$($field.'#text')")
                }
            }
            Write-Log ("wlan-event time=$($event.TimeCreated.ToString('o')) id=$($event.Id) $($fields -join ' ')")
        }
    } catch { Write-Log ("wlan-events result=$($_.Exception.Message)") }
}

function Write-WifiSnapshot {
    try {
        $previousEncoding = [Console]::OutputEncoding
        try {
            [Console]::OutputEncoding = [Text.Encoding]::UTF8
            $lines = & netsh.exe wlan show interfaces 2>&1
        } finally { [Console]::OutputEncoding = $previousEncoding }
        if ($LASTEXITCODE -ne 0) { Write-Log ("wifi snapshot netshExit=$LASTEXITCODE"); return }
        $matched = 0
        foreach ($line in $lines) {
            if ($line -match '^\s*(State|状态|狀態|Signal|信号|訊號|Rssi|Band|波段|Channel|信道|頻道|频道|Radio type|无线电类型|無線電類型|Receive rate.*Mbps.*|Transmit rate.*Mbps.*|接收速率.*Mbps.*|传输速率.*Mbps.*|傳輸速率.*Mbps.*)\s*:\s*(.+?)\s*$') {
                $field = $Matches[1]; $value = $Matches[2]
                Write-Log ("wifi snapshot field=$field value=$value")
                $matched++
            }
        }
        if ($matched -eq 0) { Write-Log 'wifi snapshot result=no-recognized-fields' }
        $adapter = Get-NetAdapter -Name WLAN -ErrorAction Stop
        Write-Log ("wifi snapshot adapterStatus=$($adapter.Status) link=$($adapter.LinkSpeed)")
    } catch { Write-Log ("wifi snapshot error=$($_.Exception.Message)") }
}

function Write-ClashLogSummary {
    # 只记录最近五分钟的分类计数，不复制日志正文、节点名、域名或凭据。
    try {
        if (-not (Test-Path -LiteralPath $ClashLog)) { Write-Log 'clash-log result=missing'; return }
        $file = Get-Item -LiteralPath $ClashLog -ErrorAction Stop
        $share = [IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete
        $stream = [IO.File]::Open($ClashLog, [IO.FileMode]::Open, [IO.FileAccess]::Read, $share)
        try {
            $offset = [Math]::Max(0, $stream.Length - 262144)
            [void]$stream.Seek($offset, [IO.SeekOrigin]::Begin)
            $reader = New-Object IO.StreamReader($stream, [Text.Encoding]::UTF8, $true)
            try {
                if ($offset -gt 0) { [void]$reader.ReadLine() }
                $since = (Get-Date).AddMinutes(-5); $warn = 0; $err = 0; $reset = 0; $lastReset = ''
                while ($null -ne ($line = $reader.ReadLine())) {
                    if ($line -notmatch '^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)\]\s+(WARN|ERROR)\s+(.*)$') { continue }
                    $eventTime = [datetime]::MinValue
                    if (-not [datetime]::TryParseExact($Matches[1], 'yyyy-MM-dd HH:mm:ss.fff', [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::None, [ref]$eventTime)) { continue }
                    $level = $Matches[2]; $message = $Matches[3]
                    if ($eventTime -lt $since -or $eventTime -gt (Get-Date).AddMinutes(1)) { continue }
                    if ($level -eq 'WARN') { $warn++ } else { $err++ }
                    if ($message -match '^websocket error: WebSocket protocol error: Connection reset without closing handshake') { $reset++; $lastReset = $eventTime.ToString('o') }
                }
            } finally { $reader.Dispose() }
        } finally { $stream.Dispose() }
        Write-Log ("clash-log windowMinutes=5 warn=$warn error=$err websocketReset=$reset lastWebsocketReset=$lastReset fileModified=$($file.LastWriteTime.ToString('o')) tailBytes=262144")
    } catch { Write-Log ("clash-log result=read-error type=$($_.Exception.GetType().Name)") }
}

function Write-DirectProbe([string]$label, [string]$target, [int]$port, [string]$source, [int]$interfaceIndex) {
    $client = $null
    $async = $null
    $timer = [Diagnostics.Stopwatch]::StartNew()
    try {
        $route = Find-NetRoute -RemoteIPAddress $target -ErrorAction Stop | Where-Object { $_.DestinationPrefix } | Select-Object -First 1
        $client = New-Object System.Net.Sockets.TcpClient([Net.Sockets.AddressFamily]::InterNetwork)
        # IP_UNICAST_IF (31) 要求网络字节序的接口索引；不修改系统路由。
        $networkIndex = [Net.IPAddress]::HostToNetworkOrder($interfaceIndex)
        $client.Client.SetSocketOption([Net.Sockets.SocketOptionLevel]::IP, 31, $networkIndex)
        $client.Client.Bind((New-Object Net.IPEndPoint([Net.IPAddress]::Parse($source), 0)))
        $async = $client.BeginConnect($target, $port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne(3000)) {
            Write-Log ("direct-probe label=$label target=$target port=$port source=$source requestedInterface=WLAN index=$interfaceIndex defaultRoute=$($route.InterfaceAlias) result=timeout elapsedMs=$($timer.ElapsedMilliseconds)")
            return
        }
        $client.EndConnect($async)
        Write-Log ("direct-probe label=$label target=$target port=$port source=$source requestedInterface=WLAN index=$interfaceIndex defaultRoute=$($route.InterfaceAlias) result=connected elapsedMs=$($timer.ElapsedMilliseconds)")
    } catch {
        $ex = $_.Exception
        if ($ex.InnerException) { $ex = $ex.InnerException }
        Write-Log ("direct-probe label=$label target=$target port=$port source=$source requestedInterface=WLAN index=$interfaceIndex defaultRoute=$($route.InterfaceAlias) result=error type=$($ex.GetType().Name) socketCode=$($ex.SocketErrorCode) elapsedMs=$($timer.ElapsedMilliseconds)")
    } finally {
        if ($client) { $client.Close() }
        if ($async) { $async.AsyncWaitHandle.Close() }
    }
}

function Write-DirectProbes {
    # 绕过 HTTP 代理，按 WLAN 接口发起连接；不修改系统路由。
    try {
        $adapter = Get-NetAdapter -Name 'WLAN' -ErrorAction Stop
        $interfaceIndex = [int]$adapter.ifIndex
        $source = Get-NetIPAddress -InterfaceIndex $interfaceIndex -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object { $_.IPAddress -notlike '169.254.*' -and $_.AddressState -eq 'Preferred' -and -not $_.SkipAsSource } | Select-Object -First 1 -ExpandProperty IPAddress
        $gateway = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction Stop |
            Where-Object { $_.InterfaceAlias -eq 'WLAN' -and $_.NextHop -ne '0.0.0.0' } | Select-Object -First 1 -ExpandProperty NextHop
        if (-not $source) { Write-Log 'direct-probe result=no-wlan-ip'; return }
        if ($gateway) { Write-DirectProbe 'gateway' $gateway 53 $source $interfaceIndex }
        else { Write-Log 'direct-probe label=gateway result=no-gateway' }
        Write-DirectProbe 'internet-dns' '223.5.5.5' 53 $source $interfaceIndex
        Write-DirectProbe 'internet-https' '1.1.1.1' 443 $source $interfaceIndex
    } catch { Write-Log ("direct-probe result=setup-error type=$($_.Exception.GetType().Name)") }
}

function Test-Healthy {
    Write-WlanEvents
    Write-WifiSnapshot
    Write-DirectProbes
    $http = Test-Http
    $dns  = Test-Dns
    $ts   = Test-Tailscale
    $score = [int]$http + [int]$dns + [int]$ts
    Write-Log ("health: http=$http dns=$dns tailscale=$ts  score=$score/3")
    if (-not $http -or -not $dns -or -not $ts) {
        Write-NetworkDiagnostics
        foreach ($service in @('Tailscale', 'clash_verge_service')) {
            $svc = Get-Service -Name $service -ErrorAction SilentlyContinue
            Write-Log ("diagnostic service=$service status=$($svc.Status)")
        }
        Get-NetAdapter -ErrorAction SilentlyContinue | ForEach-Object {
            Write-Log ("diagnostic adapter=$($_.Name) status=$($_.Status) link=$($_.LinkSpeed)")
        }
        Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | ForEach-Object {
            Write-Log ("diagnostic default-route interface=$($_.InterfaceAlias) metric=$($_.RouteMetric) state=$($_.State)")
        }
        try {
            $boot = (Get-CimInstance Win32_OperatingSystem -ErrorAction Stop).LastBootUpTime
            Write-Log ("diagnostic last-boot=$($boot.ToString('o'))")
        } catch { Write-Log ("diagnostic boot-time error=$($_.Exception.Message)") }
        try {
            $since = (Get-Date).AddMinutes(-5)
            $events = Get-WinEvent -FilterHashtable @{LogName='System'; StartTime=$since; Level=1,2,3} -MaxEvents 20 -ErrorAction Stop
            foreach ($event in $events) {
                Write-Log ("diagnostic system-event time=$($event.TimeCreated.ToString('o')) provider=$($event.ProviderName) id=$($event.Id) level=$($event.Level)")
            }
        } catch { Write-Log ("diagnostic system-events result=$($_.Exception.Message)") }
    }
    return ($score -ge 2)
}

function Test-Internet {
    # TUN 试开只要求真实 HTTP + DNS；Tailscale 掉线有单独的处理路径。
    return (Test-Http) -and (Test-Dns)
}

# ---------------------------------------------------------------- 恢复动作

function Invoke-RestartClash {
    Write-Log 'L1: restarting clash-verge service'
    try {
        Restart-Service clash_verge_service -Force -ErrorAction Stop
        Write-Log ("L1: clash restart result=ok status=$((Get-Service clash_verge_service).Status)")
    } catch { Write-Log ("L1: clash restart error=$($_.Exception.Message)") }
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
    param([switch]$DryRun)
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
  [DllImport("wlanapi.dll")] public static extern int WlanGetProfileList(IntPtr h, ref GUID g, IntPtr r, out IntPtr l);
  [DllImport("wlanapi.dll")] public static extern void WlanFreeMemory(IntPtr p);
  [DllImport("wlanapi.dll", CharSet=CharSet.Unicode)] public static extern int WlanConnect(IntPtr h, ref GUID g, ref WLAN_CONNECTION_PARAMETERS p, IntPtr r);
}
'@
    if (-not ('WdgWlan' -as [type])) { Add-Type -TypeDefinition $sig }

    [uint32]$neg = 0; $h = [IntPtr]::Zero; $list = [IntPtr]::Zero; $profiles = [IntPtr]::Zero
    try {
        $adapter = Get-NetAdapter -Name 'WLAN' -ErrorAction Stop
        $targetGuid = [Guid]$adapter.InterfaceGuid
        $openResult = [WdgWlan]::WlanOpenHandle(2, [IntPtr]::Zero, [ref]$neg, [ref]$h)
        if ($openResult -ne 0) { Write-Log "L3: WlanOpenHandle result=$openResult"; return }
        $enumResult = [WdgWlan]::WlanEnumInterfaces($h, [IntPtr]::Zero, [ref]$list)
        if ($enumResult -ne 0) { Write-Log "L3: WlanEnumInterfaces result=$enumResult"; return }
        $count = [Runtime.InteropServices.Marshal]::ReadInt32($list)
        $found = $false
        for ($i = 0; $i -lt $count; $i++) {
            $p = [IntPtr]::Add($list, 8 + $i * 532)
            $nativeGuid = [Runtime.InteropServices.Marshal]::PtrToStructure($p, [Type][Guid])
            if ($nativeGuid -ne $targetGuid) { continue }
            $found = $true
            $g = [Runtime.InteropServices.Marshal]::PtrToStructure($p, [Type][WdgWlan+GUID])
            $profileResult = [WdgWlan]::WlanGetProfileList($h, [ref]$g, [IntPtr]::Zero, [ref]$profiles)
            if ($profileResult -ne 0) { Write-Log "L3: WlanGetProfileList result=$profileResult"; return }
            $profileCount = [Runtime.InteropServices.Marshal]::ReadInt32($profiles)
            $present = $false
            for ($j = 0; $j -lt $profileCount; $j++) {
                $item = [IntPtr]::Add($profiles, 8 + $j * 516)
                $name = [Runtime.InteropServices.Marshal]::PtrToStringUni($item)
                if ($name -eq $WifiProfile) { $present = $true; break }
            }
            if (-not $present) { Write-Log "L3: configured WLAN profile missing; skip profile=$WifiProfile"; return }
            Write-Log "L3: connecting interface=WLAN profile=$WifiProfile"
            if ($DryRun) { Write-Log 'L3: dry-run profile and interface verified; no connection requested'; return }
            $cp = New-Object WdgWlan+WLAN_CONNECTION_PARAMETERS
            $cp.wlanConnectionMode = 0; $cp.strProfile = $WifiProfile; $cp.dot11BssType = 1
            $connectResult = [WdgWlan]::WlanConnect($h, [ref]$g, [ref]$cp, [IntPtr]::Zero)
            Write-Log "L3: WlanConnect accepted=$($connectResult -eq 0) result=$connectResult (asynchronous)"
            if ($connectResult -eq 0) { Start-Sleep -Seconds 15; Write-WifiSnapshot }
            break
        }
        if (-not $found) { Write-Log 'L3: WLAN interface not found in WLAN API; skip' }
    } catch { Write-Log ("L3: reconnect error=$($_.Exception.Message)") }
    finally {
        if ($profiles -ne [IntPtr]::Zero) { [WdgWlan]::WlanFreeMemory($profiles) }
        if ($list -ne [IntPtr]::Zero) { [WdgWlan]::WlanFreeMemory($list) }
        if ($h -ne [IntPtr]::Zero) { [WdgWlan]::WlanCloseHandle($h, [IntPtr]::Zero) | Out-Null }
    }
}

function Invoke-RestartTailscale {
    Write-Log 'L4: restarting Tailscale service'
    try {
        Restart-Service Tailscale -Force -ErrorAction Stop
        Write-Log ("L4: Tailscale restart result=ok status=$((Get-Service Tailscale).Status)")
    } catch { Write-Log ("L4: Tailscale restart error=$($_.Exception.Message)") }
    Start-Sleep -Seconds 10
}

# ---------------------------------------------------------------- 主流程

$state = Get-State
Write-Log ("start state=$($state | ConvertTo-Json -Compress)")
Write-ClashLogSummary

# 退避期内直接退出
if ($state.backoffUntil) {
    try {
        if ((Get-Date) -lt [datetime]$state.backoffUntil) {
            Write-Log "in backoff until $($state.backoffUntil), skip"
            Write-Log "end result=backoff elapsedMs=$($runTimer.ElapsedMilliseconds)"
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
    Write-Log "end result=healthy elapsedMs=$($runTimer.ElapsedMilliseconds)"
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
Write-Log "end result=unhealthy elapsedMs=$($runTimer.ElapsedMilliseconds)"
