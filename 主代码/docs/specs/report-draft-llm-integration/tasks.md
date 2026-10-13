# Implementation Plan: report-draft-llm-integration

## Overview

本计划将设计文档中的可选 LLM 集成拆分为可增量执行的凭据注入映射、服务器策略、CertAgent provider 适配、ReportVerify 能力接入、Web/后台任务兼容以及测试与发布门禁工作。用户已确认模型、Base URL、endpoint、请求/响应契约和鉴权完全复用 CertAgent；实现只通过受控环境/secret 注入复用同一组凭据，并禁止把真实值写入任何仓库或记录。

LLM 仅作为确定性核对之后的候选/解释建议来源；在 `REPORT_VERIFY_LLM_ALLOW_ORIGINAL_TEXT=true` 的服务器策略下允许白名单 CERT/DRAFT 字段原文，但文件、路径、二进制、图片、工具调用始终禁止外发，图片固定 false 且必须硬拒绝。任务可以选择服务器 allowlist 中的 `llm_mode`，但不能覆盖 provider、model、key、host/TLS 或任何外发策略。所有任务必须保持确定性差异、人工确认和最终下载门禁不变。

本文件仅描述编码、测试、配置和验证活动，不执行真实 provider 调用，不创建或迁移真实密钥，不修改 CertAgent 生产代码或 ReportVerify 业务确定性代码。

## Confirmed Integration Contract

以下用户决策已确认，不再作为待确认产品决策：

- [x] 使用 CertAgent 当前完全相同的模型、Base URL、`/chat/completions` endpoint、请求/响应/JSON repair 兼容策略和 Bearer/user-key 鉴权。
- [x] 通过本机受控环境变量或受控 secret 注入复用 CertAgent 同一组凭据；只实施变量映射/健康检查，不复制或记录真实 key。
- [x] 服务器策略 `REPORT_VERIFY_LLM_ALLOW_ORIGINAL_TEXT=true` 时允许白名单 CERT/DRAFT 字段原文；文件、路径、二进制、图片、工具调用始终禁止。
- [x] 图片能力固定 `false`，无授权例外、无任务级覆盖，发现图片外发意图必须在网络调用前硬拒绝。
- [x] 创建任务可以选择服务器 allowlist 中的 `llm_mode`，但不能覆盖 provider、model、endpoint、凭据、host/TLS 或外发策略。

## Prerequisites / Validation Gates

以下是编码和验证门禁，不是要求用户再次确认的决策；完成前生产仍保持 `REPORT_VERIFY_LLM_MODE=off`：

- [x] 0.1 编写并运行 CertAgent → ReportVerify 的变量映射/受控凭据注入检查；只验证变量存在性、权限和 diagnostics 脱敏，不读取、打印、复制或持久化真实值。
- [x] 0.2 编写服务器 policy 配置检查：确认 `REPORT_VERIFY_LLM_ALLOW_ORIGINAL_TEXT=true` 的字段白名单策略、`allow_images=false` 固定拒绝、host/TLS allowlist 和任务 mode allowlist 均不能被请求覆盖。
- [x] 0.3 使用本地 stub/占位 fixture 验证 CertAgent 当前 model、endpoint、请求/响应、SSE/JSON 和 repair 契约映射；不访问真实 provider。

## Tasks

### Phase 1: 配置、策略和 provider 适配

- [x] 1.1 在 ReportVerify 内新增环境变量配置对象和 CertAgent 凭据映射；保证诊断输出不含 secret。
  - 实现不可变 settings、默认 `mode=off`、安全上限和非敏感 diagnostics。
  - 将 CertAgent 当前 `LLM_BASE_URL`、`LLM_MODEL`、`LLM_API_KEY`、`LLM_USER_KEY` 映射到对应 `REPORT_VERIFY_LLM_*` 配置；只从本机受控环境/secret 注入读取，绝不在代码、文档、fixture、日志或 trace 中复制值。
  - 将 `REPORT_VERIFY_LLM_ALLOW_ORIGINAL_TEXT=true` 作为已确认的服务器策略字段，图片配置固定为 false。
  - _Requirements: 1.1, 1.4, 4.1, 6.2, 7.4_

