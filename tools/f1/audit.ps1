# Read-only inventory. Run on f1: powershell -NoProfile -File tools/f1/audit.ps1
# Outputs JSON; excludes sensitive/configuration and log files from file hashing.
$ErrorActionPreference = 'Stop'
$env:GIT_OPTIONAL_LOCKS = '0'
$repositories = @('C:\Code\lorwright')
$deploymentRoot = 'C:\Code\lorwright-deployments'

function Get-RepoSummary([string]$Path, [bool]$IncludeFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $Path '.git'))) { return $null }
    $head = (& git -C $Path rev-parse HEAD 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { throw "Cannot inspect repository: $Path" }
    $status = @(& git -C $Path status --porcelain --untracked-files=all)
    if ($LASTEXITCODE -ne 0) { throw "Cannot inspect status: $Path" }
    $result = [ordered]@{ path = $Path; head = $head; changed_entries = $status.Count }
    if ($IncludeFiles) {
        # Git emits one path per line; filenames containing newlines are unsupported.
        $names = @(& git -C $Path -c core.quotepath=false diff --name-only HEAD) +
                 @(& git -C $Path -c core.quotepath=false ls-files --others --exclude-standard)
        $files = foreach ($name in ($names | Sort-Object -Unique)) {
            if (-not $name -or $name -match '(?i)(^|[/\\])\.env([^/\\]*)?$|credential|secret|password|token|(^|[/\\])(logs?|config)([/\\]|$)|\.(log|pem|key|p12|pfx|json|ya?ml|ini|toml)$') { continue }
            $file = Join-Path $Path $name
            if (Test-Path -LiteralPath $file -PathType Leaf) {
                $item = Get-Item -LiteralPath $file
                [ordered]@{ path = $name; bytes = $item.Length; sha256 = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() }
            } else {
                [ordered]@{ path = $name; missing = $true }
            }
        }
        $result.files = @($files)
        $result.note = 'Sensitive, configuration and log paths omitted; ignored files and filenames containing newlines are not inventoried reliably. Deleted paths have missing=true.'
    }
    return $result
}

$repos = @($repositories | ForEach-Object { Get-RepoSummary $_ $true } | Where-Object { $_ })
$deployments = @()
if (Test-Path -LiteralPath $deploymentRoot) {
    $deployments = @(Get-ChildItem -LiteralPath $deploymentRoot -Directory | ForEach-Object {
        $directory = $_
        $size = (Get-ChildItem -LiteralPath $directory.FullName -Force -File -Recurse -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
        $repo = Get-RepoSummary (Join-Path $directory.FullName 'project') $false
        [ordered]@{ path = $directory.FullName; bytes = [long]$size; project_repository = $repo }
    })
}
# Only report which known paths appear, never command lines or task arguments.
$paths = @($repositories) + @($deployments | ForEach-Object { $_.path })
$processes = @(Get-CimInstance Win32_Process | ForEach-Object {
    $process = $_
    $matches = @($paths | Where-Object { $process.CommandLine -and $process.CommandLine.IndexOf($_, [StringComparison]::OrdinalIgnoreCase) -ge 0 })
    if ($matches.Count) { [ordered]@{ pid = $process.ProcessId; name = $process.Name; referenced_paths = $matches } }
})
$tasks = @(Get-ScheduledTask | ForEach-Object {
    $task = $_
    $actionText = (($task.Actions | ForEach-Object { "$($_.Execute) $($_.Arguments) $($_.WorkingDirectory)" }) -join ' ')
    $matches = @($paths | Where-Object { $actionText.IndexOf($_, [StringComparison]::OrdinalIgnoreCase) -ge 0 })
    if ($matches.Count) { [ordered]@{ name = $task.TaskName; task_path = $task.TaskPath; state = [string]$task.State; referenced_paths = $matches } }
})
[ordered]@{ repositories = $repos; deployments = $deployments; processes = $processes; scheduled_tasks = $tasks; limitations = 'Path references in process command lines and scheduled task actions only; indirect references, environment variables, services, and ignored files require separate inspection. Sizes may be incomplete if access is denied.' } | ConvertTo-Json -Depth 8
