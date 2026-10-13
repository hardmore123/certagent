# 测试与测试样例说明（tests/）

标准库 `unittest`，不依赖 pytest。**不访问真实 provider**：LLM 相关测试全部使用本地 in-process stub。

运行：
```powershell
.\scripts\run_tests.ps1                            # 全量
.\scripts\run_tests.ps1 -Pattern "test_llm_*.py"   # 只跑 LLM
python -m unittest discover -s tests -v            # 原始指令
```

---

## 一、测试文件分类

### 核对核心（确定性）

| 文件 | 覆盖内容 |
|---|---|
| `test_core.py` | 表头指纹识别、合并单元格、空值、多值型号、重复项、字段映射；三类差异（`field_mismatch` / `missing_in_draft` / `extra_in_draft`）；归一化规则命中与规则外字符差异；批注锚点降级与汇总兜底 |
| `test_review_feedback.py` | 人工确认落盘、反馈记忆写入与回放、文档版本边界 |

### LLM 子包

| 文件 | 覆盖内容 |
|---|---|
| `test_llm_config.py` | `LLMSettings` 解析、默认值、上限校验、凭据不序列化 |
| `test_llm_policy.py` | 服务器策略：字段白名单、行数/字符上限、脱敏档位 |
| `test_llm_policy_regression.py` | 策略回归：防止护栏被放宽 |
| `test_llm_jobmode.py` | 任务级 mode 授权、越权覆盖拒绝 |
| `test_llm_client.py` | 请求装配、SSE/JSON 响应读取、字节上限、JSON 语法修复、错误分类、重试/断路器接口 |
| `test_llm_schemas.py` | 响应 Schema 与字段长度校验 |
| `test_llm_evidence.py` | 脱敏证据 sidecar 读写 |
| `test_llm_explain.py` | 差异解释：分批、范围上限、并发、截断标记 |
| `test_llm_orchestrator.py` | candidate 编排与候选校验 |
| `test_llm_discipline.py` | 候选专业建议（只给候选不自动路由） |
| `test_llm_recheck.py` | 复核辅助 |
| `test_llm_release_gate.py` | 发布门禁各项检查与退出码 |
| `test_llm_injection_check.py` | 提示注入检测 |
| `test_llm_security_regression.py` | 安全回归：凭据/原文不泄漏、图片硬拒绝 |
| `test_llm_task44_properties.py` | 正确性属性测试（已实现部分；4.6–4.14 待补） |
| `test_llm_provider_contract.py` | provider 协议契约 |
| `test_certagent_llm_contract.py` | 与 CertAgent 网关约定的契约一致性 |

### Web / 环境

| 文件 | 覆盖内容 |
|---|---|
| `test_webapi_jobs.py` | 任务创建、状态流转、落盘与重启恢复 |
| `test_webapi_task_mode.py` | 任务级 LLM mode 的 API 行为 |
| `test_webapi_llm_background.py` | LLM 阶段在后台执行、失败不影响确定性结果 |
| `test_webapi_llm_review_gate.py` | **下载门禁**：未完成人工确认不得下载；LLM 不改变门禁 |
| `test_env_bootstrap.py` | `.env` 加载、真实环境变量优先不覆盖 |

---

## 二、输入测试样例

### 1. provider 协议 fixtures（`tests/fixtures/llm_contract/`）

模拟网关各种响应形态，用于验证 client 的解析与容错。**不含任何真实凭据**，endpoint 为 loopback。

| 文件 | 模拟场景 | 验证点 |
|---|---|---|
| `request_contract.json` | 期望的请求契约（base_url 为 `http://127.0.0.1:8765/v1`） | 请求装配是否符合约定 |
| `sse_fenced_json.txt` | SSE 流式，content 被 ```` ```json ```` 围栏包裹 | SSE 累积 + 围栏剥离 |
| `sse_reasoning_only.txt` | SSE 只有 `reasoning_content`，无正式 content | 忽略非 content 字段，空响应判定 |
| `sse_malformed_lines.txt` | SSE 含非 JSON 垃圾行（`data: not-json-at-all`） | 畸形行容错，不崩溃 |
| `non_stream_json.txt` | 非流式完整响应（`choices[0].message.content`） | JSON transport 读取 |
| `repair_with_prose.txt` | content 前后夹带解释性散文 | JSON 语法修复：截取第一个 `{...}` |

### 2. in-process stub（`tests/llm_contract_stub.py`）

替代真实 HTTP transport 的本地 stub，**不开 socket、不访问网络**。按上述 fixtures 回放响应，让 LLM 全链路可在离线环境测试。

### 3. 真实文档样例（`samples/`）

| 位置 | 内容 |
|---|---|
| `samples/data/` | CERT 认证资料（29 表，约 141MB）、DRAFT 原始 `.doc` 与转换后 `.docx`、转换脚本 |
| `samples/manifest.json` | 样本角色规则、各目标子块所在表索引、总表数 |
| `samples/gold_baseline.json` | 结构基线（期望表数与子块数量） |
| `samples/expected_outputs/` | 一次真实核对的产物（trace + 批注版 + 汇总），可作回归参照 |

详见 `samples/README.md`。真实样本的端到端跑法见 `scripts/run_sample.ps1`。

---

## 三、测试样例覆盖的关键场景

确定性核对侧（来自 `tasks.md` T16 验收要求）：
- 表头指纹识别 / 合并单元格 / 纵向与横向合并导致的列错位
- 空值、占位符（`/`、`-`、`N/A`）、多值型号、重复项
- 三类差异分类正确性
- 无意义差异（8 项归一化规则）命中，与规则外实质差异不被吞掉
- 批注锚点失败时的降级与汇总兜底

LLM 侧：
- 凭据不进日志/异常/trace/元数据
- 图片能力固定硬拒绝
- 任务级 mode 不可越权
- 原文受字段白名单 + 字符/行数上限约束
- 响应 Schema 校验、超大响应拒绝、畸形 JSON 容错
- 失败一律回退到确定性证据，不改变下载门禁

---

## 四、待补测试

LLM 集成 spec 中 9 个可选属性测试 **4.6–4.14** 尚未实现，覆盖分批边界、并发、截断标记、护栏等。参考 `test_llm_task44_properties.py` 的写法。详见 `docs/specs/report-draft-llm-integration/tasks.md`。
