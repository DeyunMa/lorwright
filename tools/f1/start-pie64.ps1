param([switch]$DryRun)

$ErrorActionPreference = 'Continue'
$LogFile = 'C:\Windows\Temp\start-pie64.log'
$Exe = 'C:\Program Files\BlueStacks_nxt\HD-Player.exe'
$Adb = 'C:\Program Files\BlueStacks_nxt\HD-Adb.exe'

function Write-Log([string]$Message) {
    $line = '[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

$running = Get-Process HD-Player -ErrorAction SilentlyContinue
if ($running) {
    Write-Log ('already running: ' + (($running | ForEach-Object { $_.Id }) -join ','))
    exit 0
}

if ($DryRun) {
    Write-Log 'dry-run: would start Pie64'
    exit 0
}

Write-Log 'starting Pie64'
Start-Process -FilePath $Exe -ArgumentList '--instance','Pie64' -WorkingDirectory 'C:\Program Files\BlueStacks_nxt'
Start-Sleep -Seconds 25

$running = Get-Process HD-Player -ErrorAction SilentlyContinue
if (-not $running) {
    Write-Log 'failed: HD-Player did not stay alive'
    exit 1
}
Write-Log ('HD-Player alive: ' + (($running | ForEach-Object { $_.Id }) -join ','))

& $Adb start-server 2>&1 | Out-Null
foreach ($port in @(5556, 5555)) {
    & $Adb connect ("127.0.0.1:{0}" -f $port) 2>&1 | Out-Null
}
Start-Sleep -Seconds 5
$devices = & $Adb devices 2>&1
Write-Log ('adb devices: ' + (($devices -join ' | ')))
if ($devices -match '(?m)^\s*\S+\s+device\s*$') {
    exit 0
}
Write-Log 'failed: no adb device after start'
exit 2
