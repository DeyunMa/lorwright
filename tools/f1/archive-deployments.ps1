<#
Archive old isolated deployments on f1. Never touches C:\Code\lorwright.

Run from a PowerShell session on f1, with automation and watchdogs stopped:
  powershell -NoProfile -File archive-deployments.ps1 -Mode Preview
  powershell -NoProfile -File archive-deployments.ps1 -Mode Archive -Batch review-20261115
  powershell -NoProfile -File archive-deployments.ps1 -Mode Cleanup -Batch review-20261115 -ConfirmRemoval

Preview performs no writes. Archive copies the entire eligible directory, including
ignored and unmanifested files, into a new per-deployment target; it verifies all
file hashes and directory names. Existing targets are never overwritten. Cleanup
is a separate, explicitly confirmed operation, rechecks the manifest and compares
all source and archive files and directories immediately before removal. A partial
archive is retained and must be investigated manually; it is never overwritten.
Every deployment containing .env, .git, or a reparse point is skipped in full.
A missing, invalid, or mismatched manifest also skips the entire deployment.
Only direct children named f1-* are candidates. No secrets are printed.

Restore: after ensuring the original path is absent, copy the desired directory
from C:\Code\lorwright-evidence\<batch> to C:\Code\lorwright-deployments;
compare file hashes before use. Archives may contain private data; protect them.
Stop all writers before either mutation: filesystem checks are not an atomic lock.
#>
param(
    [ValidateSet('Preview', 'Archive', 'Cleanup')][string]$Mode = 'Preview',
    [string]$Batch,
    [switch]$ConfirmRemoval
)
$ErrorActionPreference = 'Stop'
$sourceRoot = 'C:\Code\lorwright-deployments'
$evidenceRoot = 'C:\Code\lorwright-evidence'
if ($Mode -ne 'Preview' -and $Batch -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$') {
    throw 'Archive and Cleanup require a simple -Batch name.'
}
if ($Mode -eq 'Cleanup' -and !$ConfirmRemoval) { throw 'Cleanup requires -ConfirmRemoval.' }

function Assert-PlainDirectory([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force
    if (!$item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Root is not a plain directory.'
    }
}

# Walk explicitly so a link is rejected before anything can recurse through it.
function Get-Inventory([string]$Root) {
    Assert-PlainDirectory $Root
    $items = @{}
    $pending = [Collections.Generic.Stack[string]]::new()
    $pending.Push($Root)
    while ($pending.Count -gt 0) {
        $parent = $pending.Pop()
        foreach ($item in @(Get-ChildItem -LiteralPath $parent -Force)) {
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse point found.' }
            if ($item.Name -ieq '.env' -or $item.Name -ieq '.git') { throw 'Protected .env or .git found.' }
            $relative = $item.FullName.Substring($Root.Length).TrimStart('\').Replace('\', '/')
            if ($items.ContainsKey($relative)) { throw 'Duplicate case-insensitive path.' }
            if ($item.PSIsContainer) {
                $items[$relative] = 'directory'
                $pending.Push($item.FullName)
            } else {
                $items[$relative] = (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash
            }
        }
    }
    return ,$items
}

function Assert-Manifest([string]$Root, [hashtable]$Inventory) {
    if (!$Inventory.ContainsKey('deploy-manifest.json') -or $Inventory['deploy-manifest.json'] -eq 'directory') {
        throw 'Manifest missing.'
    }
    $entries = Get-Content -LiteralPath (Join-Path $Root 'deploy-manifest.json') -Raw | ConvertFrom-Json
    if ($entries.Count -eq 0) { throw 'Empty manifest.' }
    $seen = @{}
    foreach ($entry in $entries) {
        $name = [string]$entry.path
        $hash = [string]$entry.sha256
        if ($name -notmatch '^[^\\:]+$' -or $name.StartsWith('/') -or
            @($name.Split('/') | Where-Object { $_ -eq '' -or $_ -eq '.' -or $_ -eq '..' }).Count -gt 0 -or
            $hash -notmatch '^[0-9a-fA-F]{64}$' -or $seen.ContainsKey($name)) {
            throw 'Invalid manifest entry.'
        }
        $seen[$name] = $true
        if (!$Inventory.ContainsKey($name) -or $Inventory[$name] -ne $hash) { throw 'Manifest mismatch.' }
    }
}

function Assert-Equal([hashtable]$Left, [hashtable]$Right) {
    if ($Left.Count -ne $Right.Count) { throw 'Inventory count differs.' }
    foreach ($key in $Left.Keys) {
        if (!$Right.ContainsKey($key) -or $Left[$key] -ne $Right[$key]) { throw 'Inventory differs.' }
    }
}

Assert-PlainDirectory $sourceRoot
if (Test-Path -LiteralPath $evidenceRoot) { Assert-PlainDirectory $evidenceRoot }
$batchRoot = if ($Batch) { Join-Path $evidenceRoot $Batch } else { $null }
if ($Mode -eq 'Cleanup') { Assert-PlainDirectory $batchRoot }
if ($Mode -eq 'Archive' -and (Test-Path -LiteralPath $batchRoot)) {
    throw 'Batch target already exists; choose a new name.'
}
if ($Mode -eq 'Archive') {
    if (!(Test-Path -LiteralPath $evidenceRoot)) { New-Item -ItemType Directory -Path $evidenceRoot | Out-Null }
    New-Item -ItemType Directory -Path $batchRoot | Out-Null
}
foreach ($deployment in @(Get-ChildItem -LiteralPath $sourceRoot -Force | Where-Object { $_.Name -like 'f1-*' })) {
    try {
        $root = $deployment.FullName
        $inventory = Get-Inventory $root
        Assert-Manifest $root $inventory
        if ($Mode -eq 'Preview') {
            Write-Output ("ELIGIBLE {0}: {1} entries" -f $deployment.Name, $inventory.Count)
            continue
        }
        $target = Join-Path $batchRoot $deployment.Name
        if ($Mode -eq 'Archive') {
            if (Test-Path -LiteralPath $target) { throw 'Target already exists.' }
            New-Item -ItemType Directory -Path $target | Out-Null
            foreach ($key in @($inventory.Keys | Sort-Object { $_.Length })) {
                $destination = Join-Path $target $key.Replace('/', '\')
                if ($inventory[$key] -eq 'directory') {
                    New-Item -ItemType Directory -Path $destination | Out-Null
                } else {
                    Copy-Item -LiteralPath (Join-Path $root $key.Replace('/', '\')) -Destination $destination
                }
            }
            Assert-Equal $inventory (Get-Inventory $target)
            Assert-Equal $inventory (Get-Inventory $root)
            Write-Output ("ARCHIVED {0}" -f $deployment.Name)
        } else {
            $archived = Get-Inventory $target
            Assert-Manifest $target $archived
            Assert-Equal $inventory $archived
            Remove-Item -LiteralPath $root -Recurse -Force
            Write-Output ("REMOVED {0}; verified archive retained" -f $deployment.Name)
        }
    } catch {
        Write-Output ("SKIPPED {0}: {1}" -f $deployment.Name, $_.Exception.Message)
    }
}
