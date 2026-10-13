"""LLM 响应严格 Schema 与本地安全校验的单元测试（任务 1.5）。

这些测试只构造本地字符串/上下文对象，不访问真实 provider、不读取/复制/打印
真实 API key 或 user key，也不发起任何网络请求。输入模拟任务 1.3 ``repair_json``
之后的字符串（可能带围栏/杂文已被去除）。
"""
from __future__ import annotations

import json
import unittest

from report_verify.llm.schemas import (
    CAPABILITY_CANDIDATE,
    CAPABILITY_DISCIPLINE,
    CAPABILITY_EXPLAIN,
    ERROR_SAFETY_REJECTED,
    ERROR_SCHEMA_INVALID,
    CandidateContext,
    CandidateResponse,
    DisciplineContext,
    DisciplineResponse,
    ExplainContext,
    ExplanationResponse,
    validate_response,
)

_SCHEMA = "reportverify-llm-v1"


def _candidate_context(**overrides) -> CandidateContext:
    """跨文档候选池上下文。

    CERT 与 DRAFT 是两个独立文档：物理表号各自独立编号（CERT 的 safety_list 在
    第 7 张表，DRAFT 的 safety_list 在第 1 张表），同块判定只看 block_type。
    """

    base = dict(
        cert_indices=frozenset({0, 1, 2}),
        draft_indices=frozenset({0, 1, 2}),
        cert_block_type={0: "safety_list", 1: "safety_list", 2: "emc_list"},
        draft_block_type={0: "safety_list", 1: "safety_list", 2: "emc_list"},
        cert_table={0: 7, 1: 7, 2: 8},
        draft_table={0: 1, 1: 1, 2: 2},
        cert_group={0: "A", 1: "A", 2: "B"},
        draft_group={0: "A", 1: "A", 2: "B"},
        same_block_only=True,
        same_group_only=True,
        min_confidence=0.5,
    )
    base.update(overrides)
    return CandidateContext(**base)


def _candidate_json(pairs) -> str:
    return json.dumps({"schema_version": _SCHEMA, "pairs": pairs}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# candidate 能力
# ---------------------------------------------------------------------------


class CandidateValidTests(unittest.TestCase):
    def test_valid_candidate_passes_and_returns_structured_pairs(self):
        text = _candidate_json([
            {"cert_index": 0, "draft_index": 1, "confidence": 0.9, "reason": "同子块同组"},
            {"cert_index": 2, "draft_index": 2, "confidence": 0.7, "reason": "同子块同组"},
        ])
        outcome = validate_response(
            CAPABILITY_CANDIDATE, text, _candidate_context(), schema_version=_SCHEMA
        )
        self.assertTrue(outcome.ok)
        self.assertIsInstance(outcome.data, CandidateResponse)
        self.assertEqual(len(outcome.data.pairs), 2)
        self.assertEqual(outcome.data.pairs[0].cert_index, 0)
        self.assertEqual(outcome.data.pairs[0].draft_index, 1)

    def test_same_block_type_with_different_physical_tables_is_accepted(self):
        # 跨文档回归：CERT safety_list 在表 7，DRAFT safety_list 在表 1，
        # block_type 相同 + 分组相容 -> 必须接受（旧的物理表号比较会误拒）。
        text = _candidate_json([
            {"cert_index": 0, "draft_index": 0, "confidence": 0.9,
             "reason": "同 block_type，物理表号不同"},
        ])
        ctx = _candidate_context()
        self.assertNotEqual(ctx.cert_table[0], ctx.draft_table[0])
        outcome = validate_response(
            CAPABILITY_CANDIDATE, text, ctx, schema_version=_SCHEMA
        )
        self.assertTrue(outcome.ok, outcome.error_message)
        self.assertEqual(len(outcome.data.pairs), 1)

    def test_empty_pairs_is_valid(self):
        outcome = validate_response(
            CAPABILITY_CANDIDATE, _candidate_json([]),
            _candidate_context(), schema_version=_SCHEMA,
        )
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.data.pairs, ())


