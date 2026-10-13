"""创建任务 ``llm_mode`` 校验入口的单元测试（任务 1.6）。

这些测试只使用占位配置和本地对象；不访问真实 provider，不读取/复制/打印
真实 API key 或 user key，也不发起任何网络请求。任务 1.6 只复用任务 0.2 的
:func:`authorize_job_mode` allowlist/override 逻辑，本文件验证“创建任务”场景
入口的正确编排，不重复测试底层 allowlist 细节。
"""
from __future__ import annotations

import unittest

from report_verify.llm.config import LLMSettings
from report_verify.llm.jobmode import (
    JOB_MODE_REQUEST_KEY,
    JobModeDecision,
    authorize_job_creation,
    policy_from_settings,
    resolve_job_mode,
)
from report_verify.llm.policy import (
    ERROR_TASK_MODE_NOT_ALLOWED,
    PolicyError,
    ServerLLMPolicy,
    check_server_policy,
)

# 占位凭据值，仅用于断言派生策略不携带凭据；不是任何真实密钥。
_PLACEHOLDER_API_KEY = "PLACEHOLDER-API-KEY-DO-NOT-USE"
_PLACEHOLDER_USER_KEY = "PLACEHOLDER-USER-KEY-DO-NOT-USE"


def _enabled_settings(**overrides) -> LLMSettings:
    env = {
        "REPORT_VERIFY_LLM_MODE": "candidate_explain",
        "REPORT_VERIFY_LLM_BASE_URL": "https://approved.example/v1",
        "REPORT_VERIFY_LLM_MODEL": "configured-model",
        "REPORT_VERIFY_LLM_API_KEY": _PLACEHOLDER_API_KEY,
        "REPORT_VERIFY_LLM_USER_KEY": _PLACEHOLDER_USER_KEY,
        "REPORT_VERIFY_LLM_ALLOWED_HOSTS": "approved.example",
        "REPORT_VERIFY_LLM_ALLOWED_MODES": "off,candidate,explain,candidate_explain",
    }
    env.update(overrides)
    return LLMSettings.from_env(env)


def _enabled_policy(**overrides) -> ServerLLMPolicy:
    cfg = {
        "mode": "candidate_explain",
        "allow_original_text": True,
        "allowed_hosts": ["approved.example"],
        "allow_job_override": True,
        "allowed_modes": ["off", "candidate", "explain", "candidate_explain"],
    }
    cfg.update(overrides)
    return check_server_policy(cfg)


class PolicyDerivationTests(unittest.TestCase):
    """从 LLMSettings 派生策略视图，保证与 0.2/1.1 一致且不带凭据。"""

    def test_policy_from_settings_copies_non_secret_fields(self):
        settings = _enabled_settings(
            REPORT_VERIFY_LLM_ALLOWED_MODES="off,candidate",
        )
        policy = policy_from_settings(settings)
        self.assertEqual(policy.mode, "candidate_explain")
        self.assertEqual(policy.allow_job_override, settings.allow_job_override)
        self.assertEqual(policy.allowed_job_modes, settings.allowed_job_modes)
        self.assertEqual(policy.allow_original_text, settings.allow_original_text)
        self.assertEqual(policy.allowed_hosts, settings.allowed_hosts)
        self.assertEqual(policy.redaction_profile, settings.redaction_profile)

    def test_derived_policy_forces_image_false(self):
        settings = _enabled_settings()
        policy = policy_from_settings(settings)
        self.assertFalse(policy.allow_images)

    def test_derived_policy_carries_no_credentials(self):
        settings = _enabled_settings()
        policy = policy_from_settings(settings)
        # ServerLLMPolicy 根本不定义凭据字段，派生也绝不复制它们。
        for secret_field in ("api_key", "user_key", "base_url", "model"):
            self.assertFalse(hasattr(policy, secret_field))


class AllowedModeTests(unittest.TestCase):
    def test_allowed_mode_takes_effect(self):
        settings = _enabled_settings()
        decision = authorize_job_creation(settings, {JOB_MODE_REQUEST_KEY: "candidate"})
        self.assertIsInstance(decision, JobModeDecision)
        self.assertEqual(decision.mode, "candidate")
        self.assertTrue(decision.requested)
        self.assertEqual(decision.server_default, "candidate_explain")

    def test_all_four_modes_accepted_when_allowlisted(self):
        settings = _enabled_settings()
        for mode in ("off", "candidate", "explain", "candidate_explain"):
            decision = authorize_job_creation(settings, {JOB_MODE_REQUEST_KEY: mode})
            self.assertEqual(decision.mode, mode)

    def test_policy_object_accepted_directly(self):
        policy = _enabled_policy()
        decision = authorize_job_creation(policy, {JOB_MODE_REQUEST_KEY: "explain"})
        self.assertEqual(decision.mode, "explain")


