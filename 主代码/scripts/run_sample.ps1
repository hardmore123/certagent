<#
.SYNOPSIS
    Run one full deterministic verification using the bundled samples.

.DESCRIPTION
    Resolves CERT / DRAFT from samples/data via filename-prefix rules
    (A20* = CERT, 100* = DRAFT) so the script itself contains no CJK
    full-width characters in paths. Outputs verification.json plus the
    annotated draft and the diff summary docx.

.PARAMETER OutDir
    Output directory. Defaults to runs/sample_<yyyyMMdd_HHmmss>.

.PARAMETER Rules
    Normalization rules JSON path. Defaults to rules/normalization.json.
    Pass "strict" to disable all normalization (pure character compare).

.EXAMPLE
    .\scripts\run_sample.ps1
    .\scripts\run_sample.ps1 -Rules strict
    .\scripts\run_sample.ps1 -OutDir runs\my_test
#>
param(
    [string]$OutDir = "",
    [string]$Rules = ""
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

# Resolve samples by prefix rule: A20* = CERT, 100* = DRAFT (see samples/manifest.json)
$certFile = Get-ChildItem -Path "samples\data" -Filter "A20*.docx" -File |
    Select-Object -First 1
$draftFile = Get-ChildItem -Path "samples\data\_converted" -Filter "100*.docx" -File |
    Select-Object -First 1

if (-not $certFile) { throw "CERT sample not found: samples\data\A20*.docx" }
if (-not $draftFile) { throw "DRAFT sample not found: samples\data\_converted\100*.docx" }

$cert = $certFile.FullName
$draft = $draftFile.FullName

if ([string]::IsNullOrWhiteSpace($OutDir)) {
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $OutDir = Join-Path "runs" "sample_$stamp"
}

$cliArgs = @("--cert", $cert, "--draft", $draft, "--out", $OutDir)

if ($Rules -eq "strict") {
    Write-Host "Rules : strict (no normalization)" -ForegroundColor Yellow
}
elseif (-not [string]::IsNullOrWhiteSpace($Rules)) {
    $cliArgs += @("--rules", $Rules)
    Write-Host "Rules : $Rules" -ForegroundColor Cyan
}
else {
    $cliArgs += @("--rules", "rules\normalization.json")
    Write-Host "Rules : rules\normalization.json (normalized-v2)" -ForegroundColor Cyan
}

Write-Host "CERT  : $($certFile.Name)"
Write-Host "DRAFT : $($draftFile.Name)"
Write-Host "Out   : $OutDir"
Write-Host ""

python cli.py @cliArgs
$code = $LASTEXITCODE

if ($code -ne 0) {
    Write-Host "FAILED (exit $code)" -ForegroundColor Red
    exit $code
}

Write-Host ""
Write-Host "Artifacts:" -ForegroundColor Green
Get-ChildItem $OutDir |
    Select-Object Name, @{ Name = "KB"; Expression = { [math]::Round($_.Length / 1KB, 1) } } |
    Format-Table -AutoSize