class CandidateInvalidTests(unittest.TestCase):
    def test_invalid_json_is_rejected(self):
        outcome = validate_response(
            CAPABILITY_CANDIDATE, "{not json", _candidate_context(),
            schema_version=_SCHEMA,
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, ERROR_SCHEMA_INVALID)

    def test_wrong_schema_version_is_rejected(self):
        text = json.dumps({"schema_version": "other-v9", "pairs": []})
        outcome = validate_response(
            CAPABILITY_CANDIDATE, text, _candidate_context(), schema_version=_SCHEMA
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, ERROR_SCHEMA_INVALID)

    def test_unknown_top_level_field_is_rejected(self):
        text = json.dumps({"schema_version": _SCHEMA, "pairs": [], "extra": 1})
        outcome = validate_response(
            CAPABILITY_CANDIDATE, text, _candidate_context(), schema_version=_SCHEMA
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, ERROR_SCHEMA_INVALID)

    def test_unknown_pair_field_is_rejected(self):
        text = _candidate_json([
            {"cert_index": 0, "draft_index": 1, "confidence": 0.9,
             "reason": "x", "note": "unexpected"},
        ])
        outcome = validate_response(
            CAPABILITY_CANDIDATE, text, _candidate_context(), schema_version=_SCHEMA
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, ERROR_SCHEMA_INVALID)

    def test_missing_required_field_is_rejected(self):
        text = _candidate_json([{"cert_index": 0, "draft_index": 1, "confidence": 0.9}])
        outcome = validate_response(
            CAPABILITY_CANDIDATE, text, _candidate_context(), schema_version=_SCHEMA
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, ERROR_SCHEMA_INVALID)

    def test_cert_index_out_of_range_is_rejected(self):
        text = _candidate_json([
            {"cert_index": 99, "draft_index": 1, "confidence": 0.9, "reason": "x"},
        ])
        outcome = validate_response(
            CAPABILITY_CANDIDATE, text, _candidate_context(), schema_version=_SCHEMA
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, ERROR_SAFETY_REJECTED)

    def test_draft_index_out_of_range_is_rejected(self):
        text = _candidate_json([
            {"cert_index": 0, "draft_index": 99, "confidence": 0.9, "reason": "x"},
        ])
        outcome = validate_response(
            CAPABILITY_CANDIDATE, text, _candidate_context(), schema_version=_SCHEMA
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, ERROR_SAFETY_REJECTED)

    def test_duplicate_cert_index_is_rejected(self):
        text = _candidate_json([
            {"cert_index": 0, "draft_index": 0, "confidence": 0.9, "reason": "x"},
            {"cert_index": 0, "draft_index": 1, "confidence": 0.9, "reason": "x"},
        ])
        outcome = validate_response(
            CAPABILITY_CANDIDATE, text, _candidate_context(), schema_version=_SCHEMA
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, ERROR_SAFETY_REJECTED)

    def test_duplicate_draft_index_is_rejected(self):
        text = _candidate_json([
            {"cert_index": 0, "draft_index": 1, "confidence": 0.9, "reason": "x"},
            {"cert_index": 1, "draft_index": 1, "confidence": 0.9, "reason": "x"},
        ])
        outcome = validate_response(
            CAPABILITY_CANDIDATE, text, _candidate_context(), schema_version=_SCHEMA
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, ERROR_SAFETY_REJECTED)

    def test_confidence_above_one_is_rejected(self):
        text = _candidate_json([
            {"cert_index": 0, "draft_index": 1, "confidence": 1.5, "reason": "x"},
        ])
        outcome = validate_response(
            CAPABILITY_CANDIDATE, text, _candidate_context(), schema_version=_SCHEMA
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, ERROR_SAFETY_REJECTED)

    def test_confidence_below_zero_is_rejected(self):
        text = _candidate_json([
            {"cert_index": 0, "draft_index": 1, "confidence": -0.1, "reason": "x"},
        ])
        outcome = validate_response(
            CAPABILITY_CANDIDATE, text, _candidate_context(), schema_version=_SCHEMA
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, ERROR_SAFETY_REJECTED)

    def test_confidence_below_threshold_is_rejected(self):
        text = _candidate_json([
            {"cert_index": 0, "draft_index": 1, "confidence": 0.3, "reason": "x"},
        ])
        outcome = validate_response(
            CAPABILITY_CANDIDATE, text, _candidate_context(min_confidence=0.5),
            schema_version=_SCHEMA,
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, ERROR_SAFETY_REJECTED)

    def test_cross_block_type_pair_is_rejected(self):
        # cert_index 0 是 safety_list，draft_index 2 是 emc_list；分组刻意设为相容，
        # 只剩 block_type 不同这一个违规点。
        ctx = _candidate_context(
            cert_group={0: "A", 1: "A", 2: "A"},
            draft_group={0: "A", 1: "A", 2: "A"},
        )
        text = _candidate_json([
            {"cert_index": 0, "draft_index": 2, "confidence": 0.9, "reason": "x"},
        ])
        outcome = validate_response(
            CAPABILITY_CANDIDATE, text, ctx, schema_version=_SCHEMA
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, ERROR_SAFETY_REJECTED)
        self.assertIn("子块", outcome.error_message)
        self.assertNotIn("跨表", outcome.error_message)

    def test_missing_block_type_mapping_is_rejected(self):
        # 缺失 block_type 映射时 fail closed（不猜测同块）。
        ctx = _candidate_context(draft_block_type={1: "safety_list"})
        text = _candidate_json([
            {"cert_index": 0, "draft_index": 0, "confidence": 0.9, "reason": "x"},
        ])
        outcome = validate_response(
            CAPABILITY_CANDIDATE, text, ctx, schema_version=_SCHEMA
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, ERROR_SAFETY_REJECTED)

    def test_deprecated_same_table_only_false_disables_block_guard(self):
        # 向后兼容：显式 same_table_only=False 关闭同子块护栏（语义已是"同子块"）。
        ctx = _candidate_context(
            same_table_only=False,
            cert_group={0: "A", 1: "A", 2: "A"},
            draft_group={0: "A", 1: "A", 2: "A"},
        )
        text = _candidate_json([
            {"cert_index": 0, "draft_index": 2, "confidence": 0.9, "reason": "x"},
        ])
        outcome = validate_response(
            CAPABILITY_CANDIDATE, text, ctx, schema_version=_SCHEMA
        )
        self.assertTrue(outcome.ok, outcome.error_message)

    def test_cross_group_pair_is_rejected(self):
        # 构造同表但不同组：让 draft_index 1 属于组 B（cert 0 属于组 A）。
        ctx = _candidate_context(
            cert_group={0: "A", 1: "A", 2: "B"},
            draft_group={0: "A", 1: "B", 2: "B"},
        )
        text = _candidate_json([
            {"cert_index": 0, "draft_index": 1, "confidence": 0.9, "reason": "x"},
        ])
        outcome = validate_response(
            CAPABILITY_CANDIDATE, text, ctx, schema_version=_SCHEMA
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, ERROR_SAFETY_REJECTED)

    def test_non_integer_index_is_rejected(self):
        text = _candidate_json([
            {"cert_index": 0.5, "draft_index": 1, "confidence": 0.9, "reason": "x"},
        ])
        outcome = validate_response(
            CAPABILITY_CANDIDATE, text, _candidate_context(), schema_version=_SCHEMA
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, ERROR_SCHEMA_INVALID)

    def test_bool_index_is_rejected(self):
        # bool 是 int 子类，必须被显式拒绝。
        text = _candidate_json([
            {"cert_index": True, "draft_index": 1, "confidence": 0.9, "reason": "x"},
        ])
        outcome = validate_response(
            CAPABILITY_CANDIDATE, text, _candidate_context(), schema_version=_SCHEMA
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, ERROR_SCHEMA_INVALID)

    def test_over_long_reason_is_rejected(self):
        text = _candidate_json([
            {"cert_index": 0, "draft_index": 1, "confidence": 0.9,
             "reason": "长" * 10},
        ])
        outcome = validate_response(
            CAPABILITY_CANDIDATE, text, _candidate_context(),
            schema_version=_SCHEMA, max_reason_chars=5,
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, ERROR_SAFETY_REJECTED)

    def test_auto_verdict_field_is_rejected(self):
        # 顶层夹带自动决策字段。
        text = json.dumps({
            "schema_version": _SCHEMA,
            "pairs": [],
            "verdict": "accept",
        })
        outcome = validate_response(
            CAPABILITY_CANDIDATE, text, _candidate_context(), schema_version=_SCHEMA
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, ERROR_SAFETY_REJECTED)

    def test_nested_auto_verdict_field_is_rejected(self):
        text = json.dumps({
            "schema_version": _SCHEMA,
            "pairs": [
                {"cert_index": 0, "draft_index": 1, "confidence": 0.9,
                 "reason": "x", "decision": "ignore"},
            ],
        })
        outcome = validate_response(
            CAPABILITY_CANDIDATE, text, _candidate_context(), schema_version=_SCHEMA
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, ERROR_SAFETY_REJECTED)

    def test_wrong_context_type_is_rejected(self):
        outcome = validate_response(
            CAPABILITY_CANDIDATE, _candidate_json([]),
            ExplainContext(), schema_version=_SCHEMA,
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, ERROR_SCHEMA_INVALID)


