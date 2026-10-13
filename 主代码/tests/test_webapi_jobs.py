from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from webapi.app import app
from webapi.jobs import Job, JobStore, store
from webapi.settings import settings


class JobLLMStateTests(unittest.TestCase):
    def test_new_job_has_optional_disabled_llm_state_in_summary(self):
        job = Job()

        summary = job.summary()

        self.assertEqual(job.status, "queued")
        self.assertEqual(job.llm_mode, "off")
        self.assertEqual(job.llm_status, "disabled")
        self.assertEqual(job.llm_capabilities, [])
        self.assertEqual(summary["llm_mode"], "off")
        self.assertEqual(summary["llm_status"], "disabled")
        self.assertEqual(summary["llm_capabilities"], [])
        self.assertEqual(summary["llm_suggestion_count"], 0)
        self.assertEqual(summary["llm_warning_count"], 0)
        self.assertEqual(summary["llm_last_error_code"], "")
        self.assertFalse(summary["download_ready"])

    def test_legacy_job_json_recovers_with_llm_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            job_id = "legacy-review-job"
            job_dir = data_dir / job_id
            job_dir.mkdir()
            (job_dir / "job.json").write_text(
                json.dumps(
                    {
                        "job_id": job_id,
                        "status": "review",
                        "stage": "等待人工确认",
                        "progress": 0.7,
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "cert_name": "cert.docx",
                        "draft_name": "draft.docx",
                        "diff_count": 2,
                        "decisions_count": 0,
                        "error": "",
                        "decisions": {},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.object(settings, "data_dir", data_dir):
                restored = JobStore().get(job_id)

            self.assertIsNotNone(restored)
            assert restored is not None
            self.assertEqual(restored.status, "review")
            self.assertEqual(restored.llm_mode, "off")
            self.assertEqual(restored.llm_status, "disabled")
            self.assertEqual(restored.llm_capabilities, [])
            self.assertEqual(restored.llm_suggestion_count, 0)
            self.assertEqual(restored.llm_warning_count, 0)
            self.assertEqual(restored.llm_last_error_code, "")
            self.assertFalse(restored.summary()["download_ready"])

    def test_llm_fallback_round_trips_without_changing_deterministic_status(self):
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            job = Job(
                status="review",
                stage="等待人工确认",
                llm_mode="candidate_explain",
                llm_status="fallback",
                llm_capabilities=["candidate", "explain"],
                llm_suggestion_count=0,
                llm_warning_count=1,
                llm_last_error_code="llm_http_error",
                llm_trace_path="run/llm-evidence.json",
            )

            with patch.object(settings, "data_dir", data_dir):
                job.save()
                raw = json.loads(
                    (data_dir / job.job_id / "job.json").read_text(encoding="utf-8")
                )
                restored = JobStore().get(job.job_id)

            self.assertEqual(raw["llm_mode"], "candidate_explain")
            self.assertEqual(raw["llm_status"], "fallback")
            self.assertEqual(raw["llm_capabilities"], ["candidate", "explain"])
            self.assertNotIn("api_key", raw)
            self.assertNotIn("user_key", raw)
            self.assertNotIn("Authorization", raw)
            self.assertIsNotNone(restored)
            assert restored is not None
            self.assertEqual(restored.status, "review")
            self.assertEqual(restored.llm_status, "fallback")
            self.assertEqual(restored.llm_warning_count, 1)
            self.assertEqual(restored.llm_last_error_code, "llm_http_error")
            self.assertEqual(restored.llm_trace_path, "run/llm-evidence.json")
            self.assertFalse(restored.summary()["download_ready"])

    def test_job_api_summary_appends_llm_fields(self):
        job = Job(
            status="review",
            llm_mode="explain",
            llm_status="skipped_policy",
            llm_capabilities=["explain"],
            llm_warning_count=1,
            llm_last_error_code="llm_policy_denied",
        )
        store.jobs[job.job_id] = job
        try:
            response = TestClient(app).get(f"/api/jobs/{job.job_id}")

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["status"], "review")
            self.assertEqual(payload["llm_mode"], "explain")
            self.assertEqual(payload["llm_status"], "skipped_policy")
            self.assertEqual(payload["llm_capabilities"], ["explain"])
            self.assertEqual(payload["llm_warning_count"], 1)
            self.assertEqual(payload["llm_last_error_code"], "llm_policy_denied")
            self.assertFalse(payload["download_ready"])
        finally:
            store.jobs.pop(job.job_id, None)

    def test_llm_state_does_not_change_existing_status_or_download_gate(self):
        for status in ("queued", "running", "review", "done", "failed"):
            with self.subTest(status=status):
                summary = Job(
                    status=status,
                    llm_mode="candidate",
                    llm_status="skipped_policy",
                    llm_warning_count=1,
                    llm_last_error_code="llm_policy_denied",
                ).summary()
                self.assertEqual(summary["status"], status)
                self.assertEqual(summary["download_ready"], status == "done")


if __name__ == "__main__":
    unittest.main()
