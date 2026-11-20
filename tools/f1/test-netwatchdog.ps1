<#
netwatchdog.ps1 的分类与动作表测试。在 f1 上运行：
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\f1\test-netwatchdog.ps1
点源加载只取函数，不执行主流程；另以 -Simulate -DryRun 跑完整脚本，核对日志且状态文件不变。
#>
$ErrorActionPreference = 'Stop'
$script = Join-Path $PSScriptRoot 'netwatchdog.ps1'
. $script
$failures = 0
function Check([string]$Name, $Actual, $Expected) {
    if ("$Actual" -ne "$Expected") { Write-Output "FAIL $Name expected=$Expected actual=$Actual"; $script:failures++ }
    else { Write-Output "ok   $Name" }
}

Check 'all up'             (Get-FailureKind $true $true $true $true) 'healthy'
Check 'gateway silent'     (Get-FailureKind $false $true $true $true) 'link'
Check 'gateway silent all' (Get-FailureKind $false $false $false $false) 'link'
Check 'wan down'           (Get-FailureKind $true $false $false $false) 'upstream'
Check 'tun http down'      (Get-FailureKind $true $true $false $true) 'proxy'
Check 'tailscale only'     (Get-FailureKind $true $true $true $false) 'tailscale'

foreach ($case in @(
    @('link', 1, 'none'), @('link', 2, 'wifi'), @('link', 3, 'none'), @('link', 4, 'none'),
    @('link', 5, 'adapter'), @('link', 8, 'wifi'), @('link', 11, 'adapter'), @('link', 30, 'none'),
    @('proxy', 2, 'clash'), @('proxy', 5, 'clash'), @('proxy', 4, 'none'),
    @('upstream', 2, 'none'), @('upstream', 5, 'none'),
    @('upstream', 8, 'backoff'), @('proxy', 9, 'backoff'), @('tailscale', 8, 'backoff')
)) {
    Check "action $($case[0]) #$($case[1])" (Get-RecoveryAction $case[0] $case[1]) $case[2]
}

$before = if (Test-Path $StateFile) { (Get-FileHash $StateFile).Hash } else { 'absent' }
foreach ($case in @(
    @('lan=0,wan=0,http=0,ts=0', 'kind=link'),
    @('lan=1,wan=1,http=0,ts=1', 'kind=proxy'),
    @('lan=1,wan=1,http=1,ts=1', 'kind=healthy')
)) {
    $mark = "simulate probes=$($case[0])"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $script -DryRun -Simulate $case[0] | Out-Null
    Check "dry-run exit $($case[0])" $LASTEXITCODE 0
    $fs = [IO.File]::Open($LogFile, 'Open', 'Read', 'ReadWrite')
    [void]$fs.Seek([Math]::Max(0, $fs.Length - 65536), 'Begin')
    $tail = (New-Object IO.StreamReader($fs)).ReadToEnd(); $fs.Close()
    $logged = $tail.LastIndexOf($mark) -ge 0 -and $tail.Substring($tail.LastIndexOf($mark)) -match [regex]::Escape($case[1])
    Check "dry-run log $($case[0])" $logged $true
}
$after = if (Test-Path $StateFile) { (Get-FileHash $StateFile).Hash } else { 'absent' }
Check 'dry-run keeps state file' $after $before

if ($failures) { Write-Output "$failures failed"; exit 1 }
Write-Output 'all passed'