# ---------------------------------------------------------------------------
# explain 能力
# ---------------------------------------------------------------------------


class ExplainTests(unittest.TestCase):
    def _ctx(self, **overrides) -> ExplainContext:
        base = dict(known_diff_keys=frozenset({"verify-abc", "verify-def"}))
        base.update(overrides)
        return ExplainContext(**base)

    def _json(self, explanations) -> str:
        return json.dumps(
            {"schema_version": _SCHEMA, "explanations": explanations},
            ensure_ascii=False,
        )

    def test_valid_explanation_passes(self):
        text = self._json([
            {"diff_key": "verify-abc", "explanation": "型号不同", "risk": "中"},
        ])
        outcome = validate_response(
            CAPABILITY_EXPLAIN, text, self._ctx(), schema_version=_SCHEMA
        )
        self.assertTrue(outcome.ok)
        self.assertIsInstance(outcome.data, ExplanationResponse)
        self.assertEqual(outcome.data.explanations[0].diff_key, "verify-abc")

    def test_unknown_diff_key_is_rejected(self):
        text = self._json([
            {"diff_key": "verify-unknown", "explanation": "x", "risk": "低"},
        ])
        outcome = validate_response(
            CAPABILITY_EXPLAIN, text, self._ctx(), schema_version=_SCHEMA
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, ERROR_SAFETY_REJECTED)

    def test_duplicate_diff_key_is_rejected(self):
        text = self._json([
            {"diff_key": "verify-abc", "explanation": "x", "risk": "低"},
            {"diff_key": "verify-abc", "explanation": "y", "risk": "低"},
        ])
        outcome = validate_response(
            CAPABILITY_EXPLAIN, text, self._ctx(), schema_version=_SCHEMA
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, ERROR_SAFETY_REJECTED)

    def test_over_long_explanation_is_rejected(self):
        text = self._json([
            {"diff_key": "verify-abc", "explanation": "长" * 20, "risk": "低"},
        ])
        outcome = validate_response(
            CAPABILITY_EXPLAIN, text, self._ctx(max_reason_chars=5),
            schema_version=_SCHEMA,
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, ERROR_SAFETY_REJECTED)

    def test_auto_verdict_field_is_rejected(self):
        text = json.dumps({
            "schema_version": _SCHEMA,
            "explanations": [
                {"diff_key": "verify-abc", "explanation": "x", "risk": "低",
                 "action": "accept"},
            ],
        })
        outcome = validate_response(
            CAPABILITY_EXPLAIN, text, self._ctx(), schema_version=_SCHEMA
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, ERROR_SAFETY_REJECTED)


