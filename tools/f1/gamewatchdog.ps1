param([switch]$DryRun)

$ErrorActionPreference = 'Continue'
$LogFile = 'C:\Windows\Temp\gamewatchdog.log'
$StateFile = 'C:\Windows\Temp\gamewatchdog.json'
$NetStateFile = 'C:\Windows\Temp\netwatchdog.json'
$Adb = 'C:\Program Files\BlueStacks_nxt\HD-Adb.exe'
$Lorwright = 'C:\Code\lorwright\.venv\Scripts\lorwright.exe'
$Project = 'C:\Code\lorwright'
$Package = 'com.riotgames.legendsofruneterra'
$StartTask = 'F1StartPie64'

$StartEmulatorAfter = 2
$RestartEmulatorAfter = 6
$RestartAppAfter = 3

function Write-Log([string]$Message) {
    $line = '[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    if ((Test-Path $LogFile) -and (Get-Item $LogFile).Length -gt 200KB) {
        Get-Content $LogFile -Tail 300 | Set-Content $LogFile -Encoding UTF8
    }
}

function Get-State {
    $default = [ordered]@{
        noPlayer = 0
        adbFails = 0
        gameFails = 0
        backoffUntil = $null
        lastAction = ''
    }
    if (Test-Path $StateFile) {
        try {
            $raw = Get-Content $StateFile -Raw | ConvertFrom-Json
            foreach ($k in @($default.Keys)) {
                if ($null -ne $raw.$k) { $default[$k] = $raw.$k }
            }
        } catch {
            Write-Log ('state corrupt, reset: ' + $_.Exception.Message)
        }
    }
    return $default
}

function Save-State($s) {
    $s | ConvertTo-Json | Set-Content $StateFile -Encoding UTF8
}

function Get-AdbDevice {
    & $Adb start-server 2>&1 | Out-Null
    $devices = & $Adb devices 2>&1
    $match = $devices | Select-String -Pattern '(?m)^\s*(\S+)\s+device\s*$'
    if ($match) { return $match.Matches[0].Groups[1].Value }
    foreach ($port in @(5556, 5555)) {
        & $Adb connect ("127.0.0.1:{0}" -f $port) 2>&1 | Out-Null
    }
    Start-Sleep -Seconds 3
    $devices = & $Adb devices 2>&1
    $match = $devices | Select-String -Pattern '(?m)^\s*(\S+)\s+device\s*$'
    if ($match) { return $match.Matches[0].Groups[1].Value }
    return $null
}

function Restart-AdbServer {
    Write-Log 'restarting adb server'
    & $Adb kill-server 2>&1 | Out-Null
    Start-Sleep -Seconds 2
    & $Adb start-server 2>&1 | Out-Null
}

function Start-Pie64 {
    Write-Log "running scheduled task $StartTask"
    & schtasks /run /tn $StartTask 2>&1 | Out-Null
}

function Restart-Emulator {
    Write-Log 'outermost: restarting BlueStacks Pie64'
    Get-Process HD-Player -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 5
    Start-Pie64
}

function Restart-LorApp($serial) {
    Write-Log 'restarting LoR app'
    & $Adb -s $serial shell am force-stop $Package 2>&1 | Out-Null
    Start-Sleep -Seconds 2
    Push-Location $Project
    try {
        & $Lorwright launch 2>&1 | ForEach-Object { Write-Log ('lorwright launch: ' + $_) }
    } finally { Pop-Location }
    Start-Sleep -Seconds 5
    Push-Location $Project
    try {
        & $Lorwright login 2>&1 | ForEach-Object { Write-Log ('lorwright login: ' + $_) }
    } finally { Pop-Location }
}

$state = Get-State

if ($state.backoffUntil) {
    try {
        if ((Get-Date) -lt [datetime]$state.backoffUntil) {
            Write-Log "in backoff until $($state.backoffUntil), skip"
            exit 0
        }
    } catch {}
    $state['backoffUntil'] = $null
}

