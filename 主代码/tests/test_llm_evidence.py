"""任务 2.5：LLM 附属 evidence 的脱敏、兼容和原子写入测试。"""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from report_verify.llm.evidence import (
    EVIDENCE_FILENAME,
    EvidencePathError,
    EvidenceReadError,
    EvidenceValidationError,
    EvidenceWriteError,
    build_evidence,
    read_evidence,
    sanitize_evidence,
    write_evidence,
    write_evidence_for_verification,
)


_HASH = hashlib.sha256(b"local-placeholder").hexdigest()


def _safe_evidence() -> dict:
    return {
        "mode": "candidate_explain",
        "status": "success",
        "capabilities": ["candidate", "explain", "discipline"],
        "policy_version": "policy-v1",
        "schema_version": "reportverify-llm-v1",
        "rule_version": "normalized-v2",
        "trace_id": "trace-local-1",
        "job_id": "job-local-1",
        "candidates": [
            {
                "candidate_key": "cand-local-1",
                "capability": "candidate",
                "cert_ref": {"block_type": "safety", "table_idx": 1, "row_idx": 2},
                "draft_ref": {"block_type": "safety", "table_idx": 1, "row_idx": 5},
                "confidence": 0.9,
                "reason": "同表同组候选，等待人工复核",
                "status": "pending",
                "source": "llm",
                "policy_version": "policy-v1",
                "schema_version": "reportverify-llm-v1",
            }
        ],
        "explanations": [
            {
                "diff_key": "diff-local-1",
                "explanation": "仅记录待展示说明，不改变确定性差异",
                "risk": "需要人工确认",
                "source": "llm",
                "status": "pending",
                "schema_version": "reportverify-llm-v1",
            }
        ],
        "discipline_suggestions": [
            {
                "diff_key": "diff-local-1",
                "candidate_discipline": "安全",
                "reason": "专业候选，未触发路由",
                "confidence": 0.8,
                "source": "llm",
                "status": "pending",
                "rule_version": "discipline-v1",
                "schema_version": "reportverify-llm-v1",
            }
        ],
        "calls": [
            {
                "provider_host": "stub.local",
                "model": "stub-model",
                "attempts": 2,
                "elapsed_ms": 17,
                "transport": "sse",
                "status": "success",
                "request_sha256": _HASH,
                "response_sha256": _HASH,
                "schema_version": "reportverify-llm-v1",
            }
        ],
        "warnings": [{"code": "llm_warning", "message": "本地 stub 仅用于测试"}],
        "error_codes": [],
        "error_code": "",
    }