- [x] 1.2 实现 endpoint allowlist、TLS、字段白名单、服务器原文策略、图片硬拒绝和提示注入隔离的 policy gate。
  - 在 `REPORT_VERIFY_LLM_ALLOW_ORIGINAL_TEXT=true` 时仅允许 capability 白名单内的 CERT/DRAFT 字段原文进入 payload，并执行脱敏、字段/字符/行数上限。
  - 文件、二进制、路径、图片、嵌入对象、工具调用和外部 URL 访问始终拒绝；`allow_images` 固定 false，任何 true 配置或任务覆盖均在网络请求前返回明确错误。
  - 仅允许服务器端策略授权的 capability 和字段进入 payload；拒绝请求体对 provider/key/host/TLS/外发策略的覆盖。
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 5.2_

- [x] 1.3 适配 CertAgent 当前的 OpenAI-compatible Bearer/user-key 请求、SSE/JSON 读取、JSON repair、响应上限和 `temperature=0`。
  - 完全复用 CertAgent 当前 model、Base URL、`/chat/completions` endpoint、请求 body、`data:`/`[DONE]`、content 提取和非流式 JSON 兼容策略；不导入或修改 CertAgent 生产模块。
  - repair 之后仍交给 ReportVerify 本地 Schema 和安全 validator，不把 CertAgent 语法兼容当作业务信任边界。
  - 覆盖 `data:`、`[DONE]`、非流式 `choices[0].message.content` 和真实响应上限，但测试只使用本地 stub。
  - _Requirements: 1.2, 1.3, 5.4, 8.2_

- [x] 1.4 实现逐次 timeout、有限重试、总墙钟超时不可重试回退，以及 provider 级断路器。
  - 区分可重试网络/429/暂时性 5xx 与鉴权、策略、总超时错误，并记录脱敏状态。
  - _Requirements: 5.1, 5.2, 5.3, 7.1_

- [x] 1.5 实现 JSON repair 后的严格 Schema、索引/同表/同组/一对一/枚举/置信度校验。
  - 修复仅作为语法容错；任何安全校验失败均不得猜测采纳。
  - _Requirements: 5.4, 3.1, 3.3_

- [x] 1.6 实现创建任务的 `llm_mode` 服务器 allowlist 和不可越权校验。
  - 支持 `off`、`candidate`、`explain`、`candidate_explain`，只接受 `REPORT_VERIFY_LLM_ALLOWED_MODES` 中的值；未知或未允许 mode 返回明确 400。
  - `REPORT_VERIFY_LLM_ALLOW_JOB_OVERRIDE=true` 只允许选择 mode，不允许覆盖 CertAgent provider/model/Base URL/key/user key、host/TLS、原文策略或固定图片 false。
  - _Requirements: 6.2, 6.3, 4.2_

### Phase 2: ReportVerify 能力接入

- [x] 2.1 在确定性 `compare_blocks` 之后增加 candidate orchestrator；仅处理残余候选，不改变原始 diff。
  - 保留 CERT/DRAFT 引用、同表同组、一对一和阈值护栏；在服务器原文策略 true 时可使用白名单字段原文，但不接受文件、路径、图片或二进制。
  - 将建议标为 pending，接受候选后只能进入确定性重核对。
  - _Requirements: 2.1, 2.2, 2.3, 3.1, 5.4_

- [x] 2.2 增加差异解释能力；仅读取既有 `VerifyDiff` 和允许的 CERT/DRAFT 字段原文，输出待展示解释。
  - 解释失败时保留确定性差异和原有 review note，不生成新字段值或自动 verdict；解释不记录原文到 trace。
  - _Requirements: 2.1, 2.3, 3.2, 4.1, 7.2_

