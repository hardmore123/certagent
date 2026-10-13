# Requirements Document

## Introduction

为独立 ReportVerify 项目增加可选的、可审计的 LLM 建议能力，复用 CertAgent 的 OpenAI-compatible 调用契约，但不改变 CERT/DRAFT 的确定性字段核对、归一化、差异判定、批注对象、人工确认和最终下载门禁。LLM 失败、禁用或不获授权时必须保持确定性流程可用。

## Glossary

- **CERT**：认证基准文档或其中用于核对的确定性字段值。
- **DRAFT**：报告草稿文档或其中待核对的字段值。
- **LLM**：Large Language Model，大语言模型；本文指可选的外部或本地 OpenAI-compatible provider 能力。
- **LLM mode**：控制 LLM 集成行为的运行模式，包括关闭或启用等状态。
- **deterministic evidence**：由确定性定位、解析、归一化和差异比较流程产生的、可追溯且不受 LLM 结果改写的核对证据。
- **provider**：提供 OpenAI-compatible LLM 调用服务的服务端或服务实例。
- **candidate**：确定性匹配后保留、供 LLM 辅助判断或人工处理的结构化候选项。
- **credential injection**：从本机受控环境变量或受控 secret store 读取 CertAgent 当前同一组凭据，并映射到 ReportVerify 配置名；不表示复制或暴露凭据值。
- **server policy**：仅由 ReportVerify 服务端配置决定的外发、provider、TLS/host、mode allowlist 和凭据策略；普通任务请求不能放宽。
- **image hard rejection**：发现图片或图片外发意图时，在 provider 网络请求前返回策略错误且不发送替代内容；本功能不支持图片。

## Requirements

### Requirement 1: CertAgent 接口、模型和凭据适配

**User Story:** 作为系统管理员，我希望 ReportVerify 完全复用 CertAgent 当前的模型、OpenAI-compatible 调用契约和同一组受控凭据，以便接入批准的 provider 而不复制真实密钥。

#### Acceptance Criteria

1. WHEN LLM mode 被启用 THEN 系统 SHALL 使用与 CertAgent 当前完全相同的模型、Base URL、`/chat/completions` endpoint、请求参数、Bearer/user-key 鉴权方式和受控凭据；ReportVerify SHALL 通过本机受控环境变量或受控 secret 注入完成 `LLM_BASE_URL`、`LLM_MODEL`、`LLM_API_KEY`、`LLM_USER_KEY` 到对应 `REPORT_VERIFY_LLM_*` 配置的映射，不得从代码、文档、fixture、请求体或回复读取硬编码真实密钥。
2. WHEN 发起调用 THEN 系统 SHALL 使用 CertAgent 当前请求契约，包括 `temperature=0`、优先流式响应和同一 endpoint/auth 语义；任务级请求不得覆盖模型、Base URL、endpoint、API key、user key、host/TLS allowlist 或鉴权方式。
3. WHEN provider 返回响应 THEN 系统 SHALL 严格遵从 CertAgent 当前 SSE/JSON 提取和 JSON repair/解析兼容策略，包括 `data:`、`[DONE]`、`choices[0].delta.content` 和 `choices[0].message.content`；repair 后仍 SHALL 执行 ReportVerify 本地 capability Schema、安全校验和人工门禁。
4. WHEN 记录配置或调用证据 THEN 系统 SHALL 只记录脱敏的 provider host、模型、Schema、状态和摘要哈希，不记录 API key、user key、Authorization、完整 URL query、prompt、response 原文或字段原文。

### Requirement 2: 确定性规则优先

**User Story:** 作为认证工程师，我希望 LLM 只能辅助确定性核对，而不能改变应然/实然基准或无意义差异边界。

#### Acceptance Criteria

1. WHEN 生成任何 LLM payload THEN 系统 SHALL 先完成 CERT 定位、DRAFT 解析、版本化归一化和 `compare_blocks`，并只发送被允许的结构化候选或已有差异。
2. WHEN LLM 返回结果 THEN 系统 SHALL 不允许它修改 `normalize_for_compare`、规则版本、CERT/DRAFT 值、最终 `VerifyDiff` 分类或差异方向。
3. WHEN LLM 调用成功、失败、超时或被拒绝 THEN 原始确定性差异证据 SHALL 保持可追溯且不得被清空或静默改成无差异。

### Requirement 3: 允许的 LLM 能力边界

