"""LLM 运行时 client 的单元测试（任务 1.3）。

这些测试只使用本地 loopback-only stub 传输，不开 socket、不访问真实 provider、
不读取/复制/打印真实 API key 或 user key。占位凭据仅用于断言脱敏。
"""
from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from report_verify.llm.client import (
    ERROR_ATTEMPT_TIMEOUT,
    ERROR_HTTP_ERROR,
    ERROR_MISCONFIGURED,
    ERROR_RESPONSE_TOO_LARGE,
    TRANSPORT_JSON,
    TRANSPORT_SSE,
    LLMClient,
    LLMClientError,
    LLMEmptyResponse,
    LLMResponseTooLarge,
    read_openai_compatible_stream,
    repair_json,
)
from report_verify.llm.config import LLMSettings

# 复用契约 stub 的响应形态（loopback-only、不开 socket）。
sys.path.insert(0, str(Path(__file__).parent))
from llm_contract_stub import StubResponse, response_from_fixture  # noqa: E402

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "llm_contract"

# 仅用于断言脱敏的占位凭据；不是任何真实密钥。
_PLACEHOLDER_API_KEY = "PLACEHOLDER-API-KEY-DO-NOT-USE"
_PLACEHOLDER_USER_KEY = "PLACEHOLDER-USER-KEY-DO-NOT-USE"


class _RecordingTransport:
    """loopback-only 的 client 传输 stub。

    匹配 :class:`LLMClient` 使用的 ``transport(url, *, headers, params, json,
    timeout, stream)`` 签名，记录一次请求并返回 fixture 响应。拒绝非 loopback
    URL，保证任何误配置的真实 provider URL 在联网前就失败。
    """

    def __init__(self, response: StubResponse) -> None:
        self.response = response
        self.calls: list[dict] = []

    def __call__(self, url, *, headers, params, json, timeout, stream):
        parsed = urlsplit(url)
        if parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise AssertionError(f"client 测试 stub 拒绝非 loopback URL: {url}")
        self.calls.append({
            "url": url,
            "headers": dict(headers),
            "params": dict(params),
            "json": json,
            "timeout": timeout,
            "stream": stream,
        })
        return self.response


def _settings(**overrides) -> LLMSettings:
    env = {
        "REPORT_VERIFY_LLM_MODE": "candidate_explain",
        "REPORT_VERIFY_LLM_BASE_URL": "http://127.0.0.1:8765/v1",
        "REPORT_VERIFY_LLM_MODEL": "stub-model",
        "REPORT_VERIFY_LLM_API_KEY": _PLACEHOLDER_API_KEY,
        "REPORT_VERIFY_LLM_USER_KEY": _PLACEHOLDER_USER_KEY,
        # Local loopback stub only; production defaults remain TLS-only.
        "REPORT_VERIFY_LLM_ALLOW_PLAINTEXT": "true",
        "REPORT_VERIFY_LLM_ALLOWED_HOSTS": "127.0.0.1",
    }
    env.update(overrides)
    return LLMSettings.from_env(env)


def _messages() -> list[dict[str, str]]:
    return [{"role": "user", "content": "Return the contract fixture."}]


