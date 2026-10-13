"""候选接受/确定性重核对测试（任务 2.4）。

测试只使用本地 callback，不调用 provider，不创建 FastAPI 路由，也不使用真实
凭据。重点验证候选生命周期、CERT->DRAFT 护栏、确定性摘要和现有人工下载门禁
边界。
"""
from __future__ import annotations

import asyncio
import copy
import unittest
from dataclasses import replace

from fastapi import HTTPException

from report_verify.llm.orchestrator import LLMReviewCandidate
from report_verify.llm.recheck import (
    CANDIDATE_STATUS_ACCEPTED_FOR_RECHECK,
    CANDIDATE_STATUS_EXPIRED,
    CANDIDATE_STATUS_REJECTED,
    ERROR_CANDIDATE_DIRECTION_INVALID,
    ERROR_CANDIDATE_EXPIRED,
    ERROR_CANDIDATE_GROUP_MISMATCH,
    ERROR_CANDIDATE_STATUS_INVALID,
    ERROR_CANDIDATE_TABLE_MISMATCH,
    ERROR_CANDIDATE_UNKNOWN,
    ERROR_RECHECK_CALLBACK_FAILED,
    RECHECK_STATUS_FAILED,
    RECHECK_STATUS_SUCCESS,
    accept_candidate_for_recheck,
    candidate_key_for_refs,
)
from report_verify.models import DocumentRow, LocatedBlock, VerifyDiff, VerifyResult
from webapi.app import download_result
from webapi.jobs import Job, store

_BLOCK = "safety_list"
_RULES = {"version": "rules-test", "enabled": []}


def _row(*, row_idx: int, table: int = 1, group: str = "G1", model: str = "AAA-1") -> DocumentRow:
    return DocumentRow(
        block_type=_BLOCK,
        row_idx=row_idx,
        values={"关键件名称": "电容", "型号": model},
        source_table=table,
        group=group,
    )


def _ref(row: DocumentRow) -> dict[str, object]:
    return {
        "block_type": row.block_type,
        "table_idx": row.source_table,
        "row_idx": row.row_idx,
    }


def _result(cert: DocumentRow, draft: DocumentRow) -> VerifyResult:
    # Keep a populated verdict/discipline snapshot so the test proves that recheck does
    # not silently rewrite fields which belong to later human-review phases.
    diff = VerifyDiff(
        key="diff-original",
        block_type=_BLOCK,
        item_name="电容",
        diff_type="field_mismatch",
        field="型号",
        cert_value=cert.values.get("型号", ""),
        draft_value=draft.values.get("型号", ""),
        discipline="安全",
        discipline_status="discipline_pending",
        rule_version="rules-test",
        review_status="accept",
        review_note="人工保留的原备注",
        reviewed_by="reviewer-before-recheck",
    )
    return VerifyResult(
        cert_blocks=[LocatedBlock(block_type=_BLOCK, table_idx=cert.source_table, rows=[cert])],
        draft_blocks=[LocatedBlock(block_type=_BLOCK, table_idx=draft.source_table, rows=[draft])],
        diffs=[diff],
        rule_version="rules-test",
    )


def _candidate(
    cert: DocumentRow,
    draft: DocumentRow,
    *,
    status: str = "pending",
    source: str = "llm",
    candidate_key: str | None = None,
) -> LLMReviewCandidate:
    cert_ref, draft_ref = _ref(cert), _ref(draft)
    return LLMReviewCandidate(
        candidate_key=candidate_key or candidate_key_for_refs(cert_ref, draft_ref),
        capability="candidate",
        cert_ref=cert_ref,
        draft_ref=draft_ref,
        confidence=0.9,
        reason="本地测试候选，不写入重核对结果",
        status=status,
        source=source,
        policy_version="policy-test",
        schema_version="schema-test",
    )


