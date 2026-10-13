"""Task 4.5 release-gate checks.

All enabled configurations use placeholder values and an in-process transport stub;
no test opens a socket or reads a secret value.
"""
from __future__ import annotations

import json
import unittest
from collections.abc import Iterator, Mapping
from urllib.parse import urlsplit

from report_verify.llm.client import LLMClient, LLMClientError
from report_verify.llm.release_gate import (
    ERROR_HOST_TLS_GATE,
    ERROR_IMAGE_GATE,
    ERROR_MAPPING_GATE,
    ERROR_ORIGINAL_TEXT_GATE,
    ERROR_TASK_OVERRIDE_GATE,
    evaluate_release_gate,
)
from report_verify.llm.policy import ERROR_POLICY_DENIED
from report_verify.llm.config import LLMSettings


_PLACEHOLDER_API_KEY = "PLACEHOLDER-API-KEY-DO-NOT-USE"
_PLACEHOLDER_USER_KEY = "PLACEHOLDER-USER-KEY-DO-NOT-USE"


class _NameOnlyEnvironment(Mapping[str, str]):
    """Expose safe values while failing if a secret value is read."""

    _secret_names = frozenset({
        "REPORT_VERIFY_LLM_API_KEY",
        "REPORT_VERIFY_LLM_USER_KEY",
    })

    def __init__(self, values: Mapping[str, str], present: set[str] | None = None):
        self._values = dict(values)
        self._present = set(self._values) | set(present or ())
        self.value_reads: list[str] = []
        self.presence_checks: list[str] = []

    def __contains__(self, name: object) -> bool:
        if not isinstance(name, str):
            return False
        self.presence_checks.append(name)
        return name in self._present

    def __getitem__(self, name: str) -> str:
        if name in self._secret_names:
            self.value_reads.append(name)
            raise AssertionError(f"secret value was read: {name}")
        self.value_reads.append(name)
        return self._values[name]

    def __iter__(self) -> Iterator[str]:
        return iter(self._present)

    def __len__(self) -> int:
        return len(self._present)


class _StubResponse:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def iter_lines(self, decode_unicode: bool = True):
        del decode_unicode
        yield 'data: {"choices":[{"delta":{"content":"{}"}}]}'
        yield "data: [DONE]"


class _RecordingTransport:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, url, **kwargs):
        del kwargs
        if urlsplit(url).hostname not in {"127.0.0.1", "localhost"}:
            raise AssertionError("release-gate stub received non-loopback URL")
        self.calls.append(url)
        return _StubResponse()


def _enabled_env(**overrides: str) -> _NameOnlyEnvironment:
    values = {
        "REPORT_VERIFY_LLM_MODE": "candidate",
        "REPORT_VERIFY_LLM_BASE_URL": "https://approved.example/v1",
        "REPORT_VERIFY_LLM_MODEL": "placeholder-model",
        "REPORT_VERIFY_LLM_ALLOWED_HOSTS": "approved.example",
        "REPORT_VERIFY_LLM_ALLOWED_MODES": "off,candidate",
        "REPORT_VERIFY_LLM_ALLOW_ORIGINAL_TEXT": "true",
        "REPORT_VERIFY_LLM_ALLOW_IMAGES": "false",
        "REPORT_VERIFY_LLM_ALLOW_PLAINTEXT": "false",
        "REPORT_VERIFY_LLM_ALLOW_JOB_OVERRIDE": "true",
    }
    values.update(overrides)
    return _NameOnlyEnvironment(
        values,
        present={
            "REPORT_VERIFY_LLM_API_KEY",
            "REPORT_VERIFY_LLM_USER_KEY",
        },
    )


class DefaultAndRedactionTests(unittest.TestCase):
    def test_empty_environment_is_safe_closed_without_provider_permission(self):
        result = evaluate_release_gate({})

        self.assertTrue(result.release_safe)
        self.assertEqual(result.mode, "off")
        self.assertEqual(result.effective_mode, "off")
        self.assertFalse(result.provider_allowed)
        self.assertEqual(
            result.diagnostics()["network_requests_made"], False
        )

    def test_gate_never_reads_secret_values_or_reports_configuration_values(self):
        environment = _enabled_env()

        result = evaluate_release_gate(environment)
        diagnostics = result.diagnostics()
        serialized = json.dumps(diagnostics, ensure_ascii=False, sort_keys=True)

        self.assertTrue(result.provider_allowed)
        self.assertFalse(environment.value_reads.__contains__("REPORT_VERIFY_LLM_API_KEY"))
        self.assertFalse(environment.value_reads.__contains__("REPORT_VERIFY_LLM_USER_KEY"))
        self.assertNotIn(_PLACEHOLDER_API_KEY, serialized)
        self.assertNotIn(_PLACEHOLDER_USER_KEY, serialized)
        self.assertNotIn("approved.example", serialized)
        self.assertFalse(diagnostics["secret_values_read"])
        self.assertFalse(diagnostics["secret_values_persisted"])