class RequestAssemblyTests(unittest.TestCase):
    def test_request_reuses_certagent_endpoint_auth_and_generation_flags(self):
        transport = _RecordingTransport(
            response_from_fixture(FIXTURE_DIR / "sse_fenced_json.txt")
        )
        client = LLMClient(_settings(), transport=transport)
        result = client.complete_raw(_messages())

        self.assertEqual(len(transport.calls), 1)
        call = transport.calls[0]
        self.assertEqual(call["url"], "http://127.0.0.1:8765/v1/chat/completions")
        self.assertEqual(call["headers"]["Authorization"], f"Bearer {_PLACEHOLDER_API_KEY}")
        self.assertEqual(call["headers"]["Content-Type"], "application/json")
        self.assertEqual(call["params"], {"user_key": _PLACEHOLDER_USER_KEY})
        self.assertEqual(call["json"]["model"], "stub-model")
        self.assertEqual(call["json"]["messages"], _messages())
        self.assertEqual(call["json"]["temperature"], 0)
        self.assertTrue(call["json"]["stream"])
        self.assertTrue(call["stream"])
        self.assertEqual(call["timeout"], float(client.settings.timeout_seconds))
        self.assertTrue(result.content)

    def test_default_body_omits_max_tokens(self):
        transport = _RecordingTransport(
            response_from_fixture(FIXTURE_DIR / "sse_fenced_json.txt")
        )
        client = LLMClient(_settings(), transport=transport)
        client.complete_raw(_messages())
        body = transport.calls[0]["json"]
        # 默认（max_tokens=0）时请求体不含该键，保持既有行为不变。
        self.assertNotIn("max_tokens", body)
        self.assertEqual(body["model"], "stub-model")
        self.assertEqual(body["messages"], _messages())
        self.assertEqual(body["temperature"], 0)
        self.assertTrue(body["stream"])

    def test_positive_max_tokens_added_to_body_without_changing_other_fields(self):
        transport = _RecordingTransport(
            response_from_fixture(FIXTURE_DIR / "sse_fenced_json.txt")
        )
        client = LLMClient(
            _settings(REPORT_VERIFY_LLM_MAX_TOKENS="1024"), transport=transport
        )
        client.complete_raw(_messages())
        body = transport.calls[0]["json"]
        self.assertEqual(body["max_tokens"], 1024)
        # 其余字段保持不变。
        self.assertEqual(body["model"], "stub-model")
        self.assertEqual(body["messages"], _messages())
        self.assertEqual(body["temperature"], 0)
        self.assertTrue(body["stream"])

    def test_base_url_trailing_slash_is_normalized(self):
        transport = _RecordingTransport(
            response_from_fixture(FIXTURE_DIR / "non_stream_json.txt")
        )
        client = LLMClient(
            _settings(REPORT_VERIFY_LLM_BASE_URL="http://127.0.0.1:8765/v1/"),
            transport=transport,
        )
        client.complete_raw(_messages())
        self.assertEqual(
            transport.calls[0]["url"], "http://127.0.0.1:8765/v1/chat/completions"
        )

    def test_user_key_optional_but_bearer_required(self):
        transport = _RecordingTransport(
            response_from_fixture(FIXTURE_DIR / "non_stream_json.txt")
        )
        client = LLMClient(
            _settings(REPORT_VERIFY_LLM_USER_KEY=""), transport=transport
        )
        client.complete_raw(_messages())
        call = transport.calls[0]
        self.assertEqual(call["params"], {})
        self.assertEqual(call["headers"]["Authorization"], f"Bearer {_PLACEHOLDER_API_KEY}")

    def test_misconfigured_settings_raise_before_network(self):
        transport = _RecordingTransport(
            response_from_fixture(FIXTURE_DIR / "non_stream_json.txt")
        )
        client = LLMClient(
            _settings(REPORT_VERIFY_LLM_API_KEY=""), transport=transport
        )
        with self.assertRaises(LLMClientError) as ctx:
            client.complete_raw(_messages())
        self.assertEqual(ctx.exception.code, ERROR_MISCONFIGURED)
        # 未发起任何请求。
        self.assertEqual(len(transport.calls), 0)


class SseReadingTests(unittest.TestCase):
    def test_sse_content_chunks_accumulated_in_order_ignoring_reasoning(self):
        transport = _RecordingTransport(
            response_from_fixture(FIXTURE_DIR / "sse_fenced_json.txt")
        )
        client = LLMClient(_settings(), transport=transport)
        result = client.complete_raw(_messages())
        self.assertEqual(
            result.content,
            '```json\n{"changes":[{"变更项目":"型号","变更前":"P-1","变更后":"P-2"}]}\n```',
        )
        self.assertEqual(result.metadata.transport, TRANSPORT_SSE)
        # reasoning_content 从不作为 content 输出。
        self.assertNotIn("stub reasoning is not output content", result.content)

    def test_reasoning_only_stream_yields_empty_and_raises(self):
        transport = _RecordingTransport(
            response_from_fixture(FIXTURE_DIR / "sse_reasoning_only.txt")
        )
        client = LLMClient(_settings(), transport=transport)
        with self.assertRaises(LLMEmptyResponse):
            client.complete_raw(_messages())

    def test_malformed_lines_are_skipped(self):
        transport = _RecordingTransport(
            response_from_fixture(FIXTURE_DIR / "sse_malformed_lines.txt")
        )
        client = LLMClient(_settings(), transport=transport)
        result = client.complete_raw(_messages())
        self.assertEqual(result.content, "good chunk")


class NonStreamReadingTests(unittest.TestCase):
    def test_non_stream_message_content_is_read(self):
        transport = _RecordingTransport(
            response_from_fixture(FIXTURE_DIR / "non_stream_json.txt")
        )
        client = LLMClient(_settings(), transport=transport)
        result = client.complete_raw(_messages())
        self.assertEqual(
            result.content,
            '{"changes":[{"变更项目":"认证标准","变更前":"GB-1","变更后":"GB-2"}]}',
        )
        self.assertEqual(result.metadata.transport, TRANSPORT_JSON)


class ResponseLimitTests(unittest.TestCase):
    def test_accumulated_content_over_limit_is_rejected(self):
        transport = _RecordingTransport(
            response_from_fixture(FIXTURE_DIR / "sse_fenced_json.txt")
        )
        client = LLMClient(
            _settings(REPORT_VERIFY_LLM_MAX_RESPONSE_BYTES="8"), transport=transport
        )
        with self.assertRaises(LLMResponseTooLarge) as ctx:
            client.complete_raw(_messages())
        self.assertEqual(ctx.exception.code, ERROR_RESPONSE_TOO_LARGE)

    def test_single_line_over_limit_is_rejected(self):
        big = "x" * 100
        lines = (f'data: {{"choices":[{{"delta":{{"content":"{big}"}}}}]}}',)
        resp = StubResponse(lines)
        content_bytes = 20
        # 直接测底层 reader。
        with self.assertRaises(LLMResponseTooLarge):
            read_openai_compatible_stream(resp, max_response_bytes=content_bytes)