- [x] 2.3 增加专业候选数据结构；未发布规则时保持 `discipline_pending`，不触发路由或审批。
  - 仅保存候选专业、理由和脱敏元数据，不写入最终 discipline。
  - _Requirements: 3.3, 7.1, 7.4_

- [x] 2.4 为候选接受设计 `accepted_for_recheck` 流程，接受后重跑确定性核对，不直接写最终 verdict。
  - 将人工接受作为显式状态，并确保重核对继续使用确定性 `same_value`、原始 CERT/DRAFT 值和既有门禁。
  - _Requirements: 3.4, 2.2, 2.3, 6.4_

- [x] 2.5 将 LLM 状态、候选、调用摘要和 warning 写入附属 trace，保持确定性 `verification.json` 字段兼容。
  - 仅记录 provider host、模型、Schema/policy 版本、状态、耗时和摘要哈希，不记录 secret、prompt、response、CERT/DRAFT 字段原文、图片或未授权正文。
  - _Requirements: 1.4, 2.3, 6.2, 7.1, 7.4_

### Phase 3: Web/任务兼容

- [x] 3.1 扩展 Job 的可选 LLM 状态和 summary 字段，保持旧 job.json 可恢复。
  - 新增字段必须可选，并保持 `queued → running → review → done` 与确定性 `failed` 语义不变。
  - _Requirements: 6.1, 6.2, 7.1, 7.4_

- [x] 3.2 在后台任务中以 `asyncio.to_thread` 调用 orchestrator，并加入独立 provider semaphore。
  - 确保 provider 调用不阻塞 FastAPI event loop，LLM 回退不把确定性成功任务标为整体 failed。
  - _Requirements: 6.3, 5.3, 7.2_

- [x] 3.3 保持现有 API 请求/响应兼容，按策略追加 LLM 字段；实现任务级 `llm_mode` 和受控只读 evidence 接口。
  - `POST /api/jobs` 可带 `llm_mode`，只接受服务器 allowlist 值；未知/未允许值 400。
  - 保留旧必需字段、diff key、决策校验和下载响应语义；新增字段只追加不重定义。
  - 任务请求不能修改 CertAgent provider/model/Base URL/endpoint/key/user key、host/TLS、字段原文授权或固定图片 false。
  - _Requirements: 6.1, 6.2, 6.3, 7.1, 7.4_

- [x] 3.4 保持全量人工确认和最终下载门禁；LLM failure/policy denied 只能产生 review warning。
  - 在 success、fallback、disabled 和 skipped_policy 状态下均不得绕过 `finalize_review`。
  - _Requirements: 3.4, 6.4, 7.2_

- [x] 3.5 确保反馈记忆只记录人工 verdict，不自动采纳 AI 建议。
  - 不将 LLM reason、候选或解释写为 accept/ignore，也不允许其改写规则。
  - _Requirements: 7.3, 2.2, 3.2_

### Phase 4: 验证与发布门禁

- [x] 4.1 运行现有 unittest 和真实脱敏样本回归，确认 mode=off 行为无变化。
  - 验证核心核对、Web、人工确认、下载门禁和确定性输出与原有行为兼容。
  - _Requirements: 8.1, 6.1, 6.4_

- [x] 4.2 使用本地 stub 覆盖与 CertAgent 当前一致的 SSE、非流式 JSON、model/endpoint/auth contract、凭据映射、429/5xx、鉴权失败、空响应、Schema invalid、总超时和 circuit open。
  - 测试只使用占位配置/受控 stub，不访问真实 provider、不读取或写入真实密钥、不发送真实外发数据。
  - _Requirements: 1.1, 1.2, 5.1, 5.2, 5.3, 5.4, 8.2_

