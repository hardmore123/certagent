"""专业候选数据结构与生成入口的单元测试（任务 2.3）。

这些测试只构造本地对象与字符串 stub；不访问真实 provider、不读取/复制/打印真实
API key 或 user key，也不发起任何网络请求。生成入口只读取差异的 block/field/item
元数据和已发布规则摘要，产出待确认候选，绝不写最终 discipline，也不改变
``discipline_status``。
"""
from __future__ import annotations

import json
import unittest

from report_verify.llm.config import LLMSettings
from report_verify.llm.discipline import (
    CANDIDATE_SOURCE_LLM,
    CANDIDATE_STATUS_PENDING,
    STATUS_DISABLED,
    STATUS_FALLBACK,
    STATUS_INVALID,
    STATUS_SKIPPED_POLICY,
    STATUS_SUCCESS,
    DisciplineSuggestionSet,
    PublishedDisciplineRules,
    generate_discipline_suggestions,
)
from report_verify.models import VerifyDiff, VerifyResult

_SCHEMA = "reportverify-llm-v1"

# 占位凭据值，仅用于构造启用配置；不是任何真实密钥。
_PLACEHOLDER_API_KEY = "PLACEHOLDER-API-KEY-DO-NOT-USE"


def _enabled_settings(mode: str = "explain", **overrides) -> LLMSettings:
    env = {
        "REPORT_VERIFY_LLM_MODE": mode,
        "REPORT_VERIFY_LLM_BASE_URL": "https://approved.example/v1",
        "REPORT_VERIFY_LLM_MODEL": "configured-model",
        "REPORT_VERIFY_LLM_API_KEY": _PLACEHOLDER_API_KEY,
    }
    env.update(overrides)
    return LLMSettings.from_env(env)


def _result_with_diffs() -> VerifyResult:
    diffs = [
        VerifyDiff(
            key="k-safety-1",
            block_type="安全关键件清单",
            item_name="电源",
            diff_type="field_mismatch",
            field="型号",
            cert_value="A",
            draft_value="B",
        ),
        VerifyDiff(
            key="k-emc-1",
            block_type="EMC关键件清单",
            item_name="滤波器",
            diff_type="missing_in_draft",
            field="厂商",
        ),
    ]
    return VerifyResult(diffs=diffs)


def _discipline_json(candidates) -> str:
    return json.dumps(
        {"schema_version": _SCHEMA, "candidates": candidates},
        ensure_ascii=False,
    )


class DisciplineWithRulesTest(unittest.TestCase):
    """有已发布规则时产出候选，但 discipline_status 仍保持 pending。"""

    def test_success_produces_pending_candidates_without_touching_final_fields(self):
        result = _result_with_diffs()
        rules = PublishedDisciplineRules(
            allowed_disciplines=frozenset({"安全", "EMC"}),
            version="rules-2026-01",
            confirmed=True,
        )

        def caller(diff_meta, published):
            # 校验入口只传递结构化元数据，不含 CERT/DRAFT 原文值。
            for meta in diff_meta:
                self.assertIn("diff_key", meta)
                self.assertIn("block_type", meta)
                self.assertNotIn("cert_value", meta)
                self.assertNotIn("draft_value", meta)
            self.assertEqual(published.version, "rules-2026-01")
            return _discipline_json([
                {
                    "diff_key": "k-safety-1",
                    "discipline": "安全",
                    "confidence": 0.9,
                    "reason": "涉及电源关键件",
                },
                {
                    "diff_key": "k-emc-1",
                    "discipline": "EMC",
                    "confidence": 0.8,
                    "reason": "涉及滤波器",
                },
            ])

        outcome = generate_discipline_suggestions(
            result, rules, settings=_enabled_settings(), caller=caller
        )

        self.assertEqual(outcome.status, STATUS_SUCCESS)
        self.assertEqual(len(outcome.suggestions), 2)
        for sug in outcome.suggestions:
            self.assertEqual(sug.source, CANDIDATE_SOURCE_LLM)
            self.assertEqual(sug.status, CANDIDATE_STATUS_PENDING)
            self.assertEqual(sug.rule_version, "rules-2026-01")

        # 关键不变量：最终 discipline 未被写入，discipline_status 保持 pending。
        self.assertTrue(outcome.discipline_status_unchanged)
        for diff in result.diffs:
            self.assertIsNone(diff.discipline)
            self.assertEqual(diff.discipline_status, "discipline_pending")

    def test_empty_candidates_still_success_and_pending(self):
        result = _result_with_diffs()
        rules = PublishedDisciplineRules(
            allowed_disciplines=frozenset({"安全"}),
            version="rules-2026-01",
        )
        outcome = generate_discipline_suggestions(
            result, rules, settings=_enabled_settings(),
            caller=lambda meta, pub: _discipline_json([]),
        )
        self.assertEqual(outcome.status, STATUS_SUCCESS)
        self.assertEqual(outcome.suggestions, ())
        for diff in result.diffs:
            self.assertEqual(diff.discipline_status, "discipline_pending")


