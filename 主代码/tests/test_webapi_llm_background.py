"""后台 LLM 编排接入测试（任务 3.2）。

测试只替换确定性流水线和同步编排入口，不开 socket、不访问真实 provider，
并使用占位配置验证 worker/thread、独立 provider semaphore 和生命周期回退。
"""
from __future__ import annotations

import asyncio
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from report_verify.llm.config import LLMSettings

import webapi.app as web_app


_PLACEHOLDER_API_KEY = "PLACEHOLDER-API-KEY-DO-NOT-USE"


def _enabled_settings() -> LLMSettings:
    return LLMSettings(
        mode="candidate",
        base_url="http://127.0.0.1:8765/v1",
        model="local-stub-model",
        api_key=_PLACEHOLDER_API_KEY,
        allowed_hosts=frozenset({"127.0.0.1"}),
    )


class BackgroundLLMExecutionTests(unittest.IsolatedAsyncioTestCase):
    def _job(self, root: str, name: str) -> web_app.Job:
        job = web_app.Job(
            job_id=f"job-{name}",
            cert_path=str(Path(root) / f"{name}-cert.docx"),
            draft_path=str(Path(root) / f"{name}-draft.docx"),
            out_dir=str(Path(root) / f"{name}-run"),
        )
        # Avoid the process-wide web job directory in unit tests.
        job.save = Mock()  # type: ignore[method-assign]
        return job

    async def test_llm_orchestrator_runs_in_worker_and_failure_keeps_review(self):
        main_thread = threading.get_ident()
        deterministic_threads: list[int] = []
        llm_threads: list[int] = []

        def deterministic(*args, **kwargs):
            del args, kwargs
            deterministic_threads.append(threading.get_ident())
            return {"result": {"diffs": []}}

        def failing_orchestrator(*args, **kwargs):
            del args, kwargs
            llm_threads.append(threading.get_ident())
            raise RuntimeError("local stub failure")

        with tempfile.TemporaryDirectory() as root, \
                patch.object(web_app, "semaphore", asyncio.Semaphore(1)), \
                patch.object(web_app, "provider_semaphore", asyncio.Semaphore(1)), \
                patch.object(web_app, "llm_settings", _enabled_settings()), \
                patch.object(web_app, "run_verification", side_effect=deterministic), \
                patch.object(web_app, "_run_llm_orchestrator", side_effect=failing_orchestrator):
            job = self._job(root, "fallback")
            await web_app._execute(job)

        self.assertEqual(job.status, "review")
        self.assertEqual(job.error, "")
        self.assertEqual(job.stage, "等待人工确认（LLM 已回退）")
        self.assertEqual(job.llm_mode, "candidate")
        self.assertEqual(job.llm_status, "fallback")
        self.assertEqual(job.llm_warning_count, 1)
        self.assertEqual(job.llm_last_error_code, "llm_http_error")
        self.assertEqual(len(deterministic_threads), 1)
        self.assertEqual(len(llm_threads), 1)
        self.assertNotEqual(deterministic_threads[0], main_thread)
        self.assertNotEqual(llm_threads[0], main_thread)

    async def test_provider_limit_is_independent_from_deterministic_limit(self):
        deterministic_count = 0
        deterministic_lock = threading.Lock()
        second_deterministic_started = threading.Event()
        provider_observed_second_job = threading.Event()
        provider_lock = threading.Lock()
        active_provider_calls = 0
        max_provider_calls = 0

        def deterministic(*args, **kwargs):
            nonlocal deterministic_count
            del args, kwargs
            with deterministic_lock:
                deterministic_count += 1
                if deterministic_count == 2:
                    second_deterministic_started.set()
            # Leave enough scheduling room for the first job to enter its
            # provider phase before the second deterministic phase completes.
            time.sleep(0.02)
            return {"result": {"diffs": []}}

        def successful_orchestrator(*args, **kwargs):
            nonlocal active_provider_calls, max_provider_calls
            del args, kwargs
            with provider_lock:
                active_provider_calls += 1
                max_provider_calls = max(max_provider_calls, active_provider_calls)
            try:
                # If the deterministic semaphore were held during this call,
                # the second job could not reach this event before the timeout.
                if second_deterministic_started.wait(0.75):
                    provider_observed_second_job.set()
                else:
                    raise AssertionError(
                        "provider phase blocked the deterministic worker slot"
                    )
                time.sleep(0.02)
                return {"status": "success"}
            finally:
                with provider_lock:
                    active_provider_calls -= 1

        with tempfile.TemporaryDirectory() as root, \
                patch.object(web_app, "semaphore", asyncio.Semaphore(1)), \
                patch.object(web_app, "provider_semaphore", asyncio.Semaphore(1)), \
                patch.object(web_app, "llm_settings", _enabled_settings()), \
                patch.object(web_app, "run_verification", side_effect=deterministic), \
                patch.object(web_app, "_run_llm_orchestrator", side_effect=successful_orchestrator):
            jobs = [self._job(root, "one"), self._job(root, "two")]
            await asyncio.wait_for(
                asyncio.gather(*(web_app._execute(job) for job in jobs)),
                timeout=3,
            )

        self.assertTrue(provider_observed_second_job.is_set())
        self.assertEqual(max_provider_calls, 1)
        self.assertEqual([job.status for job in jobs], ["review", "review"])
        self.assertEqual([job.llm_status for job in jobs], ["success", "success"])

    async def test_mode_off_does_not_call_orchestrator_and_keeps_existing_stage(self):
        def deterministic(*args, **kwargs):
            del args, kwargs
            return {"result": {"diffs": []}}

        orchestrator = Mock()
        off_settings = LLMSettings(mode="off")
        with tempfile.TemporaryDirectory() as root, \
                patch.object(web_app, "semaphore", asyncio.Semaphore(1)), \
                patch.object(web_app, "provider_semaphore", asyncio.Semaphore(1)), \
                patch.object(web_app, "llm_settings", off_settings), \
                patch.object(web_app, "run_verification", side_effect=deterministic), \
                patch.object(web_app, "_run_llm_orchestrator", orchestrator):
            job = self._job(root, "off")
            await web_app._execute(job)

        orchestrator.assert_not_called()
        self.assertEqual(job.status, "review")
        self.assertEqual(job.stage, "等待人工确认")
        self.assertEqual(job.progress, 0.7)


if __name__ == "__main__":
    unittest.main()
