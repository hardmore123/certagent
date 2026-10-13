"""本地 provider stub 的 CertAgent 兼容错误路径测试（任务 4.2）。

测试只使用 loopback-only 的进程内 transport stub、占位配置和本地 fixture：
不打开 socket，不访问真实 provider，不读取、复制、打印或持久化真实凭据/项目数据。
基础 request/SSE/JSON/repair/响应上限及配置映射测试位于 test_llm_client.py、
test_certagent_llm_contract.py 和 test_llm_config.py；本模块补充错误、重试、总超时、
熔断，以及 provider 响应进入严格 Schema 校验的契约覆盖。
"""
from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from report_verify.llm.circuit import CircuitBreaker
from report_verify.llm.client import (
    ERROR_ATTEMPT_TIMEOUT,
    ERROR_AUTH_FAILED,
    ERROR_CIRCUIT_OPEN,
    ERROR_TOTAL_TIMEOUT,
    LLMAuthFailed,
    LLMClient,
    LLMCircuitOpen,
    LLMClientError,
    LLMTotalTimeout,
    repair_json,
)
from report_verify.llm.config import LLMSettings
from report_verify.llm.schemas import (
    CAPABILITY_CANDIDATE,
    ERROR_SAFETY_REJECTED,
    CandidateContext,
    validate_response,
)

sys.path.insert(0, str(Path(__file__).parent))
from llm_contract_stub import StubResponse, response_from_fixture  # noqa: E402

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "llm_contract"
_PLACEHOLDER_API_KEY = "PLACEHOLDER-API-KEY-DO-NOT-USE"
_PLACEHOLDER_USER_KEY = "PLACEHOLDER-USER-KEY-DO-NOT-USE"
_SCHEMA_VERSION = "reportverify-llm-v1"