- [x] 4.3 验证 payload/日志/trace/job/review 不包含 key、Authorization、prompt、response、图片或未授权原文；同时验证已授权字段原文不会进入本地日志/trace。
  - 验证 `REPORT_VERIFY_LLM_ALLOW_ORIGINAL_TEXT=true` 时仅白名单 CERT/DRAFT 字段原文可进入 stub payload；文件、路径、二进制、图片和工具调用被 policy gate 拦截。
  - 同时验证 host allowlist、TLS、脱敏 profile、字段白名单、提示注入隔离和凭据映射。
  - _Requirements: 1.4, 4.1, 4.2, 4.3, 4.4, 7.4, 8.3_

- [x] 4.4 验证候选守恒、CERT/DRAFT 方向、规则版本和人工下载门禁属性。
  - 使用自动化测试确认 LLM 成功、失败、策略拒绝和人工接受重核对均不改变确定性证据。
  - _Requirements: 2.2, 2.3, 3.1, 3.4, 6.4, 7.2_

- [x] 4.5 在凭据映射、host/TLS、mode allowlist、字段原文策略或图片硬拒绝的验证门禁未通过前保持生产开关关闭；形成回滚为 mode=off 的发布说明。
  - 将发布检查实现为可验证的配置/策略检查项，不写入任何真实密钥或 provider 凭据。
  - _Requirements: 8.4, 4.1, 4.2, 6.3_

### Correctness property tests

- [ ]* 4.6 编写 Property 1 的自动化测试：确定性规则不受影响。
  - 验证 LLM mode=off 与 LLM 失败回退对 `result.diffs`、CERT/DRAFT 值、规则版本和现有输出证据保持一致。
  - **Property 1: 确定性规则不受影响**
  - **Validates: Requirements 2.2, 2.3, 6.3**

- [ ]* 4.7 编写 Property 2 的自动化测试：归一化权威性。
  - 验证 LLM 不调用、不替代或修改 `normalize_for_compare`，格式差异只由已配置规则决定。
  - **Property 2: 归一化权威性**
  - **Validates: Requirements 2.2**

- [ ]* 4.8 编写 Property 3 的自动化测试：候选守恒。
  - 验证候选满足同表/兼容分组和一对一约束，且不删除或吞并原始行。
  - **Property 3: 候选守恒**
  - **Validates: Requirements 3.1, 5.4**

- [ ]* 4.9 编写 Property 4 的自动化测试：人工门禁。
  - 验证任意 LLM 状态都不能设置 `download_ready=true`，只有完整人工确认后的 `finalize_review` 才能下载。
  - **Property 4: 人工门禁**
  - **Validates: Requirements 3.4, 6.4**

- [ ]* 4.10 编写 Property 5 的自动化测试：方向不变。
  - 验证所有解释与建议始终将 CERT 作为应然值、DRAFT 作为实然值，不交换两者。
  - **Property 5: 方向不变**
  - **Validates: Requirements 2.2**

- [ ]* 4.11 编写 Property 6 的自动化测试：失败显式化。
  - 验证 provider failure、policy denial、schema failure 和 fallback 均产生状态码/trace warning，不静默变成无差异。
  - **Property 6: 失败显式化**
  - **Validates: Requirements 2.3, 5.2, 7.1, 7.2**

- [ ]* 4.12 编写 Property 7 的自动化测试：证据可回放。
  - 验证调用可用 job/trace id、规则/policy/schema 版本、请求摘要哈希和 provider 元数据识别，而无需秘密或完整原文。
  - **Property 7: 证据可回放**
  - **Validates: Requirements 1.3, 7.1, 7.4**

- [ ]* 4.13 编写 Property 8 的自动化测试：人工路由边界。
  - 验证专业候选不填充最终 discipline、不改变 `discipline_status` 且不触发审批。
  - **Property 8: 人工路由边界**
  - **Validates: Requirements 3.3**

- [ ]* 4.14 编写 Property 9 的自动化测试：接口兼容。
  - 验证 LLM mode=off 时现有 endpoint 必需字段、状态转移、差异 key 和下载门禁保持不变，新增字段只增不删。
  - **Property 9: 接口兼容**
  - **Validates: Requirements 6.1, 6.2, 6.4**