# 活跃退避按明确的截止时间计算。故障计数只在最近三次计划周期内有效。
if (Test-Path $NetStateFile) {
    try {
        $netFile = Get-Item -LiteralPath $NetStateFile -ErrorAction Stop
        $net = Get-Content -LiteralPath $NetStateFile -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
        $now = Get-Date
        if ($net.backoffUntil -and $now -lt [datetime]$net.backoffUntil) {
            Write-Log "network watchdog backoff until $($net.backoffUntil), skip game actions"
            exit 0
        }
        if ($net.fails -ge 2) {
            $age = $now.ToUniversalTime() - $netFile.LastWriteTimeUtc
            if ($age.TotalMinutes -ge 0 -and $age.TotalMinutes -lt 6) {
                Write-Log "network watchdog fails=$($net.fails), skip game actions"
                exit 0
            }
            Write-Log ('network watchdog failure count expired, ageSeconds={0:N0}' -f $age.TotalSeconds)
        }
    } catch {
        Write-Log ('network watchdog state unreadable: ' + $_.Exception.Message)
    }
}

$player = Get-Process HD-Player -ErrorAction SilentlyContinue
if ($DryRun) {
    Write-Log "dry-run: emulatorPresent=$([bool]$player); skip ADB checks and recovery"
    exit 0
}
if (-not $player) {
    $state['noPlayer'] = [int]$state['noPlayer'] + 1
    Write-Log "no HD-Player process (count=$($state.noPlayer))"
    if ($state.noPlayer -ge $StartEmulatorAfter) {
        Start-Pie64
        $state['noPlayer'] = 0
        $state['lastAction'] = 'start-emulator'
        $state['backoffUntil'] = (Get-Date).AddMinutes(5).ToString('o')
    }
    Save-State $state
    exit 0
}
$state['noPlayer'] = 0

$serial = Get-AdbDevice
if (-not $serial) {
    $state['adbFails'] = [int]$state['adbFails'] + 1
    Write-Log "no adb device (count=$($state.adbFails))"
    if ($state.adbFails -eq 2) { Restart-AdbServer }
    if ($state.adbFails -ge $RestartEmulatorAfter) {
        Restart-Emulator
        $state['adbFails'] = 0
        $state['lastAction'] = 'restart-emulator-adb'
        $state['backoffUntil'] = (Get-Date).AddMinutes(10).ToString('o')
    }
    Save-State $state
    exit 0
}
$state['adbFails'] = 0

$gamePid = (& $Adb -s $serial shell pidof $Package 2>&1 | Out-String).Trim()
$probeExit = $LASTEXITCODE
# adb 断连的错误文字不是进程号，也不能当成游戏已经退出。
if (($gamePid -and ($probeExit -ne 0 -or $gamePid -notmatch '^\d+(?:\s+\d+)*$')) -or $probeExit -gt 1) {
    Write-Log "LoR process probe failed (adb exit=$probeExit), skip game recovery"
    Save-State $state
    exit 1
}
if (-not $gamePid) {
    $state['gameFails'] = [int]$state['gameFails'] + 1
    Write-Log "LoR process missing (count=$($state.gameFails))"
    if ($state.gameFails -eq 1 -or $state.gameFails -eq 2) {
        Push-Location $Project
        try {
            & $Lorwright launch 2>&1 | ForEach-Object { Write-Log ('lorwright launch: ' + $_) }
        } finally { Pop-Location }
    }
    if ($state.gameFails -ge $RestartAppAfter) {
        Restart-LorApp $serial
        $state['gameFails'] = 0
        $state['lastAction'] = 'restart-app'
        $state['backoffUntil'] = (Get-Date).AddMinutes(5).ToString('o')
    }
    Save-State $state
    exit 0
}

$state['gameFails'] = 0
$state['lastAction'] = 'healthy'
Write-Log "healthy: serial=$serial pid=$gamePid"
Save-State $state
