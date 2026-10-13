<#
.SYNOPSIS
    启动 ReportVerify Web 服务（后端 API + 前端静态页，单进程托管）。

.DESCRIPTION
    会先清理父 shell 残留的 REPORT_VERIFY_LLM_* 进程级环境变量。
    这是已知坑：残留的 REPORT_VERIFY_LLM_MODE=off 会压过项目根 .env 的配置，
    导致 LLM 明明配好了却不生效。

.PARAMETER Port
    监听端口，默认 8010。

.PARAMETER BindAll
    是否监听 0.0.0.0（允许局域网访问）。默认只监听 127.0.0.1。

.EXAMPLE
    .\scripts\run_web.ps1
    .\scripts\run_web.ps1 -Port 8011
    .\scripts\run_web.ps1 -BindAll
#>
param(
    [int]$Port = 8010,
    [switch]$BindAll
)

$ErrorActionPreference = "Stop"
# 切到项目根目录（脚本在 scripts/ 下）
Set-Location (Split-Path $PSScriptRoot -Parent)

# 清理残留的进程级 LLM 环境变量，确保 .env 生效
Remove-Item Env:REPORT_VERIFY_LLM_* -ErrorAction SilentlyContinue

$bindHost = if ($BindAll) { "0.0.0.0" } else { "127.0.0.1" }

Write-Host "项目目录: $(Get-Location)"              -ForegroundColor Cyan
Write-Host "监听地址: http://${bindHost}:${Port}/"   -ForegroundColor Cyan
if (Test-Path ".env") {
    Write-Host ".env     : 已存在（LLM 配置将从中加载）" -ForegroundColor Green
} else {
    Write-Host ".env     : 不存在（LLM 保持关闭，仅确定性核对）" -ForegroundColor Yellow
}
Write-Host "按 Ctrl+C 停止服务`n" -ForegroundColor DarkGray

uvicorn webapi.app:app --host $bindHost --port $Port