class CandidateRecheckTests(unittest.TestCase):
    def test_valid_acceptance_enters_accepted_for_recheck_and_calls_callback(self):
        cert = _row(row_idx=2, model="AAA-1")
        draft = _row(row_idx=5, model="AAA-2")
        result = _result(cert, draft)
        before = copy.deepcopy(result)
        calls = []

        def callback(request):
            calls.append(request)
            # The callback only receives copied rows; mutating this value must not
            # mutate the deterministic result held by the caller.
            request.cert_row.values["型号"] = "callback-local-only"
            return {
                "status": "success",
                "same_value": False,
                "changed_fields": ["型号"],
                "diff_count": 1,
                "rule_version": request.rule_version,
            }

        candidate = _candidate(cert, draft)
        outcome = accept_candidate_for_recheck(
            candidate.candidate_key,
            [candidate],
            result,
            recheck_callback=callback,
            rules=_RULES,
        )

        self.assertEqual(outcome.status, CANDIDATE_STATUS_ACCEPTED_FOR_RECHECK)
        self.assertEqual(outcome.acceptance_status, CANDIDATE_STATUS_ACCEPTED_FOR_RECHECK)
        self.assertTrue(outcome.recheck_requested)
        self.assertEqual(outcome.recheck_result["status"], RECHECK_STATUS_SUCCESS)
        self.assertEqual(outcome.recheck_result["rule_version"], "rules-test")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].candidate["status"], CANDIDATE_STATUS_ACCEPTED_FOR_RECHECK)
        self.assertEqual(result, before)
        self.assertNotIn("本地测试候选", str(outcome.to_dict()))

    def test_default_recheck_uses_same_value_and_existing_rules(self):
        cert = _row(row_idx=2, model="AAA-1")
        draft = _row(row_idx=5, model="AAA-1")
        result = _result(cert, draft)
        candidate = _candidate(cert, draft)

        outcome = accept_candidate_for_recheck(
            candidate.candidate_key, [candidate], result, rules=_RULES
        )

        self.assertEqual(outcome.status, CANDIDATE_STATUS_ACCEPTED_FOR_RECHECK)
        self.assertEqual(outcome.recheck_result["status"], RECHECK_STATUS_SUCCESS)
        self.assertTrue(outcome.recheck_result["same_value"])
        self.assertEqual(outcome.recheck_result["changed_fields"], [])
        self.assertEqual(outcome.rule_version, "rules-test")

    def test_recheck_failure_is_explicit_and_preserves_original_diffs(self):
        cert = _row(row_idx=2)
        draft = _row(row_idx=5, model="AAA-2")
        result = _result(cert, draft)
        before = copy.deepcopy(result)
        candidate = _candidate(cert, draft)

        def callback(_request):
            raise RuntimeError("do-not-leak-this-callback-detail")

        outcome = accept_candidate_for_recheck(
            candidate.candidate_key,
            [candidate],
            result,
            recheck_callback=callback,
            rules=_RULES,
        )

        self.assertEqual(outcome.status, CANDIDATE_STATUS_REJECTED)
        self.assertEqual(outcome.acceptance_status, CANDIDATE_STATUS_ACCEPTED_FOR_RECHECK)
        self.assertTrue(outcome.recheck_requested)
        self.assertEqual(outcome.recheck_result["status"], RECHECK_STATUS_FAILED)
        self.assertEqual(outcome.error_code, ERROR_RECHECK_CALLBACK_FAILED)
        self.assertNotIn("do-not-leak", str(outcome.to_dict()))
        self.assertEqual(result, before)
        self.assertTrue(outcome.diffs_unchanged)

    def test_unknown_and_non_pending_candidates_are_rejected_without_callback(self):
        cert = _row(row_idx=2)
        draft = _row(row_idx=5)
        result = _result(cert, draft)
        candidate = _candidate(cert, draft)
        called = []

        def callback(_request):
            called.append(True)
            return {"status": "success", "rule_version": "rules-test"}

        unknown = accept_candidate_for_recheck(
            "cand-does-not-exist", [candidate], result,
            recheck_callback=callback, rules=_RULES,
        )
        self.assertEqual(unknown.status, CANDIDATE_STATUS_REJECTED)
        self.assertEqual(unknown.error_code, ERROR_CANDIDATE_UNKNOWN)
        self.assertFalse(unknown.recheck_requested)

        non_pending = replace(candidate, status="accepted_for_recheck")
        rejected = accept_candidate_for_recheck(
            candidate.candidate_key, [non_pending], result,
            recheck_callback=callback, rules=_RULES,
        )
        self.assertEqual(rejected.status, CANDIDATE_STATUS_REJECTED)
        self.assertEqual(rejected.error_code, ERROR_CANDIDATE_STATUS_INVALID)
        self.assertFalse(rejected.recheck_requested)
        self.assertEqual(called, [])

    def test_missing_reference_is_expired(self):
        cert = _row(row_idx=2)
        draft = _row(row_idx=5)
        result = _result(cert, draft)
        missing_draft = _row(row_idx=99)
        candidate = _candidate(cert, missing_draft)

        outcome = accept_candidate_for_recheck(
            candidate.candidate_key, [candidate], result, rules=_RULES
        )

        self.assertEqual(outcome.status, CANDIDATE_STATUS_EXPIRED)
        self.assertEqual(outcome.error_code, ERROR_CANDIDATE_EXPIRED)
        self.assertFalse(outcome.recheck_requested)


