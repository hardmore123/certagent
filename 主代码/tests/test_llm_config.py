"""LLM 运行时配置对象 :class:`LLMSettings` 的单元测试（任务 1.1）。

这些测试只使用占位环境变量和本地对象；不访问真实 provider，不读取/复制/
打印真实 API key 或 user key，也不发起任何网络请求。
"""
from __future__ import annotations

import json
import unittest

from report_verify.llm.config import (
    ALL_MODES,
    CERTAGENT_TO_REPORT_VERIFY_ENV,
    LLMConfigurationError,
    LLMSettings,
    STATUS_DISABLED,
    STATUS_MISCONFIGURED,
    STATUS_READY,
)

# 占位凭据值，仅用于断言脱敏；不是任何真实密钥。
_PLACEHOLDER_API_KEY = "PLACEHOLDER-API-KEY-DO-NOT-USE"
_PLACEHOLDER_USER_KEY = "PLACEHOLDER-USER-KEY-DO-NOT-USE"


def _enabled_env(**overrides) -> dict[str, str]:
    env = {
        "REPORT_VERIFY_LLM_MODE": "candidate_explain",
        "REPORT_VERIFY_LLM_BASE_URL": "https://approved.example/v1",
        "REPORT_VERIFY_LLM_MODEL": "configured-model",
        "REPORT_VERIFY_LLM_API_KEY": _PLACEHOLDER_API_KEY,
        "REPORT_VERIFY_LLM_USER_KEY": _PLACEHOLDER_USER_KEY,
        "REPORT_VERIFY_LLM_ALLOWED_HOSTS": "approved.example",
    }
    env.update(overrides)
    return env


class DefaultsTests(unittest.TestCase):
    def test_empty_env_defaults_to_off_and_disabled(self):
        settings = LLMSettings.from_env({})
        self.assertEqual(settings.mode, "off")
        self.assertFalse(settings.enabled)
        self.assertEqual(settings.status(), STATUS_DISABLED)

    def test_default_server_policy_flags(self):
        settings = LLMSettings.from_env({})
        # 已确认的默认服务器策略。
        self.assertTrue(settings.allow_original_text)
        self.assertTrue(settings.allow_job_override)
        self.assertFalse(settings.allow_images)
        self.assertFalse(settings.allow_plaintext)

    def test_default_limits_match_design(self):
        settings = LLMSettings.from_env({})
        self.assertEqual(settings.timeout_seconds, 60)
        self.assertEqual(settings.max_retry, 2)
        self.assertEqual(settings.total_timeout_seconds, 120)
        self.assertEqual(settings.circuit_failure_threshold, 3)
        self.assertEqual(settings.circuit_cooldown_seconds, 60)

    def test_mapping_matches_task_0_1_names(self):
        self.assertEqual(
            dict(CERTAGENT_TO_REPORT_VERIFY_ENV),
            {
                "LLM_BASE_URL": "REPORT_VERIFY_LLM_BASE_URL",
                "LLM_MODEL": "REPORT_VERIFY_LLM_MODEL",
                "LLM_API_KEY": "REPORT_VERIFY_LLM_API_KEY",
                "LLM_USER_KEY": "REPORT_VERIFY_LLM_USER_KEY",
            },
        )


class StatusTests(unittest.TestCase):
    def test_enabled_with_full_credentials_is_ready(self):
        settings = LLMSettings.from_env(_enabled_env())
        self.assertTrue(settings.enabled)
        self.assertTrue(settings.has_credentials)
        self.assertEqual(settings.status(), STATUS_READY)
        self.assertEqual(settings.missing_required(), ())

    def test_enabled_without_base_url_is_misconfigured(self):
        settings = LLMSettings.from_env(_enabled_env(REPORT_VERIFY_LLM_BASE_URL=""))
        self.assertEqual(settings.status(), STATUS_MISCONFIGURED)
        self.assertIn("REPORT_VERIFY_LLM_BASE_URL", settings.missing_required())

    def test_enabled_without_model_is_misconfigured(self):
        settings = LLMSettings.from_env(_enabled_env(REPORT_VERIFY_LLM_MODEL=""))
        self.assertEqual(settings.status(), STATUS_MISCONFIGURED)
        self.assertIn("REPORT_VERIFY_LLM_MODEL", settings.missing_required())

    def test_enabled_without_api_key_is_misconfigured(self):
        settings = LLMSettings.from_env(_enabled_env(REPORT_VERIFY_LLM_API_KEY=""))
        self.assertEqual(settings.status(), STATUS_MISCONFIGURED)
        self.assertIn("REPORT_VERIFY_LLM_API_KEY", settings.missing_required())

    def test_off_mode_never_misconfigured_even_without_credentials(self):
        settings = LLMSettings.from_env({"REPORT_VERIFY_LLM_MODE": "off"})
        self.assertEqual(settings.status(), STATUS_DISABLED)