**User Story:** 作为审核人，我希望 AI 只提出候选和解释，并保留人工决定权。

#### Acceptance Criteria

1. WHEN 使用候选匹配能力 THEN 系统 SHALL 仅处理确定性匹配后的残余候选，执行同表、兼容分组、一对一和置信度阈值护栏，并将候选标为 pending。
2. WHEN 使用差异解释能力 THEN 系统 SHALL 只解释已存在的差异，不能创建新的 CERT/DRAFT 字段值或自动 verdict。
3. WHEN 使用专业候选能力 THEN 系统 SHALL 只产生候选专业和理由，`discipline_status` 仍为 `discipline_pending`，不得自动分配、审批或触发外部流程。
4. WHEN 人工接受候选匹配 THEN 系统 SHALL 先进入显式的 accepted-for-recheck 状态并重新调用确定性核对；不得直接将候选变成最终差异或完成任务。

### Requirement 4: 外发授权、字段原文和隐私边界

**User Story:** 作为数据管理员，我希望在已确认的服务器策略下允许必要的 CERT/DRAFT 字段原文外发，同时硬性阻断文件、图片、路径和工具调用，并能证明实际发送了什么。

#### Acceptance Criteria

1. WHEN 服务器策略 `REPORT_VERIFY_LLM_ALLOW_ORIGINAL_TEXT=true` 且 capability 已被允许 THEN 系统 SHALL 允许发送 capability 字段白名单内的 CERT/DRAFT 字段原文，并在发送前执行脱敏 profile、字段/字符/行数上限和结构化 payload 校验；当该策略为 false 时 SHALL 跳过或拒绝需要原文的 capability。
2. WHEN payload 或任务请求包含原始文档二进制、文件路径、图片、嵌入对象、图片发送意图或工具/URL 访问要求 THEN 系统 SHALL 在发起 provider 网络请求前硬拒绝；图片策略固定为 `false`，不得通过环境变量、任务级 `llm_mode` 或请求字段覆盖。
3. WHEN 允许发送原文或 provider endpoint 被使用 THEN 系统 SHALL 按 capability 校验服务器授权、脱敏 profile、字段/尺寸上限、与 CertAgent 一致的 TLS/host allowlist 和授权审计信息；任务级请求不得放宽这些策略或提供新的凭据。
4. WHEN 文档内容包含提示注入、URL、代码块或外部指令 THEN 系统 SHALL 将其视为普通数据，不得改变系统规则、endpoint、工具权限、凭据、外发策略或人工确认边界。

### Requirement 5: 超时、重试、熔断和结构化响应

**User Story:** 作为运行维护人员，我希望 provider 不稳定时任务不会卡死，并能安全回退。

#### Acceptance Criteria

1. WHEN 发生连接错误、429 或暂时性 5xx THEN 系统 SHALL 按配置有限重试并受单次超时和总墙钟时限约束。
2. WHEN 到达总墙钟 deadline、发生鉴权/策略拒绝或结构化 Schema 校验失败 THEN 系统 SHALL 停止重试或采纳，并执行确定性回退。
3. WHEN provider 连续失败达到阈值 THEN 系统 SHALL 打开 provider 级冷却断路器，在冷却期间不发请求，并在 trace 中记录 `circuit_open`。
4. WHEN provider 返回围栏 JSON、前后杂文、越界索引、重复行、跨表/跨组 pair、未知 diff key 或非法 confidence THEN 系统 SHALL 先使用 CertAgent 当前兼容的语法 repair/提取方式，再执行 ReportVerify 严格 Schema 和本地安全校验；校验失败不得猜测采纳或改变确定性证据。

### Requirement 6: FastAPI、任务级 mode 与后台任务兼容

**User Story:** 作为现有 Web 用户，我希望关闭 LLM 时原有上传、差异、确认和下载接口行为不变，同时可以在创建任务时选择服务器允许的 LLM mode，而不能改变安全配置。

#### Acceptance Criteria

