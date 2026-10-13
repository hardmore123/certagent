<#
.SYNOPSIS
    LLM 发布门禁检查 + 当前生效配置自检（脱敏，不访问 provider）。

.DESCRIPTION
    两步：
      1) 打印当前生效的 LLM 配置摘要（密钥只显示"已设置/未设置"，不打印值）
      2) 运行 release_gate 门禁检查，输出 JSON 脱敏诊断
    退出码 0 = 安全关闭(mode=off) 或已通过全部激活门禁；1 = 有门禁失败。

.EXAMPLE
    .\scripts\check_llm.ps1
#>
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

# 清理残留，确保读到的是 .env 的真实意图
Remove-Item Env:REPORT_VERIFY_LLM_* -ErrorAction SilentlyContinue

Write-Host "=== 1) 当前生效配置摘要（脱敏）===" -ForegroundColor Cyan
python scripts\llm_config_summary.py

Write-Host "`n=== 2) 发布门禁检查 ===" -ForegroundColor Cyan
python -m report_verify.llm.release_gate
$code = $LASTEXITCODE

if ($code -eq 0) {
    Write-Host "`n[通过] 配置安全（mode=off 或已通过全部激活门禁）" -ForegroundColor Green
} else {
    Write-Host "`n[阻断] 存在门禁失败，provider 保持关闭。详见 LLM_RELEASE_GATE.md" -ForegroundColor Red
}
exit $code