class EvidencePersistenceTests(unittest.TestCase):
    def test_success_write_read_is_utf8_and_contains_only_summary_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / EVIDENCE_FILENAME
            written = write_evidence(path, _safe_evidence())
            self.assertEqual(written, path.resolve())

            text = path.read_text(encoding="utf-8")
            self.assertIn("等待人工复核", text)
            self.assertNotIn("ensure_ascii", text)
            loaded = read_evidence(path)

        self.assertEqual(loaded["mode"], "candidate_explain")
        self.assertEqual(loaded["status"], "success")
        self.assertEqual(len(loaded["candidates"]), 1)
        self.assertEqual(len(loaded["explanations"]), 1)
        self.assertEqual(len(loaded["discipline_suggestions"]), 1)
        self.assertEqual(loaded["calls"][0]["provider_host"], "stub.local")
        self.assertEqual(loaded["calls"][0]["request_sha256"], _HASH)
        self.assertNotIn("prompt", json.dumps(loaded, ensure_ascii=False))
        self.assertNotIn("response", loaded["calls"][0])

    def test_build_evidence_consumes_existing_suggestion_results_without_metadata_leak(self):
        candidate_result = {
            "status": "success",
            "candidates": [_safe_evidence()["candidates"][0]],
            "metadata": {
                "policy_version": "policy-v2",
                "schema_version": "reportverify-llm-v2",
                "rule_version": "normalized-v3",
                "call": {
                    "provider_host": "stub.local",
                    "model": "stub-model",
                    "attempts": 1,
                    "elapsed_ms": 3,
                    "transport": "json",
                    "status": "success",
                    "request_sha256": _HASH,
                    "response_sha256": _HASH,
                    "prompt": "must never be copied",
                },
            },
        }
        evidence = build_evidence(
            mode="candidate",
            candidate_result=candidate_result,
            trace_id="trace-built",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / EVIDENCE_FILENAME
            write_evidence(path, evidence)
            loaded = read_evidence(path)

        self.assertEqual(loaded["status"], "success")
        self.assertEqual(loaded["policy_version"], "policy-v2")
        self.assertEqual(loaded["calls"][0]["transport"], "json")
        self.assertNotIn("must never be copied", json.dumps(loaded, ensure_ascii=False))
        self.assertNotIn("prompt", json.dumps(loaded, ensure_ascii=False))

    def test_write_as_sidecar_leaves_deterministic_verification_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            verification = Path(directory) / "verification.json"
            original = {
                "cert_path": "/local/secret/cert.docx",
                "result": {
                    "diffs": [{"cert_value": "CERT-ORIGINAL", "draft_value": "DRAFT-ORIGINAL"}],
                    "cert_blocks": [{"rows": ["deterministic"]}],
                },
                "rules": {"version": "normalized-v2"},
                "outputs": {"summary": "/local/out/summary.docx"},
            }
            verification.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
            before = verification.read_bytes()

            sidecar = write_evidence_for_verification(verification, _safe_evidence())
            self.assertEqual(sidecar.name, EVIDENCE_FILENAME)
            self.assertEqual(verification.read_bytes(), before)
            loaded = read_evidence(verification)
            self.assertEqual(loaded["status"], "success")
            self.assertNotIn("CERT-ORIGINAL", json.dumps(loaded, ensure_ascii=False))
            self.assertNotIn("cert_path", json.dumps(loaded, ensure_ascii=False))

    def test_old_verification_without_llm_node_returns_compatible_disabled_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            verification = Path(directory) / "verification.json"
            verification.write_text(
                json.dumps(
                    {
                        "result": {"diffs": [{"cert_value": "CERT-ORIGINAL"}]},
                        "draft_path": "/local/draft.docx",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            loaded = read_evidence(verification)

        self.assertEqual(loaded["status"], "disabled")
        self.assertEqual(loaded["candidates"], [])
        self.assertEqual(loaded["warnings"][0]["code"], "llm_evidence_absent")
        self.assertNotIn("CERT-ORIGINAL", json.dumps(loaded, ensure_ascii=False))
        self.assertNotIn("draft_path", json.dumps(loaded, ensure_ascii=False))

    def test_old_verification_llm_node_is_extracted_without_deterministic_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            verification = Path(directory) / "verification.json"
            legacy = {
                "result": {"diffs": [{"cert_value": "CERT-ORIGINAL"}]},
                "draft_path": "/local/draft.docx",
                "llm": _safe_evidence(),
            }
            verification.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
            loaded = read_evidence(verification)

        self.assertEqual(loaded["trace_id"], "trace-local-1")
        self.assertEqual(len(loaded["calls"]), 1)
        serialized = json.dumps(loaded, ensure_ascii=False)
        self.assertNotIn("CERT-ORIGINAL", serialized)
        self.assertNotIn("draft_path", serialized)

    def test_atomic_replace_failure_keeps_existing_evidence_and_cleans_temp_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / EVIDENCE_FILENAME
            write_evidence(path, _safe_evidence())
            before = path.read_bytes()
            replacement = dict(_safe_evidence(), status="fallback")

            with patch("report_verify.llm.evidence.os.replace", side_effect=OSError("stub")):
                with self.assertRaises(EvidenceWriteError) as raised:
                    write_evidence(path, replacement)

            self.assertEqual(raised.exception.code, "llm_trace_write_failed")
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(Path(directory).glob(f".{EVIDENCE_FILENAME}.*.tmp")), [])


class EvidenceSecurityTests(unittest.TestCase):
    def test_forbidden_fields_are_rejected_before_any_file_is_created(self):
        forbidden_fields = (
            "api_key",
            "user_key",
            "Authorization",
            "prompt",
            "response",
            "cert_value",
            "draft_value",
            "original_text",
            "file_path",
            "image",
            "tool",
            "path",
        )
        for field in forbidden_fields:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / EVIDENCE_FILENAME
                unsafe = dict(_safe_evidence())
                unsafe[field] = "PLACEHOLDER-SENSITIVE-VALUE"
                with self.assertRaises(EvidenceValidationError) as raised:
                    write_evidence(path, unsafe)
                self.assertEqual(raised.exception.code, "llm_trace_redaction_failed")
                self.assertFalse(path.exists())

    def test_nested_forbidden_fields_and_full_url_query_are_rejected(self):
        nested = _safe_evidence()
        nested["candidates"] = [
            dict(nested["candidates"][0], cert_ref={"path": "C:\\secret\\cert.docx"})
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / EVIDENCE_FILENAME
            with self.assertRaises(EvidenceValidationError):
                write_evidence(path, nested)
            self.assertFalse(path.exists())

            full_url = _safe_evidence()
            full_url["calls"] = [
                dict(
                    full_url["calls"][0],
                    provider_host="https://stub.local/v1/chat/completions?user_key=SECRET",
                )
            ]
            with self.assertRaises(EvidenceValidationError):
                write_evidence(path, full_url)
            self.assertFalse(path.exists())

    def test_read_rejects_unsafe_existing_evidence_instead_of_returning_raw_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / EVIDENCE_FILENAME
            unsafe = dict(_safe_evidence(), prompt="do not read")
            path.write_text(json.dumps(unsafe), encoding="utf-8")
            with self.assertRaises(EvidenceValidationError):
                read_evidence(path)

    def test_deterministic_verification_and_job_paths_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ("verification.json", "job.json"):
                with self.subTest(name=name):
                    with self.assertRaises(EvidencePathError):
                        write_evidence(Path(directory) / name, _safe_evidence())

    def test_missing_evidence_has_explicit_read_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(EvidenceReadError) as raised:
                read_evidence(Path(directory) / EVIDENCE_FILENAME)
        self.assertEqual(raised.exception.code, "llm_trace_missing")

    def test_sanitize_evidence_returns_a_copy_without_unknown_fields(self):
        safe = _safe_evidence()
        sanitized = sanitize_evidence(safe)
        sanitized["candidates"][0]["reason"] = "changed outside"
        self.assertEqual(safe["candidates"][0]["reason"], "同表同组候选，等待人工复核")


if __name__ == "__main__":
    unittest.main()
