"""独立 Web 配置，输入和输出不进入 CertAgent 任务目录。"""
from __future__ import annotations

import os
from pathlib import Path


class Settings:
    data_dir = Path(os.getenv("REPORT_VERIFY_DATA_DIR", str(Path(__file__).resolve().parents[1] / "runs" / "web_jobs"))).resolve()
    max_upload_mb = int(os.getenv("REPORT_VERIFY_MAX_UPLOAD_MB", "500"))
    max_concurrent_jobs = int(os.getenv("REPORT_VERIFY_MAX_CONCURRENT_JOBS", "2"))
    # Provider concurrency is deliberately independent from deterministic job
    # concurrency.  Keep the default conservative and never let it exceed the
    # worker limit, so LLM calls cannot exhaust the deterministic job slots.
    llm_max_concurrent = max(
        1,
        min(
            max_concurrent_jobs,
            int(os.getenv("REPORT_VERIFY_LLM_MAX_CONCURRENT", "1")),
        ),
    )
    api_key = os.getenv("REPORT_VERIFY_API_KEY", "")
    comment_author = os.getenv("REPORT_VERIFY_COMMENT_AUTHOR", "ReportVerify")
    comment_initials = os.getenv("REPORT_VERIFY_COMMENT_INITIALS", "RV")
    allowed_extensions = {".doc", ".docx"}


settings = Settings()