class LimitsAndParsingTests(unittest.TestCase):
    def test_custom_limits_are_parsed(self):
        settings = LLMSettings.from_env(_enabled_env(
            REPORT_VERIFY_LLM_TIMEOUT="30",
            REPORT_VERIFY_LLM_MAX_RETRY="0",
            REPORT_VERIFY_LLM_TOTAL_TIMEOUT="90",
            REPORT_VERIFY_LLM_MAX_RESPONSE_BYTES="2048",
        ))
        self.assertEqual(settings.timeout_seconds, 30)
        self.assertEqual(settings.max_retry, 0)
        self.assertEqual(settings.total_timeout_seconds, 90)
        self.assertEqual(settings.max_response_bytes, 2048)

    def test_explain_batch_rows_default_is_below_policy_max_rows(self):
        settings = LLMSettings.from_env(_enabled_env())
        self.assertEqual(settings.explain_batch_rows, 50)
        self.assertEqual(settings.diagnostics()["explain_batch_rows"], 50)

    def test_explain_batch_rows_parsed_from_env(self):
        settings = LLMSettings.from_env(_enabled_env(
            REPORT_VERIFY_LLM_EXPLAIN_BATCH_ROWS="25",
        ))
        self.assertEqual(settings.explain_batch_rows, 25)
        self.assertEqual(settings.diagnostics()["explain_batch_rows"], 25)

    def test_explain_batch_rows_non_integer_raises(self):
        with self.assertRaises(LLMConfigurationError):
            LLMSettings.from_env(_enabled_env(
                REPORT_VERIFY_LLM_EXPLAIN_BATCH_ROWS="many",
            ))

    def test_explain_batch_rows_non_positive_raises(self):
        with self.assertRaises(LLMConfigurationError):
            LLMSettings.from_env(_enabled_env(
                REPORT_VERIFY_LLM_EXPLAIN_BATCH_ROWS="0",
            ))

    def test_explain_max_diffs_default_and_diagnostics(self):
        settings = LLMSettings.from_env(_enabled_env())
        self.assertEqual(settings.explain_max_diffs, 500)
        self.assertEqual(settings.diagnostics()["explain_max_diffs"], 500)

    def test_explain_max_diffs_parsed_from_env(self):
        settings = LLMSettings.from_env(_enabled_env(
            REPORT_VERIFY_LLM_EXPLAIN_MAX_DIFFS="80",
        ))
        self.assertEqual(settings.explain_max_diffs, 80)
        self.assertEqual(settings.diagnostics()["explain_max_diffs"], 80)

    def test_explain_max_diffs_invalid_values_raise(self):
        for bad in ("many", "0", "-5"):
            with self.subTest(value=bad):
                with self.assertRaises(LLMConfigurationError):
                    LLMSettings.from_env(_enabled_env(
                        REPORT_VERIFY_LLM_EXPLAIN_MAX_DIFFS=bad,
                    ))

    def test_explain_max_workers_default_and_diagnostics(self):
        settings = LLMSettings.from_env(_enabled_env())
        self.assertEqual(settings.explain_max_workers, 4)
        self.assertEqual(settings.diagnostics()["explain_max_workers"], 4)

    def test_explain_max_workers_parsed_from_env(self):
        settings = LLMSettings.from_env(_enabled_env(
            REPORT_VERIFY_LLM_EXPLAIN_MAX_WORKERS="1",
        ))
        self.assertEqual(settings.explain_max_workers, 1)
        self.assertEqual(settings.diagnostics()["explain_max_workers"], 1)

    def test_explain_max_workers_invalid_values_raise(self):
        for bad in ("lots", "0", "-2"):
            with self.subTest(value=bad):
                with self.assertRaises(LLMConfigurationError):
                    LLMSettings.from_env(_enabled_env(
                        REPORT_VERIFY_LLM_EXPLAIN_MAX_WORKERS=bad,
                    ))

    def test_max_tokens_default_is_zero_and_unlimited(self):
        settings = LLMSettings.from_env(_enabled_env())
        self.assertEqual(settings.max_tokens, 0)
        self.assertEqual(settings.diagnostics()["max_tokens"], 0)

    def test_max_tokens_empty_env_defaults_to_zero(self):
        settings = LLMSettings.from_env(_enabled_env(
            REPORT_VERIFY_LLM_MAX_TOKENS="",
        ))
        self.assertEqual(settings.max_tokens, 0)

    def test_max_tokens_positive_parsed_and_in_diagnostics(self):
        settings = LLMSettings.from_env(_enabled_env(
            REPORT_VERIFY_LLM_MAX_TOKENS="4096",
        ))
        self.assertEqual(settings.max_tokens, 4096)
        self.assertEqual(settings.diagnostics()["max_tokens"], 4096)

    def test_max_tokens_zero_is_allowed(self):
        settings = LLMSettings.from_env(_enabled_env(
            REPORT_VERIFY_LLM_MAX_TOKENS="0",
        ))
        self.assertEqual(settings.max_tokens, 0)

    def test_max_tokens_negative_raises(self):
        with self.assertRaises(LLMConfigurationError):
            LLMSettings.from_env(_enabled_env(
                REPORT_VERIFY_LLM_MAX_TOKENS="-1",
            ))

    def test_max_tokens_non_integer_raises(self):
        with self.assertRaises(LLMConfigurationError):
            LLMSettings.from_env(_enabled_env(
                REPORT_VERIFY_LLM_MAX_TOKENS="lots",
            ))

    def test_non_integer_limit_raises(self):
        with self.assertRaises(LLMConfigurationError):
            LLMSettings.from_env(_enabled_env(REPORT_VERIFY_LLM_TIMEOUT="abc"))

    def test_non_positive_limit_raises(self):
        with self.assertRaises(LLMConfigurationError):
            LLMSettings.from_env(_enabled_env(REPORT_VERIFY_LLM_TIMEOUT="0"))

    def test_unknown_mode_raises(self):
        with self.assertRaises(LLMConfigurationError):
            LLMSettings.from_env({"REPORT_VERIFY_LLM_MODE": "vision"})

    def test_ambiguous_bool_raises(self):
        with self.assertRaises(LLMConfigurationError):
            LLMSettings.from_env(_enabled_env(
                REPORT_VERIFY_LLM_ALLOW_ORIGINAL_TEXT="maybe"
            ))


