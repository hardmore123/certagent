"""Task 3.3 Web API compatibility and redacted evidence tests.

All requests use placeholder documents and placeholder configuration.  The
background task is discarded before execution, so these tests never contact a
provider or execute the deterministic document pipeline.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

import webapi.app as web_app
from report_verify.llm.config import LLMSettings
from report_verify.llm.evidence import write_evidence_for_verification
from webapi.jobs import Job, store
from webapi.settings import settings


_PLACEHOLDER_API_KEY = "PLACEHOLDER-API-KEY-DO-NOT-USE"


def _server_settings(
    *,
    mode: str = "off",
    allowed_modes: frozenset[str] | None = None,
) -> LLMSettings:
    return LLMSettings(
        mode=mode,  # type: ignore[arg-type]
        base_url="http://127.0.0.1:8765/v1",
        model="local-stub-model",
        api_key=_PLACEHOLDER_API_KEY,
        allowed_hosts=frozenset({"127.0.0.1"}),
        allow_plaintext=True,
        allowed_job_modes=allowed_modes or frozenset(
            {"off", "candidate", "explain", "candidate_explain"}
        ),
    )


def _discard_task(coro):
    """Close the scheduled coroutine so the route test cannot run a job."""

    coro.close()
    return Mock()


def _multipart(client: TestClient, *, data: dict[str, str] | None = None):
    files = {
        "cert": ("cert.docx", b"CERT PLACEHOLDER", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        "draft": ("draft.docx", b"DRAFT PLACEHOLDER", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    }
    return client.post("/api/jobs", files=files, data=data or {})


class CreateJobCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.created_ids: set[str] = set()

    def _post(self, root: str, llm_settings: LLMSettings, *, data=None):
        before = set(store.jobs)
        with (
            patch.object(settings, "data_dir", Path(root)),
            patch.object(web_app, "llm_settings", llm_settings),
            patch.object(web_app.asyncio, "create_task", side_effect=_discard_task),
        ):
            response = _multipart(TestClient(web_app.app), data=data)
        created = set(store.jobs) - before
        self.created_ids.update(created)
        return response, created

    def tearDown(self):
        # The route creates real job records before scheduling the worker.  Keep
        # the process-wide store isolated between tests.
        for job_id in self.created_ids:
            store.jobs.pop(job_id, None)

    def test_legacy_multipart_without_llm_mode_still_succeeds(self):
        with tempfile.TemporaryDirectory() as root:
            response, created = self._post(root, _server_settings())

            self.assertEqual(response.status_code, 202)
            payload = response.json()
            self.assertEqual(payload["status"], "queued")
            self.assertEqual(payload["llm_mode"], "off")
            self.assertEqual(payload["llm_status"], "disabled")
            self.assertFalse(payload["download_ready"])
            self.assertTrue(created)
            self.assertNotIn("api_key", json.dumps(payload))
            self.assertNotIn("Authorization", json.dumps(payload))

    def test_allowlisted_task_mode_is_saved_and_appended_to_response(self):
        with tempfile.TemporaryDirectory() as root:
            response, created = self._post(
                root,
                _server_settings(mode="candidate_explain"),
                data={"llm_mode": "candidate"},
            )

            self.assertEqual(response.status_code, 202)
            payload = response.json()
            self.assertEqual(payload["llm_mode"], "candidate")
            self.assertEqual(payload["status"], "queued")
            self.assertTrue(created)
            job = store.get(next(iter(created)))
            self.assertIsNotNone(job)
            assert job is not None
            self.assertEqual(job.llm_mode, "candidate")
            self.assertTrue(job.llm_mode_explicit)

    def test_unknown_or_unallowlisted_mode_returns_stable_400_without_creating_job(self):
        with tempfile.TemporaryDirectory() as root:
            before = set(store.jobs)
            response, created = self._post(
                root,
                _server_settings(
                    mode="candidate_explain",
                    allowed_modes=frozenset({"off", "candidate"}),
                ),
                data={"llm_mode": "explain"},
            )

            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["detail"]["code"], "llm_task_mode_not_allowed")
            self.assertEqual(created, set())
            self.assertEqual(set(store.jobs), before)

    def test_unknown_mode_is_also_rejected_before_upload_persistence(self):
        with tempfile.TemporaryDirectory() as root:
            response, created = self._post(
                root,
                _server_settings(),
                data={"llm_mode": "vision"},
            )

            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["detail"]["code"], "llm_task_mode_not_allowed")
            self.assertEqual(created, set())
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_task_cannot_override_provider_or_externalization_policy(self):
        with tempfile.TemporaryDirectory() as root:
            response, created = self._post(
                root,
                _server_settings(mode="candidate_explain"),
                data={"llm_mode": "candidate", "model": "attacker-model"},
            )

            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["detail"]["code"], "llm_task_mode_not_allowed")
            self.assertEqual(created, set())


class LLMEvidenceRouteTests(unittest.TestCase):
    def _job_with_verification(self, root: str, *, sidecar: bool) -> tuple[Job, bytes]:
        verification = Path(root) / "verification.json"
        deterministic = {
            "result": {
                "diffs": [
                    {"cert_value": "CERT-ORIGINAL-MUST-STAY-LOCAL", "draft_value": "DRAFT-ORIGINAL"}
                ]
            },
            "draft_path": "C:/private/draft.docx",
        }
        verification.write_text(json.dumps(deterministic, ensure_ascii=False), encoding="utf-8")
        before = verification.read_bytes()
        if sidecar:
            write_evidence_for_verification(
                verification,
                {
                    "mode": "candidate",
                    "status": "success",
                    "capabilities": ["candidate"],
                    "candidates": [],
                    "explanations": [],
                    "discipline_suggestions": [],
                    "calls": [],
                    "warnings": [],
                    "error_codes": [],
                    "policy_version": "policy-v1",
                    "schema_version": "reportverify-llm-v1",
                    "rule_version": "normalized-v2",
                    "trace_id": "trace-local",
                    "job_id": "job-local",
                },
            )
        return (
            Job(
                job_id="test-evidence-job",
                status="review",
                out_dir=root,
                trace_path=str(verification),
            ),
            before,
        )

    def test_route_reads_validated_sidecar_and_never_returns_deterministic_or_secret_fields(self):
        with tempfile.TemporaryDirectory() as root:
            job, verification_before = self._job_with_verification(root, sidecar=True)
            store.jobs[job.job_id] = job
            try:
                response = TestClient(web_app.app).get(
                    f"/api/jobs/{job.job_id}/llm-evidence"
                )

                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["status"], "success")
                self.assertEqual(payload["mode"], "candidate")
                serialized = json.dumps(payload, ensure_ascii=False)
                self.assertNotIn("CERT-ORIGINAL-MUST-STAY-LOCAL", serialized)
                self.assertNotIn("DRAFT-ORIGINAL", serialized)
                self.assertNotIn("api_key", serialized.lower())
                self.assertNotIn("authorization", serialized.lower())
                self.assertNotIn("prompt", serialized.lower())
                self.assertNotIn("response", serialized.lower())
                self.assertEqual(
                    Path(job.trace_path).read_bytes(), verification_before
                )
                self.assertTrue((Path(root) / "llm-evidence.json").exists())
            finally:
                store.jobs.pop(job.job_id, None)

    def test_legacy_without_sidecar_returns_safe_disabled_evidence(self):
        with tempfile.TemporaryDirectory() as root:
            job, verification_before = self._job_with_verification(root, sidecar=False)
            store.jobs[job.job_id] = job
            try:
                response = TestClient(web_app.app).get(
                    f"/api/jobs/{job.job_id}/llm-evidence"
                )

                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["status"], "disabled")
                self.assertEqual(payload["warnings"][0]["code"], "llm_evidence_absent")
                self.assertNotIn("CERT-ORIGINAL-MUST-STAY-LOCAL", json.dumps(payload))
                self.assertEqual(Path(job.trace_path).read_bytes(), verification_before)
            finally:
                store.jobs.pop(job.job_id, None)

    def test_unsafe_sidecar_is_rejected_without_returning_raw_content(self):
        with tempfile.TemporaryDirectory() as root:
            job, _ = self._job_with_verification(root, sidecar=False)
            sidecar = Path(root) / "llm-evidence.json"
            sidecar.write_text(
                json.dumps({"prompt": "DO-NOT-RETURN"}), encoding="utf-8"
            )
            store.jobs[job.job_id] = job
            try:
                response = TestClient(web_app.app).get(
                    f"/api/jobs/{job.job_id}/llm-evidence"
                )

                self.assertEqual(response.status_code, 500)
                self.assertEqual(
                    response.json()["detail"]["code"], "llm_trace_redaction_failed"
                )
                self.assertNotIn("DO-NOT-RETURN", response.text)
            finally:
                store.jobs.pop(job.job_id, None)


if __name__ == "__main__":
    unittest.main()