class DisciplineSkippedPolicyTest(unittest.TestCase):
    """无已发布规则/版本未确认/未接入 client 时 skipped_policy，不触发路由。"""

    def test_no_published_rules_is_skipped_policy(self):
        result = _result_with_diffs()
        rules = PublishedDisciplineRules()  # 空专业集合、无版本

        called = {"hit": False}

        def caller(meta, pub):  # pragma: no cover - 不应被调用
            called["hit"] = True
            return _discipline_json([])

        outcome = generate_discipline_suggestions(
            result, rules, settings=_enabled_settings(), caller=caller
        )

        self.assertEqual(outcome.status, STATUS_SKIPPED_POLICY)
        self.assertEqual(outcome.suggestions, ())
        self.assertFalse(called["hit"])  # 无规则时不发 provider 请求
        for diff in result.diffs:
            self.assertIsNone(diff.discipline)
            self.assertEqual(diff.discipline_status, "discipline_pending")

    def test_unconfirmed_rule_version_is_skipped_policy(self):
        result = _result_with_diffs()
        rules = PublishedDisciplineRules(
            allowed_disciplines=frozenset({"安全"}),
            version="rules-draft",
            confirmed=False,
        )
        outcome = generate_discipline_suggestions(
            result, rules, settings=_enabled_settings(),
            caller=lambda meta, pub: _discipline_json([]),
        )
        self.assertEqual(outcome.status, STATUS_SKIPPED_POLICY)
        self.assertEqual(outcome.suggestions, ())

    def test_no_caller_falls_back_to_skipped_policy(self):
        result = _result_with_diffs()
        rules = PublishedDisciplineRules(
            allowed_disciplines=frozenset({"安全"}),
            version="rules-2026-01",
        )
        outcome = generate_discipline_suggestions(
            result, rules, settings=_enabled_settings(), caller=None
        )
        self.assertEqual(outcome.status, STATUS_SKIPPED_POLICY)
        self.assertEqual(outcome.suggestions, ())


class DisciplineDisabledTest(unittest.TestCase):
    """mode 未开启 discipline 能力时 disabled，且不调用 provider。"""

    def test_mode_off_is_disabled(self):
        result = _result_with_diffs()
        rules = PublishedDisciplineRules(
            allowed_disciplines=frozenset({"安全"}),
            version="rules-2026-01",
        )
        called = {"hit": False}

        def caller(meta, pub):  # pragma: no cover
            called["hit"] = True
            return _discipline_json([])

        outcome = generate_discipline_suggestions(
            result, rules, settings=_enabled_settings(mode="off"), caller=caller
        )
        self.assertEqual(outcome.status, STATUS_DISABLED)
        self.assertFalse(called["hit"])

    def test_candidate_only_mode_is_disabled_for_discipline(self):
        result = _result_with_diffs()
        rules = PublishedDisciplineRules(
            allowed_disciplines=frozenset({"安全"}),
            version="rules-2026-01",
        )
        outcome = generate_discipline_suggestions(
            result, rules, settings=_enabled_settings(mode="candidate"),
            caller=lambda meta, pub: _discipline_json([]),
        )
        self.assertEqual(outcome.status, STATUS_DISABLED)