class CandidateGuardrailTests(unittest.TestCase):
    def _assert_guardrail(self, cert: DocumentRow, draft: DocumentRow, expected: str):
        result = _result(cert, draft)
        candidate = _candidate(cert, draft)
        called = []

        def callback(_request):
            called.append(True)
            return {"status": "success", "rule_version": "rules-test"}

        outcome = accept_candidate_for_recheck(
            candidate.candidate_key, [candidate], result,
            recheck_callback=callback, rules=_RULES,
        )
        self.assertEqual(outcome.status, CANDIDATE_STATUS_REJECTED)
        self.assertEqual(outcome.error_code, expected)
        self.assertEqual(called, [])

    def test_cross_table_candidate_is_rejected(self):
        self._assert_guardrail(
            _row(row_idx=2, table=1),
            _row(row_idx=5, table=2),
            ERROR_CANDIDATE_TABLE_MISMATCH,
        )

    def test_cross_group_candidate_is_rejected(self):
        self._assert_guardrail(
            _row(row_idx=2, group="G1"),
            _row(row_idx=5, group="G2"),
            ERROR_CANDIDATE_GROUP_MISMATCH,
        )

    def test_swapped_cert_and_draft_references_are_rejected(self):
        cert = _row(row_idx=2)
        draft = _row(row_idx=5)
        result = _result(cert, draft)
        candidate = _candidate(draft, cert)

        outcome = accept_candidate_for_recheck(
            candidate.candidate_key, [candidate], result, rules=_RULES
        )

        self.assertEqual(outcome.status, CANDIDATE_STATUS_REJECTED)
        self.assertEqual(outcome.error_code, ERROR_CANDIDATE_DIRECTION_INVALID)


class ReviewAndDownloadBoundaryTests(unittest.TestCase):
    def test_acceptance_does_not_change_verdict_discipline_or_download_gate(self):
        cert = _row(row_idx=2)
        draft = _row(row_idx=5, model="AAA-2")
        result = _result(cert, draft)
        before = copy.deepcopy(result)
        candidate = _candidate(cert, draft)
        job = Job(status="review", decisions={"diff-original": {"verdict": "accept"}})
        store.jobs[job.job_id] = job
        try:
            outcome = accept_candidate_for_recheck(
                candidate.candidate_key, [candidate], result, rules=_RULES
            )
            self.assertEqual(result, before)
            self.assertEqual(result.diffs[0].review_status, "accept")
            self.assertEqual(result.diffs[0].discipline, "安全")
            self.assertEqual(result.diffs[0].discipline_status, "discipline_pending")
            self.assertEqual(job.status, "review")
            self.assertEqual(job.decisions["diff-original"]["verdict"], "accept")
            self.assertTrue(outcome.manual_confirmation_required)
            self.assertFalse(outcome.download_ready)

            with self.assertRaises(HTTPException) as context:
                asyncio.run(download_result(job.job_id, "draft"))
            self.assertEqual(context.exception.status_code, 409)
        finally:
            store.jobs.pop(job.job_id, None)


if __name__ == "__main__":
    unittest.main()
