"""任务 4.15：原文允许、图片硬拒绝、任务级 mode 越权的策略回归。

本文件把 design.md 已确认的三条服务器策略固化为面向"provider 请求边界"的
回归断言，验证 Requirements 4.1、4.2、6.3、8.2、8.3：

1. ``REPORT_VERIFY_LLM_ALLOW_ORIGINAL_TEXT=true`` 时，白名单 CERT/DRAFT 字段
   原文可进入**本地 stub payload**（离开本机的结构化 body），但绝不进入脱敏
   evidence（trace/job/review 的落盘边界由任务 4.3 覆盖，这里补齐 candidate
   能力的 payload/evidence 边界）。
2. 图片字段/图片对象/文件路径/二进制/工具调用意图在**任何 provider 请求之前**
   被硬拒绝：图片精确返回 ``llm_image_externalization_rejected``，其余返回
   ``llm_policy_denied``；固定 ``allow_images=false`` 无法被环境或任务级
   ``llm_mode`` 绕过。
3. 创建任务只能选择服务器 allowlist 中的 mode，且不能修改 provider/model/
   key/host/TLS 或外发策略。

所有测试只使用占位/脱敏数据；不打开 socket、不访问真实 provider、不读取或
写入真实密钥。provider 交互均由 loopback-only transport stub 捕获，任何非本地
URL 都会让 stub 主动失败。这些断言与任务 0.2/1.6/3.3/4.3/4.5 互补，不重复其
底层单元覆盖。
"""
from __future__ import annotations

import json
import unittest
from urllib.parse import urlsplit

from report_verify.llm.client import LLMClient, LLMClientError
from report_verify.llm.config import LLMSettings
from report_verify.llm.evidence import (
    ERROR_EVIDENCE_INVALID,
    EvidenceValidationError,
    LLMEvidence,
    build_evidence,
)
from report_verify.llm.jobmode import authorize_job_creation, policy_from_settings
from report_verify.llm.policy import (
    ERROR_IMAGE_REJECTED,
    ERROR_POLICY_DENIED,
    ERROR_TASK_MODE_NOT_ALLOWED,
    PolicyError,
    ServerLLMPolicy,
    authorize_outbound,
    build_minimal_payload,
)


# 故意的非敏感占位值；不是任何真实凭据或真实 CERT/DRAFT 原文。
_API_KEY = "PLACEHOLDER-API-KEY-4-15"
_USER_KEY = "PLACEHOLDER-USER-KEY-4-15"
_CERT_VALUE = "PLACEHOLDER-CERT-VALUE-4-15"
_DRAFT_VALUE = "PLACEHOLDER-DRAFT-VALUE-4-15"
_IMAGE_SENTINEL = "IMAGE-BYTES-MUST-NOT-LEAVE-4-15"
_SCHEMA = "reportverify-llm-v1"


class _StubResponse:
    """最小 requests.Response 兼容响应；不开 socket。"""

    status_code = 200

    def __init__(self, content: str) -> None:
        self._line = json.dumps(
            {"choices": [{"message": {"content": content}}]}, ensure_ascii=False
        )

    def raise_for_status(self) -> None:
        return None

    def iter_lines(self, decode_unicode: bool = True):
        del decode_unicode
        yield self._line


class _RecordingTransport:
    """只捕获 loopback 调用；任何非本地 host 都主动失败。"""

    def __init__(self, content: str = "{}") -> None:
        self.response = _StubResponse(content)
        self.calls: list[dict] = []

    def __call__(self, url, *, headers, params, json, timeout, stream):
        if urlsplit(url).hostname not in {"127.0.0.1", "localhost"}:
            raise AssertionError(f"policy regression stub rejected non-loopback URL: {url}")
        self.calls.append(
            {"url": url, "headers": dict(headers), "params": dict(params), "json": json}
        )
        return self.response


def _settings(**overrides) -> LLMSettings:
    env = {
        "REPORT_VERIFY_LLM_MODE": "candidate",
        "REPORT_VERIFY_LLM_BASE_URL": "http://127.0.0.1:8765/v1",
        "REPORT_VERIFY_LLM_MODEL": "local-stub-model",
        "REPORT_VERIFY_LLM_API_KEY": _API_KEY,
        "REPORT_VERIFY_LLM_USER_KEY": _USER_KEY,
        "REPORT_VERIFY_LLM_ALLOWED_HOSTS": "127.0.0.1",
        "REPORT_VERIFY_LLM_ALLOW_PLAINTEXT": "true",
        "REPORT_VERIFY_LLM_ALLOWED_MODES": "off,candidate,explain,candidate_explain",
        "REPORT_VERIFY_LLM_REDACTION_PROFILE": "standard",
    }
    env.update(overrides)
    return LLMSettings.from_env(env)