class DisciplineRejectionTest(unittest.TestCase):
    """非允许专业/未知 diff key 被拒（复用 schemas 校验），回退且不写最终字段。"""

    def test_disallowed_discipline_is_rejected(self):
        result = _result_with_diffs()
        rules = PublishedDisciplineRules(
            allowed_disciplines=frozenset({"安全"}),  # 不含“环境”
            version="rules-2026-01",
        )
        outcome = generate_discipline_suggestions(
            result, rules, settings=_enabled_settings(),
            caller=lambda meta, pub: _discipline_json([
                {
                    "diff_key": "k-safety-1",
                    "discipline": "环境",  # 非允许专业
                    "confidence": 0.9,
                    "reason": "越权专业",
                }
            ]),
        )
        self.assertEqual(outcome.status, STATUS_INVALID)
        self.assertEqual(outcome.suggestions, ())
        # 回退：最终字段与状态均未变化。
        for diff in result.diffs:
            self.assertIsNone(diff.discipline)
            self.assertEqual(diff.discipline_status, "discipline_pending")

    def test_unknown_diff_key_is_rejected(self):
        result = _result_with_diffs()
        rules = PublishedDisciplineRules(
            allowed_disciplines=frozenset({"安全"}),
            version="rules-2026-01",
        )
        outcome = generate_discipline_suggestions(
            result, rules, settings=_enabled_settings(),
            caller=lambda meta, pub: _discipline_json([
                {
                    "diff_key": "does-not-exist",
                    "discipline": "安全",
                    "confidence": 0.9,
                    "reason": "凭空创造的差异",
                }
            ]),
        )
        self.assertEqual(outcome.status, STATUS_INVALID)

    def test_auto_verdict_field_is_rejected(self):
        result = _result_with_diffs()
        rules = PublishedDisciplineRules(
            allowed_disciplines=frozenset({"安全"}),
            version="rules-2026-01",
        )
        # 注入被禁的自动决策字段，schemas 应拒绝。
        payload = json.dumps({
            "schema_version": _SCHEMA,
            "candidates": [{
                "diff_key": "k-safety-1",
                "discipline": "安全",
                "confidence": 0.9,
                "reason": "带越权字段",
                "route": "assign-to-safety",
            }],
        }, ensure_ascii=False)
        outcome = generate_discipline_suggestions(
            result, rules, settings=_enabled_settings(),
            caller=lambda meta, pub: payload,
        )
        self.assertEqual(outcome.status, STATUS_INVALID)


class DisciplineFallbackTest(unittest.TestCase):
    """provider 调用异常时回退 fallback，不抛出、不写最终字段。"""

    def test_provider_exception_is_fallback(self):
        result = _result_with_diffs()
        rules = PublishedDisciplineRules(
            allowed_disciplines=frozenset({"安全"}),
            version="rules-2026-01",
        )

        def caller(meta, pub):
            raise RuntimeError("simulated provider failure")

        outcome = generate_discipline_suggestions(
            result, rules, settings=_enabled_settings(), caller=caller
        )
        self.assertEqual(outcome.status, STATUS_FALLBACK)
        self.assertEqual(outcome.suggestions, ())
        for diff in result.diffs:
            self.assertIsNone(diff.discipline)
            self.assertEqual(diff.discipline_status, "discipline_pending")


class DisciplineSerializationTest(unittest.TestCase):
    """to_dict 输出脱敏，不含 prompt/response 原文或凭据。"""

    def test_suggestion_set_to_dict_shape(self):
        result = _result_with_diffs()
        rules = PublishedDisciplineRules(
            allowed_disciplines=frozenset({"安全"}),
            version="rules-2026-01",
        )
        outcome = generate_discipline_suggestions(
            result, rules, settings=_enabled_settings(),
            caller=lambda meta, pub: _discipline_json([{
                "diff_key": "k-safety-1",
                "discipline": "安全",
                "confidence": 0.9,
                "reason": "ok",
            }]),
        )
        data = outcome.to_dict()
        self.assertEqual(data["status"], STATUS_SUCCESS)
        self.assertTrue(data["discipline_status_unchanged"])
        self.assertEqual(len(data["suggestions"]), 1)
        sug = data["suggestions"][0]
        self.assertEqual(sug["source"], CANDIDATE_SOURCE_LLM)
        self.assertEqual(sug["status"], CANDIDATE_STATUS_PENDING)
        self.assertNotIn("prompt", json.dumps(data, ensure_ascii=False))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
