# CertAgent 一键备份：快照到 历史版本，生成版本说明，追加工作日志。
# 用法：powershell -NoProfile -ExecutionPolicy Bypass -File _backup_certagent.ps1 [标签]
param([string]$Label = "解密集成+LLM熔断修复+前端放行加密文件")

$ErrorActionPreference = "Stop"
$enc = New-Object System.Text.UTF8Encoding($true)   # UTF-8 with BOM
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$proj    = $PSScriptRoot
$src     = Join-Path $proj "CertAgent"
$histDir = Join-Path $proj "历史版本"
$logFile = Join-Path $proj "工作日志.md"

if (-not (Test-Path $src)) { Write-Host "[错误] 找不到源目录：$src" -ForegroundColor Red; exit 1 }

if (-not $Label) {
    $Label = Read-Host "请输入本次版本标签（可留空，回车跳过）"
}
$Label = ($Label -replace '[\\/:*?"<>|]', '').Trim()

$ts   = Get-Date -Format "yyyyMMdd_HHmmss"
$name = if ($Label) { "$ts`_$Label" } else { $ts }
$dst  = Join-Path $histDir "版本_$name\CertAgent"

# ===== 可选：从服务器拉回业务长期记忆 feedback.jsonl（非免密 SSH，需手动输密码）=====
# 服务器是实际跑任务积累记忆的地方；拉回后会被本次 robocopy 一并归档进快照。
$serverFeedback = "hisense@10.18.87.51:/home/hisense/pro/Gitlab/CertAgent/compare_core/memory/data/feedback.jsonl"
$localFeedback  = Join-Path $src "compare_core\memory\data\feedback.jsonl"
Write-Host ""
Write-Host "==> [可选] 拉回服务器长期记忆 feedback.jsonl" -ForegroundColor Cyan
$answer = Read-Host "    是否从服务器拉回记忆？(y/n，回车跳过)"
if ($answer -match '^[Yy]') {
    scp $serverFeedback $localFeedback
    if ($LASTEXITCODE -eq 0) { Write-Host "    [OK] 已拉回：$localFeedback" -ForegroundColor Green }
    else { Write-Host "    [跳过] 拉回失败（服务器可能无此文件，或密码输入有误）" -ForegroundColor Yellow }
} else {
    Write-Host "    跳过拉回" -ForegroundColor DarkGray
}

Write-Host "==> 备份中：$src" -ForegroundColor Cyan
Write-Host "         -> $dst"

# robocopy：排除依赖/产物/缓存/密钥/前端构建产物
$rc = Start-Process robocopy -ArgumentList @(
    "`"$src`"", "`"$dst`"", "/E",
    "/XD", "node_modules", "dist", "runs", "jobs", "__pycache__", "_converted", ".kiro", ".git", ".vscode", ".idea", "venv", ".venv",
    "/XF", ".env", "*.pyc",
    "/NFL", "/NDL", "/NJH", "/NJS", "/NP"
) -NoNewWindow -Wait -PassThru
if ($rc.ExitCode -ge 8) { Write-Host "[错误] robocopy 失败，代码 $($rc.ExitCode)" -ForegroundColor Red; exit 1 }

$fileCount = (Get-ChildItem $dst -Recurse -File | Measure-Object).Count

# 安全检查：确认 .env 未被复制
$envLeak = Test-Path (Join-Path $dst ".env")
$envMsg  = if ($envLeak) { "⚠ 警告：.env 被复制，请手动删除！" } else { "已排除（保留 .env.example）" }

$now = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

$note = @"
# 版本快照 $name（CertAgent）

- 快照时间：$now
- 来源：CertAgent（工作副本）
- 文件数：$fileCount
- .env：$envMsg
- 排除项：.git / .env / node_modules / dist / runs / jobs / __pycache__ / _converted / .kiro / .vscode / .idea / venv / *.pyc

## 本版本关键改动（2026-08-20）
- 透明加密文件上传：新增 compare_core/decrypt.py，上传加密 docx 后调解密服务（10.18.87.51:8500）还原；runner._load_one 解密兜底
- LLM 熔断修复：去掉 reasoning 字数熔断（10k 误杀正常长思考），保留 120s 墙钟兜底
- config.py 自动加载项目根 .env（LLM 环境变量不再依赖 systemd/export）
- 前端放行加密 docx 的未知 magic（交给后端解密兜底），只拦 .doc
- 部署文档（部署与使用指南 / 部署问题排查日志）+ test_decrypt.py

## git 版本
- 本地 commit e9afe4f（已推送到 Gitlab origin/main）

## 说明
- 前端构建产物 dist 已排除，恢复后用 `cd frontend && npm install && npm run build` 重建
- .env 含 LLM 密钥，未纳入快照；部署时需按服务器 .env 或 .env.example 自行配置

---
> 本文件由 _backup_certagent.ps1 自动生成。
"@

$noteFile = Join-Path (Split-Path $dst -Parent) "版本说明.md"
[System.IO.File]::WriteAllText($noteFile, $note, $enc)
Write-Host "==> 版本说明：$noteFile" -ForegroundColor Green

# 追加到工作日志
if (Test-Path $logFile) {
    $logEntry = "`r`n---`r`n`r`n## 版本快照 $name（CertAgent，$now）`r`n`r`n" +
                "备份到 历史版本\版本_$name\（$fileCount 个文件，.env $envMsg）。`r`n" +
                "本版本改动：解密集成 / LLM 熔断修复 / 前端放行加密文件。`r`n"
    Add-Content -Path $logFile -Value $logEntry -Encoding UTF8
    Write-Host "==> 已追加工作日志：$logFile" -ForegroundColor Green
} else {
    Write-Host "[提示] 未找到工作日志：$logFile（跳过追加）" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "CertAgent 备份完成。" -ForegroundColor Cyan
if ($envLeak) { Write-Host "请注意上面的 .env 警告！" -ForegroundColor Red }