class ActivationGateTests(unittest.TestCase):
    def test_missing_credential_mapping_blocks_provider(self):
        environment = _enabled_env()
        environment = _NameOnlyEnvironment(
            {key: value for key, value in environment._values.items()},
            present=set(),
        )

        result = evaluate_release_gate(environment)

        self.assertFalse(result.provider_allowed)
        self.assertIn(ERROR_MAPPING_GATE, result.blocked_codes)

    def test_unapproved_host_and_plain_http_block_provider(self):
        for overrides in (
            {"REPORT_VERIFY_LLM_BASE_URL": "https://unapproved.example/v1"},
            {"REPORT_VERIFY_LLM_BASE_URL": "http://approved.example/v1"},
        ):
            with self.subTest(overrides=overrides):
                result = evaluate_release_gate(_enabled_env(**overrides))
                self.assertFalse(result.provider_allowed)
                self.assertIn(ERROR_HOST_TLS_GATE, result.blocked_codes)

    def test_server_mode_not_allowlisted_blocks_default_activation(self):
        result = evaluate_release_gate(
            _enabled_env(REPORT_VERIFY_LLM_ALLOWED_MODES="off")
        )

        self.assertFalse(result.provider_allowed)
        self.assertIn("llm_release_mode_allowlist_failed", result.blocked_codes)

    def test_task_mode_cannot_expand_server_allowlist_or_override_provider(self):
        off_only = _enabled_env(
            REPORT_VERIFY_LLM_MODE="off",
            REPORT_VERIFY_LLM_ALLOWED_MODES="off",
        )
        denied_mode = evaluate_release_gate(
            off_only,
            requested_mode="candidate",
        )
        self.assertFalse(denied_mode.provider_allowed)
        self.assertIn(ERROR_TASK_OVERRIDE_GATE, denied_mode.blocked_codes)

        denied_override = evaluate_release_gate(
            _enabled_env(),
            requested_mode="candidate",
            override_fields={"model": "attacker-model"},
        )
        self.assertFalse(denied_override.provider_allowed)
        self.assertIn(ERROR_TASK_OVERRIDE_GATE, denied_override.blocked_codes)

        denied_override_without_mode = evaluate_release_gate(
            _enabled_env(),
            override_fields={"model": "attacker-model"},
        )
        self.assertFalse(denied_override_without_mode.provider_allowed)
        self.assertIn(
            ERROR_TASK_OVERRIDE_GATE,
            denied_override_without_mode.blocked_codes,
        )

    def test_original_text_policy_must_be_explicitly_approved_for_enabled_modes(self):
        result = evaluate_release_gate(
            _enabled_env(REPORT_VERIFY_LLM_ALLOW_ORIGINAL_TEXT="false")
        )

        self.assertFalse(result.provider_allowed)
        self.assertIn(ERROR_ORIGINAL_TEXT_GATE, result.blocked_codes)

    def test_image_true_or_ambiguous_configuration_blocks_before_activation(self):
        for image_value in ("true", "maybe"):
            with self.subTest(image_value=image_value):
                result = evaluate_release_gate(
                    _enabled_env(REPORT_VERIFY_LLM_ALLOW_IMAGES=image_value)
                )
                self.assertFalse(result.provider_allowed)
                self.assertIn(ERROR_IMAGE_GATE, result.blocked_codes)


class RuntimeBoundaryTests(unittest.TestCase):
    def test_client_does_not_call_transport_when_host_tls_gate_fails(self):
        environment = {
            "REPORT_VERIFY_LLM_MODE": "candidate",
            "REPORT_VERIFY_LLM_BASE_URL": "http://127.0.0.1:8765/v1",
            "REPORT_VERIFY_LLM_MODEL": "placeholder-model",
            "REPORT_VERIFY_LLM_API_KEY": _PLACEHOLDER_API_KEY,
            "REPORT_VERIFY_LLM_ALLOWED_HOSTS": "127.0.0.1",
            # allow_plaintext deliberately remains false.
        }
        settings = LLMSettings.from_env(environment)
        transport = _RecordingTransport()
        client = LLMClient(settings, transport=transport)

        with self.assertRaises(LLMClientError) as ctx:
            client.complete_raw([{"role": "user", "content": "{}"}])

        self.assertEqual(ctx.exception.code, ERROR_POLICY_DENIED)
        self.assertEqual(transport.calls, [])

    def test_client_does_not_call_transport_when_original_text_policy_fails(self):
        environment = {
            "REPORT_VERIFY_LLM_MODE": "candidate",
            "REPORT_VERIFY_LLM_BASE_URL": "https://approved.example/v1",
            "REPORT_VERIFY_LLM_MODEL": "placeholder-model",
            "REPORT_VERIFY_LLM_API_KEY": _PLACEHOLDER_API_KEY,
            "REPORT_VERIFY_LLM_ALLOWED_HOSTS": "approved.example",
            "REPORT_VERIFY_LLM_ALLOW_ORIGINAL_TEXT": "false",
        }
        settings = LLMSettings.from_env(environment)
        transport = _RecordingTransport()
        client = LLMClient(settings, transport=transport)

        with self.assertRaises(LLMClientError) as ctx:
            client.complete_raw([{"role": "user", "content": "{}"}])

        self.assertEqual(ctx.exception.code, ERROR_POLICY_DENIED)
        self.assertEqual(transport.calls, [])

    def test_client_does_not_call_transport_when_image_policy_was_overridden(self):
        environment = {
            "REPORT_VERIFY_LLM_MODE": "candidate",
            "REPORT_VERIFY_LLM_BASE_URL": "https://approved.example/v1",
            "REPORT_VERIFY_LLM_MODEL": "placeholder-model",
            "REPORT_VERIFY_LLM_API_KEY": _PLACEHOLDER_API_KEY,
            "REPORT_VERIFY_LLM_ALLOWED_HOSTS": "approved.example",
            "REPORT_VERIFY_LLM_ALLOW_IMAGES": "true",
        }
        settings = LLMSettings.from_env(environment)
        transport = _RecordingTransport()
        client = LLMClient(settings, transport=transport)

        with self.assertRaises(LLMClientError) as ctx:
            client.complete_raw([{"role": "user", "content": "{}"}])

        self.assertEqual(ctx.exception.code, ERROR_POLICY_DENIED)
        self.assertEqual(transport.calls, [])


if __name__ == "__main__":
    unittest.main()
