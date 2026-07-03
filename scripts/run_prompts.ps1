param(
    [string]$PromptsFile = "prompts.txt",
    [string]$Mode = "external-tele",
    [string]$OutputRoot = "outputs\batch_runs",
    [string]$LogRoot = "outputs\batch_logs",
    [int]$StartIndex = 1,
    [int]$EndIndex = 0,
    [switch]$Resume,
    [switch]$StopOnError
)

$ErrorActionPreference = "Stop"

function New-PromptId {
    param([string]$Text)
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
    $sha1 = [System.Security.Cryptography.SHA1]::Create()
    try {
        $hash = $sha1.ComputeHash($bytes)
    }
    finally {
        $sha1.Dispose()
    }
    return ([System.BitConverter]::ToString($hash)).Replace("-", "").Substring(0, 10).ToLowerInvariant()
}

function Ensure-Directory {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path | Out-Null
    }
}

if (-not (Test-Path -LiteralPath $PromptsFile)) {
    throw "Prompts file not found: $PromptsFile"
}

Ensure-Directory -Path $OutputRoot
Ensure-Directory -Path $LogRoot

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$batchName = "batch_$stamp"
$batchOutputRoot = Join-Path $OutputRoot $batchName
$batchLogRoot = Join-Path $LogRoot $batchName
Ensure-Directory -Path $batchOutputRoot
Ensure-Directory -Path $batchLogRoot

$summaryPath = Join-Path $batchLogRoot "summary.csv"
"index,status,exit_code,duration_seconds,run_dir,stdout_log,stderr_log,prompt" | Set-Content -Path $summaryPath -Encoding UTF8

$allPrompts = Get-Content -LiteralPath $PromptsFile -Encoding UTF8 | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
if ($EndIndex -le 0 -or $EndIndex -gt $allPrompts.Count) {
    $EndIndex = $allPrompts.Count
}
if ($StartIndex -lt 1 -or $StartIndex -gt $EndIndex) {
    throw "Invalid range: StartIndex=$StartIndex EndIndex=$EndIndex Count=$($allPrompts.Count)"
}

Write-Host "Total prompts: $($allPrompts.Count)"
Write-Host "Running range: $StartIndex..$EndIndex"
Write-Host "Mode: $Mode"
Write-Host "Batch output: $batchOutputRoot"
Write-Host "Batch logs: $batchLogRoot"

for ($i = $StartIndex; $i -le $EndIndex; $i++) {
    $prompt = $allPrompts[$i - 1].Trim()
    $promptId = New-PromptId -Text $prompt
    $runName = "{0:D3}_{1}" -f $i, $promptId
    $runDir = Join-Path $batchOutputRoot $runName
    $stdoutLog = Join-Path $batchLogRoot "$runName.stdout.log"
    $stderrLog = Join-Path $batchLogRoot "$runName.stderr.log"
    $promptFile = Join-Path $batchLogRoot "$runName.prompt.txt"

    Set-Content -Path $promptFile -Value $prompt -Encoding UTF8

    if ($Resume -and (Test-Path -LiteralPath $runDir)) {
        Write-Host "[$i/$EndIndex] Skip existing: $runName"
        ('{0},{1},{2},{3},"{4}","{5}","{6}","{7}"' -f
            $i, "skipped", 0, 0, $runDir, $stdoutLog, $stderrLog, ($prompt -replace '"', '""')
        ) | Add-Content -Path $summaryPath -Encoding UTF8
        continue
    }

    Ensure-Directory -Path $runDir
    Write-Host "[$i/$EndIndex] Running: $runName"
    $started = Get-Date

    $exitCode = 0

    try {
        $proc = Start-Process `
            -FilePath "genclaw" `
            -ArgumentList @("run", "--mode", $Mode, "--prompt", $prompt, "--out", $runDir) `
            -RedirectStandardOutput $stdoutLog `
            -RedirectStandardError $stderrLog `
            -NoNewWindow `
            -Wait `
            -PassThru
        $exitCode = $proc.ExitCode
    }
    catch {
        $exitCode = 1
        ($_ | Out-String) | Set-Content -Path $stderrLog -Encoding UTF8
        if (-not (Test-Path -LiteralPath $stdoutLog)) {
            "" | Set-Content -Path $stdoutLog -Encoding UTF8
        }
    }

    $duration = [math]::Round(((Get-Date) - $started).TotalSeconds, 2)

    if (-not (Test-Path -LiteralPath $stdoutLog)) {
        "" | Set-Content -Path $stdoutLog -Encoding UTF8
    }

    if (-not (Test-Path -LiteralPath $stderrLog)) {
        "" | Set-Content -Path $stderrLog -Encoding UTF8
    }

    $status = if ($exitCode -eq 0) { "ok" } else { "failed" }
    ('{0},{1},{2},{3},"{4}","{5}","{6}","{7}"' -f
        $i, $status, $exitCode, $duration, $runDir, $stdoutLog, $stderrLog, ($prompt -replace '"', '""')
    ) | Add-Content -Path $summaryPath -Encoding UTF8

    if ($exitCode -eq 0) {
        Write-Host "[$i/$EndIndex] OK in ${duration}s"
    }
    else {
        Write-Warning "[$i/$EndIndex] FAILED in ${duration}s"
        if ($StopOnError) {
            throw "Stopping on error at prompt index $i"
        }
    }
}

Write-Host "Done. Summary: $summaryPath"