class _SequenceStub:
    """loopback-only 的可编排 transport stub，不打开网络连接。"""

    def __init__(self, responses: list[StubResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def __call__(
        self,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, str],
        json: object,
        timeout: float | None,
        stream: bool,
    ) -> StubResponse:
        parsed = urlsplit(url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise AssertionError(f"contract stub rejects non-loopback URL: {url}")
        if not self._responses:
            raise AssertionError("contract stub received an unexpected extra request")
        self.calls.append({
            "url": url,
            "headers": dict(headers),
            "params": dict(params),
            "json": json,
            "timeout": timeout,
            "stream": stream,
        })
        return self._responses.pop(0)


def _settings(**overrides: str) -> LLMSettings:
    env = {
        "REPORT_VERIFY_LLM_MODE": "candidate_explain",
        "REPORT_VERIFY_LLM_BASE_URL": "http://127.0.0.1:8765/v1",
        "REPORT_VERIFY_LLM_MODEL": "stub-model",
        "REPORT_VERIFY_LLM_API_KEY": _PLACEHOLDER_API_KEY,
        "REPORT_VERIFY_LLM_USER_KEY": _PLACEHOLDER_USER_KEY,
        "REPORT_VERIFY_LLM_ALLOWED_HOSTS": "127.0.0.1",
        "REPORT_VERIFY_LLM_ALLOW_PLAINTEXT": "true",
        "REPORT_VERIFY_LLM_CIRCUIT_FAILURE_THRESHOLD": "10",
    }
    env.update(overrides)
    return LLMSettings.from_env(env)


def _success_response() -> StubResponse:
    return response_from_fixture(FIXTURE_DIR / "non_stream_json.txt")


def _sse_content_response(content: str) -> StubResponse:
    chunk = {
        "id": "stub-sse",
        "choices": [{"delta": {"content": content}}],
    }
    return StubResponse((
        "data: " + json.dumps(chunk, ensure_ascii=False),
        "data: [DONE]",
    ))


class RetryAndFailureContractTests(unittest.TestCase):
    def test_429_is_retried_and_success_keeps_attempt_metadata(self):
        stub = _SequenceStub([
            StubResponse((), status_code=429, reason="Too Many Requests"),
            _success_response(),
        ])
        client = LLMClient(
            _settings(REPORT_VERIFY_LLM_MAX_RETRY="2"),
            transport=stub,
            sleep=lambda _seconds: None,
        )

        result = client.complete_raw([{"role": "user", "content": "stub"}])

        self.assertEqual(result.metadata.attempts, 2)
        self.assertEqual(len(stub.calls), 2)
        self.assertEqual(result.metadata.status, "success")
        self.assertEqual(result.metadata.transport, "json")
        self.assertEqual(stub.calls[0]["url"], "http://127.0.0.1:8765/v1/chat/completions")
        self.assertEqual(stub.calls[0]["json"]["temperature"], 0)  # type: ignore[index]
        self.assertTrue(stub.calls[0]["json"]["stream"])  # type: ignore[index]

    def test_transient_5xx_errors_are_retried_until_success(self):
        stub = _SequenceStub([
            StubResponse((), status_code=503, reason="Service Unavailable"),
            StubResponse((), status_code=502, reason="Bad Gateway"),
            _success_response(),
        ])
        client = LLMClient(
            _settings(REPORT_VERIFY_LLM_MAX_RETRY="2"),
            transport=stub,
            sleep=lambda _seconds: None,
        )

        result = client.complete_raw([{"role": "user", "content": "stub"}])

        self.assertEqual(len(stub.calls), 3)
        self.assertEqual(result.metadata.attempts, 3)
        self.assertEqual(result.metadata.status, "success")

    def test_auth_failures_are_not_retried(self):
        for status in (401, 403):
            with self.subTest(status=status):
                stub = _SequenceStub([
                    StubResponse((), status_code=status, reason="Unauthorized"),
                    _success_response(),
                ])
                client = LLMClient(
                    _settings(REPORT_VERIFY_LLM_MAX_RETRY="2"),
                    transport=stub,
                    sleep=lambda _seconds: None,
                )

                with self.assertRaises(LLMAuthFailed) as ctx:
                    client.complete_raw([{"role": "user", "content": "stub"}])

                self.assertEqual(ctx.exception.code, ERROR_AUTH_FAILED)
                self.assertEqual(len(stub.calls), 1)

    def test_empty_response_is_retried_without_becoming_success(self):
        empty = response_from_fixture(FIXTURE_DIR / "sse_reasoning_only.txt")
        stub = _SequenceStub([empty, _success_response()])
        client = LLMClient(
            _settings(REPORT_VERIFY_LLM_MAX_RETRY="1"),
            transport=stub,
            sleep=lambda _seconds: None,
        )

        result = client.complete_raw([{"role": "user", "content": "stub"}])

        self.assertEqual(len(stub.calls), 2)
        self.assertEqual(result.metadata.attempts, 2)
        self.assertTrue(result.content)


class TimeoutAndCircuitContractTests(unittest.TestCase):
    def test_expired_read_deadline_is_attempt_timeout_and_not_retried(self):
        stub = _SequenceStub([_success_response(), _success_response()])
        client = LLMClient(
            _settings(REPORT_VERIFY_LLM_MAX_RETRY="2"),
            transport=stub,
            sleep=lambda _seconds: None,
        )

        with self.assertRaises(LLMClientError) as ctx:
            client.complete_raw(
                [{"role": "user", "content": "stub"}],
                deadline=time.time() - 1,
            )

        self.assertEqual(ctx.exception.code, ERROR_ATTEMPT_TIMEOUT)
        self.assertEqual(len(stub.calls), 1)

    def test_total_wall_clock_timeout_stops_further_retries(self):
        # 使用假时钟推进退避，不等待真实时间；HTTP 错误本身由本地 stub 返回。
        now = [1000.0]

        def clock() -> float:
            return now[0]

        def advance_sleep(seconds: float) -> None:
            now[0] += seconds

        stub = _SequenceStub([
            StubResponse((), status_code=503, reason="Service Unavailable"),
            StubResponse((), status_code=503, reason="Service Unavailable"),
            _success_response(),
        ])
        client = LLMClient(
            _settings(
                REPORT_VERIFY_LLM_MAX_RETRY="4",
                REPORT_VERIFY_LLM_TOTAL_TIMEOUT="1",
            ),
            transport=stub,
            sleep=advance_sleep,
            clock=clock,
        )

        with self.assertRaises(LLMTotalTimeout) as ctx:
            client.complete_raw([{"role": "user", "content": "stub"}])

        self.assertEqual(ctx.exception.code, ERROR_TOTAL_TIMEOUT)
        self.assertEqual(len(stub.calls), 2)
        self.assertLess(now[0], 1002.0)

    def test_open_circuit_rejects_before_provider_request(self):
        breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=60)
        breaker.record_failure()
        stub = _SequenceStub([_success_response()])
        client = LLMClient(_settings(), transport=stub, breaker=breaker)

        with self.assertRaises(LLMCircuitOpen) as ctx:
            client.complete_raw([{"role": "user", "content": "stub"}])

        self.assertEqual(ctx.exception.code, ERROR_CIRCUIT_OPEN)
        self.assertEqual(len(stub.calls), 0)


class StubToSchemaContractTests(unittest.TestCase):
    def test_repair_then_strict_schema_rejects_invalid_provider_response(self):
        invalid_body = {
            "schema_version": _SCHEMA_VERSION,
            "pairs": [{
                "cert_index": 0,
                "draft_index": 0,
                "confidence": 1.5,
                "reason": "占位响应",
            }],
        }
        raw_content = "provider prose\n```json\n" + json.dumps(
            invalid_body, ensure_ascii=False
        ) + "\n```\ntrailing prose"
        stub = _SequenceStub([_sse_content_response(raw_content)])
        client = LLMClient(
            _settings(REPORT_VERIFY_LLM_MAX_RETRY="2"),
            transport=stub,
            sleep=lambda _seconds: None,
        )

        raw_result = client.complete_raw([{"role": "user", "content": "stub"}])
        repaired = repair_json(raw_result.content)
        outcome = validate_response(
            CAPABILITY_CANDIDATE,
            repaired,
            CandidateContext(
                cert_indices=frozenset({0}),
                draft_indices=frozenset({0}),
                cert_table={0: 1},
                draft_table={0: 1},
                cert_group={0: "A"},
                draft_group={0: "A"},
            ),
            schema_version=_SCHEMA_VERSION,
        )

        self.assertEqual(len(stub.calls), 1)
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, ERROR_SAFETY_REJECTED)
        self.assertEqual(raw_result.metadata.attempts, 1)


if __name__ == "__main__":
    unittest.main()