1. WHEN LLM mode 为 off THEN 现有 `/api/jobs`、`/api/jobs/{id}`、`/diffs`、`/row-diffs`、`/decisions`、`/memory` 和 `/result/{kind}` 的必需字段、状态转移、差异 key 和下载门禁 SHALL 保持兼容。
2. WHEN LLM mode 非 off THEN 系统 SHALL 只追加 `llm_mode`、`llm_status`、建议数量、warning 数量和可选 evidence 字段，不删除或重定义既有字段。
3. WHEN 创建任务请求带有 `llm_mode` THEN 系统 SHALL 仅接受服务器 `REPORT_VERIFY_LLM_ALLOWED_MODES` allowlist 中的 `off|candidate|explain|candidate_explain`；允许的 mode 才能生效，未知或未允许 mode SHALL 返回明确 400。任务级选择不得覆盖 provider、模型、Base URL、endpoint、凭据、host/TLS allowlist、`REPORT_VERIFY_LLM_ALLOW_ORIGINAL_TEXT` 或固定为 false 的图片策略。
4. WHEN 后台任务调用 LLM THEN 调用 SHALL 运行在 worker/thread 和独立 provider 并发限制内，不阻塞 FastAPI event loop；LLM 回退不得将确定性成功任务误标为整体 failed。
5. WHEN 全部确定性差异尚未完成人工确认 THEN 无论 LLM mode/status 为何，下载接口 SHALL 继续返回不可下载状态。

### Requirement 7: 任务证据、错误状态和反馈边界

**User Story:** 作为审核人，我希望知道 AI 做了什么、为什么回退，并能继续使用确定性证据完成确认。

#### Acceptance Criteria

1. WHEN 一次 LLM 调用完成或回退 THEN job summary 和 trace SHALL 显示 capability、状态、attempts、耗时、Schema/policy 版本和分类错误码。
2. WHEN LLM 失败或 policy denied THEN 任务 SHALL 继续暴露确定性差异；界面或 API SHALL 明确显示“无 AI 建议/已回退”而不是静默成功。
3. WHEN 写入反馈记忆 THEN 只有人工 verdict 和人工备注 SHALL 写入反馈；LLM 建议不能自动成为 accept/ignore，也不能改写规则。
4. WHEN 需要审计回放 THEN 通过 job/trace id、规则版本、policy 版本、Schema 版本和摘要哈希 SHALL 能判断调用路径，而不需要保存秘密或完整敏感正文。

### Requirement 8: 测试与发布门禁

**User Story:** 作为维护者，我希望该功能可在不访问真实 provider 的情况下验证安全和兼容性。

#### Acceptance Criteria

1. WHEN 运行现有测试集且 LLM mode 为 off THEN 既有核心、Web、人工确认和真实样本回归 SHALL 保持通过。
2. WHEN 使用本地 provider stub THEN 系统 SHALL 覆盖与 CertAgent 当前完全一致的模型/API endpoint、Bearer/user-key 注入映射、SSE/JSON、JSON repair、重试、总超时、断路器、Schema invalid、字段原文策略和 fallback 路径，且测试不使用真实密钥或真实外发。
3. WHEN 安全测试发现日志、trace、异常或 job 文件包含 secret、prompt、response、CERT/DRAFT 字段原文、图片或未授权数据 THEN 发布 SHALL 被阻断；测试 SHALL 证明图片请求在网络调用前硬拒绝。
4. WHEN 同 CertAgent 的凭据注入映射、host/TLS 校验、服务器 mode allowlist 或脱敏策略未通过验证 THEN 生产启用 SHALL 被阻断并保持 mode=off；任何任务级请求都不能绕过该门禁。

## Non-Functional Requirements

- 可回放：规则版本、policy 版本、Schema 版本和 provider 调用摘要必须与结果关联。
- 可降级：LLM 不可用不影响确定性核对、人工确认和证据保全。
- 可扩展：候选匹配、解释和专业候选通过 capability 隔离，未来新增能力不能默认获得文件、图片、路径、工具调用或超出服务器策略的原文权限。
- 凭据隔离：ReportVerify 只通过本机受控环境变量/secret 注入复用 CertAgent 同一组凭据；凭据映射不能被请求体、任务 mode、fixture 或日志覆盖或泄露。
- 原文与图片边界：服务器策略 `REPORT_VERIFY_LLM_ALLOW_ORIGINAL_TEXT=true` 时仅允许白名单 CERT/DRAFT 字段原文；图片固定 false，任何图片外发必须硬拒绝且不发网络请求。
- 任务级可选：创建任务可选择服务器 allowlist 中的 `llm_mode`，但不能覆盖 provider、model、endpoint、key、host/TLS、原文或图片策略。
- 独立边界：不导入或修改 CertAgent 生产模块，不接入 KOA/Tims，不改变现有部署。