class HostAllowlistTests(unittest.TestCase):
    def test_hosts_parsed_and_normalized(self):
        settings = LLMSettings.from_env(_enabled_env(
            REPORT_VERIFY_LLM_ALLOWED_HOSTS="Approved.Example, other.example"
        ))
        self.assertEqual(
            settings.allowed_hosts, frozenset({"approved.example", "other.example"})
        )

    def test_allowed_modes_parsed_and_off_implicit(self):
        settings = LLMSettings.from_env(_enabled_env(
            REPORT_VERIFY_LLM_ALLOWED_MODES="candidate,explain"
        ))
        self.assertIn("candidate", settings.allowed_job_modes)
        self.assertIn("explain", settings.allowed_job_modes)
        self.assertIn("off", settings.allowed_job_modes)  # off 隐式允许
        self.assertNotIn("candidate_explain", settings.allowed_job_modes)


class ImageFixedFalseTests(unittest.TestCase):
    def test_allow_images_fixed_false_via_env_ignored(self):
        # 环境中即便存在图片开关也不影响固定 False。
        settings = LLMSettings.from_env(_enabled_env(
            REPORT_VERIFY_LLM_ALLOW_IMAGES="true"
        ))
        self.assertFalse(settings.allow_images)
        self.assertFalse(settings.image_policy_valid)
        self.assertEqual(settings.status(), STATUS_MISCONFIGURED)

    def test_ambiguous_image_policy_is_rejected_before_enabled_runtime(self):
        with self.assertRaises(LLMConfigurationError):
            LLMSettings.from_env(_enabled_env(
                REPORT_VERIFY_LLM_ALLOW_IMAGES="maybe"
            ))

    def test_allow_images_override_via_constructor_is_forced_false(self):
        settings = LLMSettings(allow_images=True)  # type: ignore[arg-type]
        self.assertFalse(settings.allow_images)
        self.assertFalse(settings.image_policy_valid)


class SecretRedactionTests(unittest.TestCase):
    def test_diagnostics_never_contain_secret_values(self):
        settings = LLMSettings.from_env(_enabled_env())
        diag = settings.diagnostics()
        serialized = json.dumps(diag, ensure_ascii=False, sort_keys=True)
        self.assertNotIn(_PLACEHOLDER_API_KEY, serialized)
        self.assertNotIn(_PLACEHOLDER_USER_KEY, serialized)
        # 只暴露存在性布尔，不暴露值。
        self.assertTrue(diag["api_key_present"])
        self.assertTrue(diag["user_key_present"])
        self.assertFalse(diag["secret_values_in_diagnostics"])
        self.assertFalse(diag["allow_images"])

    def test_repr_and_str_never_contain_secret_values(self):
        settings = LLMSettings.from_env(_enabled_env())
        text = repr(settings)
        self.assertNotIn(_PLACEHOLDER_API_KEY, text)
        self.assertNotIn(_PLACEHOLDER_USER_KEY, text)
        self.assertNotIn(_PLACEHOLDER_API_KEY, str(settings))
        # 存在凭据时用掩码占位表示。
        self.assertIn("redacted", text.lower())

    def test_repr_shows_empty_for_absent_secrets(self):
        settings = LLMSettings.from_env({})
        text = repr(settings)
        self.assertNotIn("redacted", text.lower())

    def test_diagnostics_flags_missing_credentials_when_enabled(self):
        settings = LLMSettings.from_env(_enabled_env(REPORT_VERIFY_LLM_API_KEY=""))
        diag = settings.diagnostics()
        self.assertEqual(diag["status"], STATUS_MISCONFIGURED)
        self.assertFalse(diag["api_key_present"])
        self.assertIn("REPORT_VERIFY_LLM_API_KEY", diag["missing_required"])


if __name__ == "__main__":
    unittest.main()
