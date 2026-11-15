<# Remove the specifically identified historical f1 backups at the owner's request.
Default: report targets only. -Apply permanently removes the listed directories and
watchdog backup, and drops only the identified stash. Requires the current formal
checkout, its login configuration, and no active Python/lorwright processes. It does
not touch Git history, the active watchdog, or either device's current project.
There is no recovery after removal; restore from another backup if one exists.
#>
param([switch]$Apply)
$ErrorActionPreference = 'Stop'
$project = 'C:\Code\lorwright'
$targets = @(
    'C:\Code\lorwright-evidence',
    'C:\Code\lorwright-sync-backups',
    'C:\Code\lorwright-deployments',
    'C:\Windows\Temp\gamewatchdog-before-lorwright-reorg.ps1'
)
$stashHash = '2a9354a5a01e37e073c1f26cdfe7ffdfdd90116a'
if (!(Test-Path -LiteralPath (Join-Path $project '.git'))) { throw 'Formal checkout missing.' }
if (!(Test-Path -LiteralPath (Join-Path $project '.env') -PathType Leaf)) { throw 'Formal login configuration missing.' }
$head = (& git -C $project rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $head -ne '536107d25a70ad66773ab1945c5a2d11784e0057') { throw 'Unexpected formal checkout HEAD.' }
$status = @(& git -C $project status --porcelain --untracked-files=all)
if ($LASTEXITCODE -ne 0 -or $status.Count) { throw 'Formal checkout has uncommitted or untracked changes.' }
$processes = @(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(pythonw?|lorwright)(\.exe)?$' })
if ($processes.Count) { throw 'Python or lorwright process detected; inspect before cleaning.' }
foreach ($target in $targets) {
    if (Test-Path -LiteralPath $target) {
        $item = Get-Item -LiteralPath $target -Force
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Refusing reparse-point target: $target" }
        Write-Output "Target: $target"
    }
}
$stashEntries = @(& git -C $project stash list --format='%gd %H')
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect stash.' }
$matched = @($stashEntries | Where-Object { $_ -match ('^stash@\{\d+\} ' + $stashHash + '$') })
if ($matched.Count -ne 1) { throw 'Expected historical stash missing or ambiguous; refusing cleanup.' }
Write-Output "Target stash: $($matched[0])"
if (!$Apply) { Write-Output 'Preview only; nothing removed.'; return }
foreach ($target in $targets) {
    if (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Force -Recurse
        if (Test-Path -LiteralPath $target) { throw "Removal incomplete: $target" }
        Write-Output "Removed: $target"
    }
}
if ($matched.Count -eq 1) {
    $ref = ($matched[0] -split ' ')[0]
    & git -C $project stash drop $ref
    if ($LASTEXITCODE -ne 0) { throw 'Stash drop failed.' }
}
Write-Output 'Cleanup completed.'
