# 一键备份脚本：快照 list-merge-demo 到 历史版本，生成版本说明，追加工作日志。
# 由 备份.bat 调用（也可单独：powershell -ExecutionPolicy Bypass -File _backup.ps1 [标签]）
param([string]$Label = "")

$ErrorActionPreference = "Stop"
$enc = New-Object System.Text.UTF8Encoding($true)   # UTF-8 with BOM
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$proj    = $PSScriptRoot
$src     = Join-Path $proj "list-merge-demo"
$histDir = Join-Path $proj "历史版本"
$logFile = Join-Path $proj "工作日志.md"

if (-not (Test-Path $src)) { Write-Host "[错误] 找不到源目录：$src" -ForegroundColor Red; exit 1 }

# 标签：命令行参数优先，否则交互输入（可留空）
if (-not $Label) {
    $Label = Read-Host "请输入本次版本标签（可留空，回车跳过）"
}
$Label = ($Label -replace '[\\/:*?"<>|]', '').Trim()

$ts   = Get-Date -Format "yyyyMMdd_HHmmss"
$name = if ($Label) { "$ts`_$Label" } else { $ts }
$dst  = Join-Path $histDir "版本_$name\list-merge-demo"

Write-Host "==> 备份中：$src" -ForegroundColor Cyan
Write-Host "         -> $dst"

# robocopy：排除依赖/产物/缓存/密钥
$rc = Start-Process robocopy -ArgumentList @(
    "`"$src`"", "`"$dst`"", "/E",
    "/XD", "node_modules", "runs", "__pycache__", ".kiro", "dist", ".git",
    "/XF", ".env", "*.pyc",
    "/NFL", "/NDL", "/NJH", "/NJS", "/NP"
) -NoNewWindow -Wait -PassThru
if ($rc.ExitCode -ge 8) { Write-Host "[错误] robocopy 失败，代码 $($rc.ExitCode)" -ForegroundColor Red; exit 1 }

$fileCount = (Get-ChildItem $dst -Recurse -File | Measure-Object).Count

# 安全检查：确认 .env 未被复制
$envLeak = Test-Path (Join-Path $dst ".env")
$envMsg  = if ($envLeak) { "⚠ 警告：.env 被复制，请手动删除！" } else { "已排除（仅保留 .env.example）" }

$now = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

# ===== 已完成 / 未完成清单（随项目演进，需要时更新本段）=====
$done = @"
### 已完成的能力
- 解析：python-docx（无 COM，线程安全）+ .doc 自动转换（LibreOffice/Word 子进程）
- 匹配（分趟，确定性）：
  - Rich 键精确匹配 + 命中后内容复核（认证标准/制造商等变更不再被判 SAME 静默吞掉）
  - Loose 键（同表+同组+同名+同型号）→ CHANGED
  - 第 2.5 趟型号集合匹配：子集(列表扩充)自动合并、部分重叠交人工、括号说明剥离
  - 可选 LLM fuzzy 候选提名（只提名不决策，人工确认；前端开关）
- 数据守恒审计（三层：引擎/决策/物理）+ 指纹定位丢行 + 自动补录自愈 + 守恒等式可视化
- Word 输出：表1/表2 结构、分组行、来源列、标红、繁→简、统一字体
- Web 前后端：FastAPI(JWT+异步任务+审计面板) + React(登录/工作台/差异确认)
- 差异确认页：合并视图 + 并排对照视图(A|B 行号映射+词级高亮)、顺序对齐最终文档、跳到下一个待确认
- 拒绝配对→拆开保留(不丢行)、别名沉淀 mine_aliases
"@

$todo = @"
### 待完成 / 待确认
- [ ] reject 三态：CHANGED 被拒应区分「保留旧值 / 整行删除」——需业务先定语义
- [ ] 对照表按 decisions 过滤 + 被拒项附录留痕（当前对照表不受拒绝影响）
- [ ] 审计 P2：决策层输出 rejected_items 明细（依赖 reject 三态）
- [ ] 输出格式可配：字号/列宽/页面方向/模板文件（现仅字体+繁简可配）
- [ ] 型号集合 overlap 自动合并开关 accept_overlap（默认关，待业务确认）
- [ ] 别名归一回灌 diff：mine_aliases 已产出别名对，尚未在 diff 前做名称归一
- [ ] 跨样例验证：目前仅东芝 85ZXSF 一个真实差异样例，跨机型稳定性待验
- [ ] 环境：依赖装在 Python 3.14，系统 python 可能是 3.12；
      启动后端须用 Python314\python.exe -m webapi
"@

$note = @"
# 版本快照 $name

- 快照时间：$now
- 来源：list-merge-demo（工作副本）
- 文件数：$fileCount
- .env：$envMsg
- 排除项：node_modules / runs / __pycache__ / .kiro / dist / .git / .env / *.pyc

$done

$todo

---
> 本文件由 备份.bat 自动生成。已完成/待办清单如与实际不符，请更新 项目根目录\_backup.ps1 中对应段落。
"@

$noteFile = Join-Path (Split-Path $dst -Parent) "版本说明.md"
[System.IO.File]::WriteAllText($noteFile, $note, $enc)
Write-Host "==> 版本说明：$noteFile" -ForegroundColor Green

# 追加到工作日志
if (Test-Path $logFile) {
    $logEntry = "`r`n---`r`n`r`n## 版本快照 $name（$now）`r`n`r`n" +
                "备份到 历史版本\版本_$name\（$fileCount 个文件，.env $envMsg）。`r`n" +
                "已完成能力与待办清单见该目录下 版本说明.md。`r`n"
    Add-Content -Path $logFile -Value $logEntry -Encoding UTF8
    Write-Host "==> 已追加工作日志：$logFile" -ForegroundColor Green
} else {
    Write-Host "[提示] 未找到工作日志：$logFile（跳过追加）" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "备份完成。" -ForegroundColor Cyan
if ($envLeak) { Write-Host "请注意上面的 .env 警告！" -ForegroundColor Red }
