<#
.SYNOPSIS
    Run the unit test suite (standard library unittest).

.DESCRIPTION
    Tests never reach a real provider: LLM tests use a local in-process stub.
    Residual REPORT_VERIFY_LLM_* process variables are cleared first so the
    suite runs against a clean configuration.

.PARAMETER Pattern
    Only run matching test files, e.g. -Pattern "test_llm_*.py".

.PARAMETER Quiet
    Compact output (omit -v).

.EXAMPLE
    .\scripts\run_tests.ps1
    .\scripts\run_tests.ps1 -Pattern "test_llm_explain.py"
    .\scripts\run_tests.ps1 -Quiet
#>
param(
    [string]$Pattern = "test*.py",
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

# Clear residual LLM env vars so they cannot override test expectations
Remove-Item Env:REPORT_VERIFY_LLM_* -ErrorAction SilentlyContinue

$verbosity = if ($Quiet) { @() } else { @("-v") }

Write-Host "Tests : tests/   Pattern: $Pattern" -ForegroundColor Cyan
Write-Host ""

python -m unittest discover -s tests -p $Pattern @verbosity
$code = $LASTEXITCODE

Write-Host ""
if ($code -eq 0) {
    Write-Host "PASSED - all tests green" -ForegroundColor Green
}
else {
    Write-Host "FAILED - exit code $code" -ForegroundColor Red
}
exit $code