class DefaultFallbackTests(unittest.TestCase):
    def test_missing_request_falls_back_to_server_default(self):
        settings = _enabled_settings(REPORT_VERIFY_LLM_MODE="candidate")
        decision = authorize_job_creation(settings, None)
        self.assertEqual(decision.mode, "candidate")
        self.assertFalse(decision.requested)
        self.assertEqual(decision.server_default, "candidate")

    def test_request_without_mode_key_falls_back(self):
        settings = _enabled_settings(REPORT_VERIFY_LLM_MODE="explain")
        decision = authorize_job_creation(settings, {"cert": "a.docx", "draft": "b.docx"})
        self.assertEqual(decision.mode, "explain")
        self.assertFalse(decision.requested)

    def test_business_fields_are_not_treated_as_override(self):
        # 普通业务键（cert/draft 文件引用）不应被误判为越权 override。
        settings = _enabled_settings()
        decision = authorize_job_creation(
            settings,
            {JOB_MODE_REQUEST_KEY: "candidate", "cert": "a.docx", "draft": "b.docx"},
        )
        self.assertEqual(decision.mode, "candidate")


class RejectionTests(unittest.TestCase):
    def test_unknown_mode_is_rejected(self):
        settings = _enabled_settings()
        with self.assertRaises(PolicyError) as ctx:
            authorize_job_creation(settings, {JOB_MODE_REQUEST_KEY: "vision"})
        self.assertEqual(ctx.exception.code, ERROR_TASK_MODE_NOT_ALLOWED)

    def test_mode_not_in_allowlist_is_rejected(self):
        settings = _enabled_settings(
            REPORT_VERIFY_LLM_ALLOWED_MODES="off,explain",
        )
        with self.assertRaises(PolicyError) as ctx:
            authorize_job_creation(settings, {JOB_MODE_REQUEST_KEY: "candidate"})
        self.assertEqual(ctx.exception.code, ERROR_TASK_MODE_NOT_ALLOWED)

    def test_override_provider_fields_are_rejected(self):
        settings = _enabled_settings()
        for bad in ("base_url", "provider", "model", "api_key", "user_key",
                    "allowed_hosts", "allow_images", "allow_original_text",
                    "host", "tls", "endpoint"):
            with self.assertRaises(PolicyError) as ctx:
                authorize_job_creation(
                    settings,
                    {JOB_MODE_REQUEST_KEY: "candidate", bad: "x"},
                )
            self.assertEqual(
                ctx.exception.code, ERROR_TASK_MODE_NOT_ALLOWED,
                msg=f"override field {bad!r} should be rejected",
            )

    def test_fullwidth_disguised_override_is_rejected(self):
        # 全角 "ｍｏｄｅｌ" 也必须被硬拒绝（policy 层做 NFKC 归一）。
        settings = _enabled_settings()
        with self.assertRaises(PolicyError) as ctx:
            authorize_job_creation(
                settings,
                {JOB_MODE_REQUEST_KEY: "candidate",
                 "\uFF4D\uFF4F\uFF44\uFF45\uFF4C": "gpt"},
            )
        self.assertEqual(ctx.exception.code, ERROR_TASK_MODE_NOT_ALLOWED)


class JobOverrideDisabledTests(unittest.TestCase):
    def test_override_disabled_allows_only_server_default(self):
        settings = _enabled_settings(
            REPORT_VERIFY_LLM_MODE="candidate",
            REPORT_VERIFY_LLM_ALLOW_JOB_OVERRIDE="false",
        )
        # 与服务器默认相同的 mode 仍可选择。
        decision = authorize_job_creation(settings, {JOB_MODE_REQUEST_KEY: "candidate"})
        self.assertEqual(decision.mode, "candidate")
        # 不同 mode 被拒绝。
        with self.assertRaises(PolicyError) as ctx:
            authorize_job_creation(settings, {JOB_MODE_REQUEST_KEY: "explain"})
        self.assertEqual(ctx.exception.code, ERROR_TASK_MODE_NOT_ALLOWED)


class ResolveJobModeTests(unittest.TestCase):
    """轻量入口 resolve_job_mode 语义与 authorize_job_creation 一致。"""

    def test_resolve_returns_effective_mode(self):
        settings = _enabled_settings()
        self.assertEqual(resolve_job_mode(settings, "candidate"), "candidate")

    def test_resolve_none_falls_back_to_default(self):
        settings = _enabled_settings(REPORT_VERIFY_LLM_MODE="explain")
        self.assertEqual(resolve_job_mode(settings, None), "explain")

    def test_resolve_rejects_override(self):
        settings = _enabled_settings()
        with self.assertRaises(PolicyError) as ctx:
            resolve_job_mode(settings, "candidate", override_fields={"api_key": "x"})
        self.assertEqual(ctx.exception.code, ERROR_TASK_MODE_NOT_ALLOWED)


if __name__ == "__main__":
    unittest.main()