- [x] 4.15 编写原文允许、图片硬拒绝和任务级 mode 越权的策略回归测试。
  - 使用占位 CERT/DRAFT 字段验证 `REPORT_VERIFY_LLM_ALLOW_ORIGINAL_TEXT=true` 时白名单字段原文可进入本地 stub payload，但不会进入日志、trace、job 或 review。
  - 使用图片字段、图片对象、文件路径、二进制和工具调用意图验证固定 `allow_images=false` 在 provider 请求前返回 `llm_image_externalization_rejected`；任务级 `llm_mode` 不能绕过。
  - 验证创建任务只能选择服务器 allowlist 中的 mode，不能修改 provider/model/key/host/TLS 或外发策略。
  - **Validates: Requirements 4.1, 4.2, 6.3, 8.2, 8.3**

## Notes

- 任务应按已确认契约 → Phase 0 编码/验证门禁 → Phase 1 → Phase 2 → Phase 3 → Phase 4 执行；Phase 0 不是管理员再次确认，而是验证凭据映射、服务器策略和 CertAgent stub 契约；门禁未通过前保持生产 `REPORT_VERIFY_LLM_MODE=off`。
- 所有 LLM 失败、禁用、策略拒绝、图片硬拒绝、超时、熔断或 Schema 失败都必须回退到确定性流程，并显式保留 warning/trace。
- 任务只涉及编码、测试、配置和验证；不修改 CertAgent 生产代码，不改变 ReportVerify 确定性规则、差异算法、人工确认和下载门禁。
- 不添加真实密钥；配置、fixture、日志、trace、job、review 和测试均使用空值、占位符或本地 stub。字段原文策略测试只使用占位文本。
- `REPORT_VERIFY_LLM_ALLOW_ORIGINAL_TEXT=true` 只允许服务器字段白名单内的 CERT/DRAFT 原文进入 provider payload；图片、文件、路径、二进制和工具调用永远拒绝，任务 mode 不能放宽。
- 设计中的 Correctness Properties 1–9 已通过对应实现/验证任务覆盖；策略新增回归见 4.15。

## Task Dependency Graph

```json
{
  "phase_dependencies": [
    { "phase": "Phase 0", "depends_on": [], "gate": "Phase 0 validation tasks 0.1-0.3" },
    { "phase": "Phase 1", "depends_on": ["Phase 0"] },
    { "phase": "Phase 2", "depends_on": ["Phase 1"] },
    { "phase": "Phase 3", "depends_on": ["Phase 2"] },
    { "phase": "Phase 4", "depends_on": ["Phase 3"] }
  ],
  "waves": [
    { "id": 0, "phase": "Phase 0 implementation/validation gate", "tasks": ["0.1", "0.2", "0.3"] },
    { "id": 1, "phase": "Phase 1", "tasks": ["1.1", "1.2"] },
    { "id": 2, "phase": "Phase 1", "tasks": ["1.3", "1.4"] },
    { "id": 3, "phase": "Phase 1", "tasks": ["1.5", "1.6"] },
    { "id": 4, "phase": "Phase 2", "tasks": ["2.1", "2.2", "2.3"] },
    { "id": 5, "phase": "Phase 2", "tasks": ["2.4", "2.5"] },
    { "id": 6, "phase": "Phase 3", "tasks": ["3.1", "3.2"] },
    { "id": 7, "phase": "Phase 3", "tasks": ["3.3", "3.4", "3.5"] },
    { "id": 8, "phase": "Phase 4", "tasks": ["4.1", "4.2", "4.3", "4.4", "4.5"] },
    { "id": 9, "phase": "Phase 4 correctness properties and policy regression", "tasks": ["4.6", "4.7", "4.8", "4.9", "4.10", "4.11", "4.12", "4.13", "4.14", "4.15"] }
  ]
}
```