def _candidate_content() -> str:
    return json.dumps(
        {
            "schema_version": _SCHEMA,
            "pairs": [
                {"cert_index": 0, "draft_index": 0, "confidence": 0.9, "reason": "候选"}
            ],
        },
        ensure_ascii=False,
    )


class OriginalTextAllowedButNotLeakedTests(unittest.TestCase):
    """Requirements 4.1, 8.3：原文可外发但不进入脱敏 evidence（candidate 能力）。"""

    def test_whitelisted_original_text_reaches_outbound_body_only(self):
        settings = _settings()
        policy = policy_from_settings(settings)
        transport = _RecordingTransport(_candidate_content())
        client = LLMClient(settings, transport=transport)

        payload = build_minimal_payload(
            policy,
            "candidate",
            [
                {
                    "cert_index": 0,
                    "draft_index": 0,
                    "block_type": "safety_list",
                    "cert_value": _CERT_VALUE,
                    "draft_value": _DRAFT_VALUE,
                }
            ],
            rules_version="normalized-v2",
        )
        # 原文只在授权的结构化 payload 中（allow_original_text=true）。
        row = payload["rows"][0]
        self.assertEqual(row["cert_value"], _CERT_VALUE)
        self.assertEqual(row["draft_value"], _DRAFT_VALUE)
        self.assertTrue(payload["metadata"]["allow_original_text"])
        self.assertFalse(payload["metadata"]["allow_images"])

        client.complete_raw(
            [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            schema_version=_SCHEMA,
            request_id="trace-4-15",
        )

        self.assertEqual(len(transport.calls), 1)
        call = transport.calls[0]
        # 凭据只在 transport 信封（header/query），绝不在 JSON body。
        self.assertEqual(call["headers"]["Authorization"], f"Bearer {_API_KEY}")
        self.assertEqual(call["params"], {"user_key": _USER_KEY})
        body_text = json.dumps(call["json"], ensure_ascii=False)
        self.assertIn(_CERT_VALUE, body_text)  # 授权原文允许离开本机
        self.assertNotIn(_API_KEY, body_text)
        self.assertNotIn(_USER_KEY, body_text)
        self.assertNotIn("Authorization", body_text)

    def test_original_text_dropped_when_server_policy_disallows(self):
        policy = policy_from_settings(_settings(REPORT_VERIFY_LLM_ALLOW_ORIGINAL_TEXT="false"))
        payload = build_minimal_payload(
            policy,
            "candidate",
            [{"cert_index": 0, "draft_index": 0, "cert_value": _CERT_VALUE, "block_type": "s"}],
            rules_version="normalized-v2",
        )
        row = payload["rows"][0]
        self.assertNotIn("cert_value", row)
        self.assertEqual(row["block_type"], "s")
        self.assertFalse(payload["metadata"]["allow_original_text"])

    def test_evidence_never_carries_original_text_for_candidate(self):
        # 合法候选只带结构化引用（block_type/table_idx），evidence 序列化后不含原文。
        evidence = build_evidence(
            mode="candidate",
            status="success",
            capabilities=["candidate"],
            candidates=[
                {
                    "candidate_key": "cand-4-15",
                    "capability": "candidate",
                    "cert_ref": {"block_type": "safety_list", "table_idx": 0, "row_idx": 1},
                    "draft_ref": {"block_type": "safety_list", "table_idx": 0, "row_idx": 2},
                    "confidence": 0.9,
                    "reason": "仅供人工复核",
                    "status": "pending",
                }
            ],
            policy_version="policy-v1",
            schema_version=_SCHEMA,
            rule_version="normalized-v2",
            trace_id="trace-4-15",
            job_id="job-4-15",
        )
        serialized = json.dumps(evidence.to_dict(), ensure_ascii=False)
        self.assertNotIn(_CERT_VALUE, serialized)
        self.assertNotIn(_DRAFT_VALUE, serialized)
        self.assertNotIn("cert_value", serialized)
        self.assertNotIn("draft_value", serialized)

    def test_evidence_rejects_candidate_that_smuggles_original_text(self):
        # 即使调用方试图把原文塞进 candidate，evidence 校验边界也必须在落盘/读取时
        # 拒绝，绝不让 CERT/DRAFT 原文进入 evidence sidecar。
        smuggled = {
            "mode": "candidate",
            "status": "success",
            "capabilities": ["candidate"],
            "candidates": [
                {
                    "candidate_key": "cand-bad",
                    "capability": "candidate",
                    "cert_ref": {"block_type": "s", "table_idx": 0},
                    "draft_ref": {"block_type": "s", "table_idx": 0},
                    "confidence": 0.5,
                    "reason": "x",
                    "cert_value": _CERT_VALUE,
                }
            ],
        }
        with self.assertRaises(EvidenceValidationError) as ctx:
            LLMEvidence.from_mapping(smuggled)
        self.assertEqual(ctx.exception.code, ERROR_EVIDENCE_INVALID)


class ImageAndForbiddenContentHardRejectionTests(unittest.TestCase):
    """Requirements 4.2, 8.2：外发禁令在 provider 请求前生效，任务级 mode 不能绕过。"""

    def _forbidden_rows(self) -> dict[str, tuple[dict, str]]:
        # 映射：标签 -> (payload 行, 期望错误码)。
        return {
            "image_field": ({"cert_value": "x", "image": _IMAGE_SENTINEL}, ERROR_IMAGE_REJECTED),
            "image_url": ({"image_url": "http://x/p.png"}, ERROR_IMAGE_REJECTED),
            "nested_image_object": ({"photo": {"data": _IMAGE_SENTINEL}}, ERROR_IMAGE_REJECTED),
            "file_path": ({"file_path": "C:/private/draft.docx"}, ERROR_POLICY_DENIED),
            "bare_path": ({"path": "/private/draft.docx"}, ERROR_POLICY_DENIED),
            "binary_value": ({"cert_value": b"\x00\x01"}, ERROR_POLICY_DENIED),
            "binary_field": ({"binary": b"\x00\x01"}, ERROR_POLICY_DENIED),
            "tool_call": ({"tool_calls": [{"name": "fetch"}]}, ERROR_POLICY_DENIED),
            "external_url": ({"external_url": "https://evil.example"}, ERROR_POLICY_DENIED),
            "embedded_object": ({"embedded_object": {"type": "image"}}, ERROR_POLICY_DENIED),
        }

    def test_forbidden_payloads_are_rejected_before_any_provider_request(self):
        settings = _settings()
        policy = policy_from_settings(settings)
        for label, (row, expected_code) in self._forbidden_rows().items():
            with self.subTest(content=label):
                transport = _RecordingTransport(_candidate_content())
                client = LLMClient(settings, transport=transport)
                with self.assertRaises(PolicyError) as ctx:
                    payload = build_minimal_payload(
                        policy, "candidate", [row], rules_version="normalized-v2"
                    )
                    # 若 payload 组装未拒绝，则任何后续调用都不得先于策略发出。
                    client.complete_raw(
                        [{"role": "user", "content": json.dumps(payload)}],
                        schema_version=_SCHEMA,
                        request_id="trace-4-15",
                    )
                self.assertEqual(ctx.exception.code, expected_code)
                # 关键回归：provider 请求从未发出。
                self.assertEqual(transport.calls, [])

    def test_image_intent_precisely_flagged_by_authorize_outbound(self):
        policy = policy_from_settings(_settings())
        auth = authorize_outbound(
            policy,
            capability="candidate",
            payload_sample={"rows": [{"images": ["p.png"]}]},
        )
        self.assertFalse(auth.authorized)
        self.assertFalse(auth.images_allowed)
        self.assertEqual(auth.error_code, ERROR_IMAGE_REJECTED)

    def test_env_allow_images_true_is_forced_false_and_blocks_provider(self):
        settings = _settings(REPORT_VERIFY_LLM_ALLOW_IMAGES="true")
        # 固定安全常量：环境试图开启也归一为 False，并标记配置无效。
        self.assertFalse(settings.allow_images)
        self.assertFalse(settings.image_policy_valid)
        self.assertFalse(policy_from_settings(settings).allow_images)

        transport = _RecordingTransport(_candidate_content())
        client = LLMClient(settings, transport=transport)
        with self.assertRaises(LLMClientError) as ctx:
            client.complete_raw(
                [{"role": "user", "content": "{}"}],
                schema_version=_SCHEMA,
                request_id="trace-4-15",
            )
        self.assertEqual(ctx.exception.code, ERROR_POLICY_DENIED)
        self.assertEqual(transport.calls, [])

    def test_job_mode_selection_cannot_reenable_images(self):
        settings = _settings(REPORT_VERIFY_LLM_MODE="candidate_explain")

        # 选择一个 allowlist 中的能力 mode 不改变固定图片策略。
        decision = authorize_job_creation(settings, {"llm_mode": "candidate_explain"})
        self.assertEqual(decision.mode, "candidate_explain")

        policy = policy_from_settings(settings)
        auth = authorize_outbound(
            policy,
            capability="explain",
            payload_sample={"rows": [{"image_url": "http://x/p.png"}]},
        )
        self.assertFalse(auth.authorized)
        self.assertEqual(auth.error_code, ERROR_IMAGE_REJECTED)

        # 任务请求试图把 allow_images 一并打开，直接硬拒绝。
        with self.assertRaises(PolicyError) as ctx:
            authorize_job_creation(
                settings, {"llm_mode": "candidate", "allow_images": True}
            )
        self.assertEqual(ctx.exception.code, ERROR_TASK_MODE_NOT_ALLOWED)


class JobModeSelectionCannotOverrideServerPolicyTests(unittest.TestCase):
    """Requirements 6.3, 8.2：任务只能选 allowlist mode，不能改 provider/外发策略。"""

    def test_only_allowlisted_modes_are_accepted(self):
        settings = _settings(
            REPORT_VERIFY_LLM_MODE="candidate_explain",
            REPORT_VERIFY_LLM_ALLOWED_MODES="off,candidate",
        )
        self.assertEqual(
            authorize_job_creation(settings, {"llm_mode": "candidate"}).mode, "candidate"
        )
        # explain 不在 allowlist -> 明确拒绝。
        with self.assertRaises(PolicyError) as ctx:
            authorize_job_creation(settings, {"llm_mode": "explain"})
        self.assertEqual(ctx.exception.code, ERROR_TASK_MODE_NOT_ALLOWED)

    def test_unknown_mode_is_rejected(self):
        settings = _settings()
        with self.assertRaises(PolicyError) as ctx:
            authorize_job_creation(settings, {"llm_mode": "vision"})
        self.assertEqual(ctx.exception.code, ERROR_TASK_MODE_NOT_ALLOWED)

    def test_provider_credential_and_externalization_overrides_are_rejected(self):
        settings = _settings()
        for bad_field in (
            "base_url",
            "provider",
            "endpoint",
            "model",
            "api_key",
            "user_key",
            "allowed_hosts",
            "host",
            "tls",
            "allow_plaintext",
            "allow_original_text",
            "allow_images",
            "redaction_profile",
        ):
            with self.subTest(field=bad_field):
                with self.assertRaises(PolicyError) as ctx:
                    authorize_job_creation(
                        settings, {"llm_mode": "candidate", bad_field: "x"}
                    )
                self.assertEqual(ctx.exception.code, ERROR_TASK_MODE_NOT_ALLOWED)

    def test_selecting_mode_does_not_mutate_derived_provider_policy(self):
        # 任务级选择只返回 mode；派生策略的 host/TLS/原文/图片字段保持服务器值。
        settings = _settings(REPORT_VERIFY_LLM_MODE="candidate_explain")
        policy = policy_from_settings(settings)

        decision = authorize_job_creation(settings, {"llm_mode": "candidate"})
        self.assertEqual(decision.mode, "candidate")

        after = policy_from_settings(settings)
        self.assertEqual(after.allowed_hosts, policy.allowed_hosts)
        self.assertEqual(after.allow_original_text, policy.allow_original_text)
        self.assertEqual(after.allow_plaintext, policy.allow_plaintext)
        self.assertFalse(after.allow_images)
        # 派生策略对象根本不承载凭据字段。
        for secret in ("api_key", "user_key", "base_url", "model"):
            self.assertFalse(hasattr(after, secret))

    def test_job_override_disabled_allows_only_server_default_mode(self):
        settings = _settings(
            REPORT_VERIFY_LLM_MODE="candidate",
            REPORT_VERIFY_LLM_ALLOW_JOB_OVERRIDE="false",
        )
        self.assertEqual(
            authorize_job_creation(settings, {"llm_mode": "candidate"}).mode, "candidate"
        )
        with self.assertRaises(PolicyError) as ctx:
            authorize_job_creation(settings, {"llm_mode": "explain"})
        self.assertEqual(ctx.exception.code, ERROR_TASK_MODE_NOT_ALLOWED)


if __name__ == "__main__":
    unittest.main()
