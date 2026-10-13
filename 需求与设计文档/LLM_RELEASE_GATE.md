# ReportVerify LLM 发布门禁与回滚说明（任务 4.5）

本文只描述本地发布检查和安全回滚，不包含真实 API key、user key、provider 凭据、完整原文或真实 endpoint。所有示例值都是占位符；发布检查不访问 provider。

## 发布结论

当前安全生产基线是：

```text
REPORT_VERIFY_LLM_MODE=off
```

`off` 时 provider 不启用，ReportVerify 继续只运行确定性核对、人工确认和最终下载门禁。为防止任务请求把生产默认值放宽，生产配置还应将任务 allowlist 收窄为：

```text
REPORT_VERIFY_LLM_ALLOWED_MODES=off
```

这两项是生产关闭配置，不写入任何密钥或 endpoint 值。任务级 `llm_mode` 只能在服务器 allowlist 内选择；当 allowlist 只有 `off` 时，`candidate`、`explain` 和 `candidate_explain` 请求在创建/激活检查中被拒绝。

## 可执行检查

在项目根目录 `报告草稿准确性核对` 执行：

```powershell
python -m report_verify.llm.release_gate
```

检查只读取非敏感配置值；`REPORT_VERIFY_LLM_API_KEY` 和 `REPORT_VERIFY_LLM_USER_KEY` 只做变量名存在性检查，不读取其值。输出为 JSON 脱敏诊断，包含每项门禁的 `status`、固定错误码和 `provider_allowed`，不包含 URL、Authorization、prompt、response、CERT/DRAFT 原文或 secret。退出码含义：

- `0`：当前配置安全关闭（`mode=off`），或非 `off` 配置已经通过全部激活门禁；
- `1`：配置存在不能发布/激活的门禁失败；provider 保持关闭。

### 门禁清单

| 门禁 | 通过条件 | 未通过行为 |
|---|---|---|
| 生产 mode | mode 是允许值；默认/生产基线为 `off` | 无法判定时 fail closed，不发 provider 请求 |
| CertAgent 凭据映射 | `REPORT_VERIFY_LLM_BASE_URL`、`REPORT_VERIFY_LLM_MODEL`、`REPORT_VERIFY_LLM_API_KEY` 目标变量名可检查；user key 可选 | enabled mode 下映射缺失/不可检查，阻断 provider；检查不读取值 |
| host/TLS | endpoint host 在服务器 allowlist，TLS 默认要求 HTTPS；明文只有服务器显式配置才可用于受控环境 | 未批准 host、缺 allowlist、非 TLS 或 endpoint 无效，阻断 provider |
| 服务器 mode allowlist | 服务器默认 mode 自身在 `REPORT_VERIFY_LLM_ALLOWED_MODES` 中 | 默认 mode 未列入 allowlist，阻断 provider |
| 任务 mode/越权 | 任务只选择 allowlist 内 mode；不允许覆盖 provider、model、endpoint、key、host/TLS、原文或图片策略 | 返回 `llm_task_mode_not_allowed`，不发 provider 请求 |
| 字段原文策略 | enabled mode 使用已确认的 `REPORT_VERIFY_LLM_ALLOW_ORIGINAL_TEXT=true`，仍受字段/字符/行数和脱敏限制 | 策略为 false 或无效时阻断当前 provider 激活 |
| 图片硬拒绝 | `allow_images` 固定为 false；`true` 或歧义配置直接阻断 | 返回 `llm_image_externalization_rejected`，组装 payload/网络请求前停止 |
| 本地 stub/脱敏 | 只使用占位环境和 loopback/in-process stub | 不访问真实 provider，不落盘 secret、prompt、response 或原文 |

`LLMClient` 还在实际 transport 前重复执行 host/TLS、mode allowlist、原文策略和图片固定值检查；发布检查被绕过或运行时配置变化时，网络调用仍 fail closed。

## 受控启用前的本地示例

以下只是占位配置形态，不应把真实值写入仓库、文档、fixture、日志或提交记录：

```text
REPORT_VERIFY_LLM_MODE=candidate
REPORT_VERIFY_LLM_BASE_URL=https://<approved-host>/<approved-path>
REPORT_VERIFY_LLM_MODEL=<approved-model>
REPORT_VERIFY_LLM_API_KEY=<injected-secret-not-written>
REPORT_VERIFY_LLM_USER_KEY=<optional-injected-secret-not-written>
REPORT_VERIFY_LLM_ALLOWED_HOSTS=<approved-host>
REPORT_VERIFY_LLM_ALLOWED_MODES=off,candidate
REPORT_VERIFY_LLM_ALLOW_ORIGINAL_TEXT=true
REPORT_VERIFY_LLM_ALLOW_IMAGES=false
REPORT_VERIFY_LLM_ALLOW_PLAINTEXT=false
```

真实部署只通过受控环境/secret store 注入同一组 CertAgent 凭据。发布前用本地 placeholder/stub 运行门禁和相关 unittest；门禁通过不等于允许把真实凭据放进代码或测试，也不代替人工确认和下载门禁。

## 回滚

最小回滚动作只有一项：将服务器配置切回：

```text
REPORT_VERIFY_LLM_MODE=off
```

然后按部署方式重启/重新加载 ReportVerify 进程。切回后新任务不调用 provider，确定性 `verification.json`、人工 decisions、`finalize_review` 和下载门禁继续按原语义运行。若需要同时阻断任何任务级选择，可将 allowlist 收窄为 `REPORT_VERIFY_LLM_ALLOWED_MODES=off`；这不是恢复确定性流程所必需的第二把开关，而是额外的配置防护。

回滚不需要复制、轮换、打印或写入 key；不需要删除 CERT/DRAFT 原文；不需要访问 provider；不修改 CertAgent 生产代码。旧任务中的 LLM sidecar 仍只作为脱敏附属证据读取，不会改变确定性差异或人工确认状态。

## 发布阻断条件

以下任意一项未通过，发布状态必须保持 `mode=off`：凭据变量名映射检查、host/TLS allowlist、服务器/任务 mode allowlist、字段原文策略、图片固定拒绝、脱敏证据检查。阻断结果只记录固定错误码和非敏感状态；禁止用请求参数临时放宽策略，也禁止以真实 provider 联调替代本地 stub 验证。
