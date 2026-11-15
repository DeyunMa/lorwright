# Update the existing f1 checkout from a previously copied Git bundle.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Bundle,
    [switch]$Apply
)
$ErrorActionPreference = 'Stop'
$env:GIT_OPTIONAL_LOCKS = '0'
$project = 'C:\Code\lorwright'

function Git([string[]]$GitArgs) {
    # Git writes normal progress to stderr; Windows PowerShell can treat it as an error.
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = @(& git.exe -C $project @GitArgs 2>&1)
        $exitCode = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previousPreference }
    if ($exitCode -ne 0) { throw "Git command failed: $($GitArgs[0]); inspect the checkout before retrying." }
    return @($output | Where-Object { $_ -isnot [System.Management.Automation.ErrorRecord] })
}
function Assert-NoSession {
    # Conservative: a Python process may be running a session from any deployment.
    $processes = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
        $_.Name -match '^(pythonw?|lorwright)(\.exe)?$'
    })
    if ($processes.Count) { throw 'Python or lorwright process detected; stop and verify all sessions before updating.' }
    $roots = @((Join-Path $project 'logs\runs'))
    if ($env:LORWRIGHT_RUNS_DIR) { $roots += [IO.Path]::GetFullPath($env:LORWRIGHT_RUNS_DIR) }
    foreach ($root in ($roots | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $root)) { continue }
        foreach ($file in @(Get-ChildItem -LiteralPath $root -Filter status.json -File -Recurse -ErrorAction Stop)) {
            $state = Get-Content -LiteralPath $file.FullName -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
            if ($state.status -notin @('stopped', 'cancelled', 'failed', 'completed')) {
                throw "Nonterminal or invalid session record: $($file.FullName); inspect it before updating."
            }
        }
    }
}

if (-not (Test-Path -LiteralPath (Join-Path $project '.git'))) { throw 'Expected Git checkout is missing.' }
$bundlePath = (Resolve-Path -LiteralPath $Bundle -ErrorAction Stop).ProviderPath
if (-not (Test-Path -LiteralPath $bundlePath -PathType Leaf)) { throw 'Bundle must be a file.' }
$branch = (Git @('branch', '--show-current') | Out-String).Trim()
if ($branch -ne 'main') { throw 'Checkout must be on main.' }
$head = (Git @('rev-parse', 'HEAD') | Out-String).Trim()
$status = @(Git @('status', '--porcelain=v1', '--untracked-files=all'))
$null = Git @('bundle', 'verify', $bundlePath)
$heads = @(Git @('bundle', 'list-heads', $bundlePath, 'refs/heads/main'))
if ($heads.Count -ne 1 -or $heads[0] -notmatch '^([0-9a-fA-F]{40,64})\s+refs/heads/main$') {
    throw 'Bundle must contain exactly one refs/heads/main.'
}
$target = $Matches[1].ToLowerInvariant()
Assert-NoSession
Write-Output "Checkout HEAD: $head"
Write-Output "Bundle main: $target"
Write-Output "Changed status entries: $($status.Count)"
if (-not $Apply) {
    Write-Output 'Dry run: bundle verified; ancestry and merge feasibility will be checked on apply. No checkout changes made.'
    return
}

if ($head -eq $target) {
    Write-Output 'Already at bundle main; working tree and stashes left untouched.'
    return
}
# FETCH_HEAD is deliberately used without moving any local branch.
$null = Git @('fetch', '--no-tags', $bundlePath, 'refs/heads/main')
$fetched = (Git @('rev-parse', 'FETCH_HEAD') | Out-String).Trim()
if ($fetched -ne $target) { throw 'Fetched commit does not match bundle main.' }
& git.exe -C $project merge-base --is-ancestor $head $target
if ($LASTEXITCODE -ne 0) { throw 'Current HEAD is not an ancestor of bundle main; checkout was not stashed or merged.' }
Assert-NoSession
$status = @(Git @('status', '--porcelain=v1', '--untracked-files=all'))
if ($status.Count -gt 0) {
    $marker = 'f1-update-' + [Guid]::NewGuid().ToString('N')
    $null = Git @('stash', 'push', '--include-untracked', '-m', $marker)
    $stash = (Git @('rev-parse', 'refs/stash') | Out-String).Trim()
    Write-Output "Saved tracked and untracked changes in stash $stash ($marker)."
}
$remaining = @(Git @('status', '--porcelain=v1', '--untracked-files=all'))
if ($remaining.Count -gt 0) { throw 'Working tree is not clean after stash; inspect it and the retained stash.' }
Assert-NoSession
$null = Git @('merge', '--ff-only', 'FETCH_HEAD')
$final = (Git @('rev-parse', 'HEAD') | Out-String).Trim()
if ($final -ne $target) { throw 'Final HEAD differs from bundle main; inspect the checkout.' }
Write-Output "Updated main to $final. Existing stashes and ignored files remain in place."