class DeadlineTests(unittest.TestCase):
    def test_deadline_exceeded_during_read_raises_attempt_timeout(self):
        transport = _RecordingTransport(
            response_from_fixture(FIXTURE_DIR / "sse_fenced_json.txt")
        )
        client = LLMClient(_settings(), transport=transport)
        # deadline 已过期。
        with self.assertRaises(LLMClientError) as ctx:
            client.complete_raw(_messages(), deadline=time.time() - 1)
        self.assertEqual(ctx.exception.code, ERROR_ATTEMPT_TIMEOUT)


class HttpErrorTests(unittest.TestCase):
    def test_http_error_status_is_normalized_without_body(self):
        resp = StubResponse(("ignored",), status_code=503, reason="Service Unavailable")
        transport = _RecordingTransport(resp)
        client = LLMClient(_settings(), transport=transport)
        with self.assertRaises(LLMClientError) as ctx:
            client.complete_raw(_messages())
        self.assertEqual(ctx.exception.code, ERROR_HTTP_ERROR)
        # 状态码可出现，响应正文不可出现。
        self.assertIn("503", str(ctx.exception))

    def test_transport_exception_is_normalized(self):
        def boom(url, **kwargs):
            raise ConnectionError("secret-host-detail should not leak")

        client = LLMClient(_settings(), transport=boom)
        with self.assertRaises(LLMClientError) as ctx:
            client.complete_raw(_messages())
        self.assertEqual(ctx.exception.code, ERROR_HTTP_ERROR)
        self.assertNotIn("secret-host-detail", str(ctx.exception))


class RepairJsonTests(unittest.TestCase):
    def test_repair_strips_fence_and_extracts_object(self):
        raw = (FIXTURE_DIR / "repair_with_prose.txt").read_text(encoding="utf-8")
        repaired = repair_json(raw)
        self.assertEqual(
            json.loads(repaired),
            {"pairs": [{
                "orig_index": 0,
                "plm_index": 1,
                "confidence": 0.94,
                "reason": "同表同组的占位候选",
            }]},
        )

    def test_repair_is_syntax_only_no_schema(self):
        # repair 不做 Schema：不合法业务结构也原样提取，交给 1.5。
        repaired = repair_json('```json\n{"unexpected": true}\n```')
        self.assertEqual(json.loads(repaired), {"unexpected": True})


class MetadataRedactionTests(unittest.TestCase):
    def test_metadata_contains_no_secret_or_query(self):
        transport = _RecordingTransport(
            response_from_fixture(FIXTURE_DIR / "sse_fenced_json.txt")
        )
        client = LLMClient(_settings(), transport=transport)
        result = client.complete_raw(_messages())
        meta = result.metadata
        # 序列化元数据不得含凭据或 URL query。
        serialized = json.dumps({
            "provider_host": meta.provider_host,
            "model": meta.model,
            "schema_version": meta.schema_version,
            "attempts": meta.attempts,
            "elapsed_ms": meta.elapsed_ms,
            "transport": meta.transport,
            "status": meta.status,
            "request_sha256": meta.request_sha256,
            "response_sha256": meta.response_sha256,
            "fallback_reason": meta.fallback_reason,
        }, ensure_ascii=False)
        self.assertNotIn(_PLACEHOLDER_API_KEY, serialized)
        self.assertNotIn(_PLACEHOLDER_USER_KEY, serialized)
        self.assertNotIn("user_key", serialized)
        self.assertNotIn("Authorization", serialized)
        self.assertEqual(meta.provider_host, "127.0.0.1")
        self.assertEqual(meta.model, "stub-model")
        self.assertEqual(meta.attempts, 1)
        self.assertEqual(len(meta.request_sha256), 64)
        self.assertEqual(len(meta.response_sha256), 64)

    def test_request_hash_covers_body_not_credentials(self):
        transport = _RecordingTransport(
            response_from_fixture(FIXTURE_DIR / "sse_fenced_json.txt")
        )
        # 两个不同 api_key、相同 body -> 相同 request 哈希（哈希只覆盖 body）。
        r1 = LLMClient(_settings(REPORT_VERIFY_LLM_API_KEY="key-a"), transport=transport)
        h1 = r1.complete_raw(_messages()).metadata.request_sha256

        transport2 = _RecordingTransport(
            response_from_fixture(FIXTURE_DIR / "sse_fenced_json.txt")
        )
        r2 = LLMClient(_settings(REPORT_VERIFY_LLM_API_KEY="key-b"), transport=transport2)
        h2 = r2.complete_raw(_messages()).metadata.request_sha256
        self.assertEqual(h1, h2)


if __name__ == "__main__":
    unittest.main()
