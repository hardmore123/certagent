# 运行脚本与指令手册（scripts/）

所有脚本都会自动切到项目根目录，并清理父 shell 残留的 `REPORT_VERIFY_LLM_*` 环境变量（已知坑：残留的 `=off` 会压过 `.env`）。

在项目根目录执行。若遇执行策略限制，加 `-ExecutionPolicy Bypass`：
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run_web.ps1
```

---

## 脚本一览

| 脚本 | 作用 | 典型用法 |
|---|---|---|
| `run_web.ps1` | 启动 Web 服务（API + 前端同进程） | `.\scripts\run_web.ps1` |
| `run_sample.ps1` | 用内置样本跑一次完整核对（CLI） | `.\scripts\run_sample.ps1` |
| `run_tests.ps1` | 跑全量单元测试 | `.\scripts\run_tests.ps1` |
| `check_llm.ps1` | LLM 配置自检 + 发布门禁 | `.\scripts\check_llm.ps1` |
| `llm_config_summary.py` | 打印生效 LLM 配置（脱敏），被 check_llm 调用 | `python scripts\llm_config_summary.py` |

---

## 1. 安装依赖

```powershell
python -m pip install -r requirements.txt
```

`requests` 仅在启用 LLM 时真正使用（`client.py` 延迟导入），不装也能跑确定性核对。

## 2. 启动 Web 服务

```powershell
.\scripts\run_web.ps1                 # 127.0.0.1:8010
.\scripts\run_web.ps1 -Port 8011      # 换端口
.\scripts\run_web.ps1 -BindAll        # 监听 0.0.0.0，允许局域网访问
```

等价原始指令：
```powershell
Remove-Item Env:REPORT_VERIFY_LLM_* -ErrorAction SilentlyContinue
uvicorn webapi.app:app --host 0.0.0.0 --port 8010
```

浏览器打开 `http://127.0.0.1:8010/`。首次打开若界面是旧版，按 **Ctrl+F5** 强刷。

使用流程：上传 CERT（`A20` 开头）+ DRAFT（`100` 开头）→ 选 AI 模式 → 开始核对 → 逐行人工确认 → 全部确认后下载批注版与汇总。

## 3. 用内置样本跑核对（CLI）

```powershell
.\scripts\run_sample.ps1                 # 用 rules/normalization.json
.\scripts\run_sample.ps1 -Rules strict   # 纯逐字比较（不启用任何归一化）
.\scripts\run_sample.ps1 -OutDir runs\my_test
```

等价原始指令：
```powershell
python cli.py `
  --cert "samples\data\A2026CCC0808-4944044（00501-CG2026-0353）-P 安全描述+EMC（1.26） (2).docx" `
  --draft "samples\data\_converted\100E7S-PRO(01)_安全&EMC关键件清单 (1).docx" `
  --out runs\sample_run `
  --rules rules\normalization.json
```

CLI 其他参数：`--author`（批注作者，默认 ReportVerify）、`--initials`（缩写，默认 RV）。

输出：`verification.json`（完整 trace）、`批注版报告草稿.docx`、`差异汇总.docx`。
参照产物见 `samples/expected_outputs/`。

## 4. 跑测试

```powershell
.\scripts\run_tests.ps1                              # 全量
.\scripts\run_tests.ps1 -Pattern "test_llm_*.py"     # 只跑 LLM 相关
.\scripts\run_tests.ps1 -Pattern "test_llm_explain.py"
.\scripts\run_tests.ps1 -Quiet                       # 精简输出
```

等价原始指令：
```powershell
python -m unittest discover -s tests -v
```

测试不访问真实 provider，LLM 相关用本地 in-process stub（见 `tests/llm_contract_stub.py`）。

## 5. LLM 配置自检与门禁

```powershell
.\scripts\check_llm.ps1
```

输出两段：① 生效配置摘要（密钥只显示"已设置/未设置"）；② 发布门禁 JSON 诊断。
退出码 `0` = 安全（`mode=off` 或已通过全部激活门禁），`1` = 有门禁阻断。

等价原始指令：
```powershell
python scripts\llm_config_summary.py
python -m report_verify.llm.release_gate
```

---

## 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 前端 `Failed to fetch` | 服务没启动 | 跑 `run_web.ps1`，确认输出 `Uvicorn running on ...` |
| 界面是旧版 | 浏览器缓存 | Ctrl+F5 强刷 |
| LLM 配好了却不生效 | 父 shell 残留 `REPORT_VERIFY_LLM_MODE=off` | 用本目录脚本启动（已自动清理），或手动 `Remove-Item Env:REPORT_VERIFY_LLM_*` |
| 上传报 `error parsing the body` | 旧版 Starlette 1MiB 单 part 限制 | 已修复（`app.py` 手动 `request.form(max_part_size=...)`）；确认用的是最新代码 |
| 网关偶发 SSLError | 内网来源准入波动 | 重试或联系网关侧，非代码问题 |
| 终端输出被截断 | Windows PowerShell 回显限制 | 把输出写入 `runs\_diag.txt` 再读 |
| 大文件很慢 | 141MB CERT 解析+LLM 耗时 | 看页面计时判断卡在"解析核对"还是"AI 解释" |