# ---------------------------------------------------------------------------
# discipline 能力
# ---------------------------------------------------------------------------


class DisciplineTests(unittest.TestCase):
    def _ctx(self, **overrides) -> DisciplineContext:
        base = dict(
            known_diff_keys=frozenset({"verify-abc"}),
            allowed_disciplines=frozenset({"安全", "电磁兼容"}),
            min_confidence=0.5,
        )
        base.update(overrides)
        return DisciplineContext(**base)

    def _json(self, candidates) -> str:
        return json.dumps(
            {"schema_version": _SCHEMA, "candidates": candidates},
            ensure_ascii=False,
        )

    def test_valid_discipline_candidate_passes(self):
        text = self._json([
            {"diff_key": "verify-abc", "discipline": "安全",
             "confidence": 0.8, "reason": "涉及关键件"},
        ])
        outcome = validate_response(
            CAPABILITY_DISCIPLINE, text, self._ctx(), schema_version=_SCHEMA
        )
        self.assertTrue(outcome.ok)
        self.assertIsInstance(outcome.data, DisciplineResponse)
        self.assertEqual(outcome.data.candidates[0].discipline, "安全")

    def test_disallowed_discipline_is_rejected(self):
        text = self._json([
            {"diff_key": "verify-abc", "discipline": "未知专业",
             "confidence": 0.8, "reason": "x"},
        ])
        outcome = validate_response(
            CAPABILITY_DISCIPLINE, text, self._ctx(), schema_version=_SCHEMA
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, ERROR_SAFETY_REJECTED)

    def test_no_published_disciplines_rejects_all(self):
        # allowed_disciplines 为空 -> 任何专业候选都拒绝（保持 discipline_pending）。
        text = self._json([
            {"diff_key": "verify-abc", "discipline": "安全",
             "confidence": 0.8, "reason": "x"},
        ])
        outcome = validate_response(
            CAPABILITY_DISCIPLINE, text,
            self._ctx(allowed_disciplines=frozenset()),
            schema_version=_SCHEMA,
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, ERROR_SAFETY_REJECTED)

    def test_unknown_diff_key_is_rejected(self):
        text = self._json([
            {"diff_key": "verify-missing", "discipline": "安全",
             "confidence": 0.8, "reason": "x"},
        ])
        outcome = validate_response(
            CAPABILITY_DISCIPLINE, text, self._ctx(), schema_version=_SCHEMA
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, ERROR_SAFETY_REJECTED)

    def test_discipline_status_field_is_rejected_as_verdict(self):
        # discipline_status 属于自动路由字段，必须拒绝。
        text = json.dumps({
            "schema_version": _SCHEMA,
            "candidates": [
                {"diff_key": "verify-abc", "discipline": "安全",
                 "confidence": 0.8, "reason": "x",
                 "discipline_status": "assigned"},
            ],
        })
        outcome = validate_response(
            CAPABILITY_DISCIPLINE, text, self._ctx(), schema_version=_SCHEMA
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, ERROR_SAFETY_REJECTED)


class UnknownCapabilityTests(unittest.TestCase):
    def test_unknown_capability_is_rejected(self):
        outcome = validate_response(
            "bogus", "{}", CandidateContext(), schema_version=_SCHEMA
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, ERROR_SCHEMA_INVALID)


if __name__ == "__main__":
    unittest.main()
