"""任务注册表：进程内 dict + JSON 持久化。"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .settings import settings


class JobRecord:
    def __init__(self, job_id: str | None = None):
        self.job_id = job_id or str(uuid.uuid4())
        self.status = "queued"
        self.stage = ""
        self.progress = 0.0
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.file_orig = ""
        self.file_plm = ""
        self.owner = ""
        self.error = ""
        self.diff_count = 0
        self.out_merged = ""
        self.out_compare = ""
        self.fuzzy_llm = False  # 该任务是否启用 LLM 智能配对（前端按需勾选）
        self.state: dict[str, Any] = {}  # pipeline state（内存中，不落盘）

    @property
    def job_dir(self) -> Path:
        d = settings.JOBS_DIR / self.job_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save(self) -> None:
        data = {
            "job_id": self.job_id,
            "status": self.status,
            "stage": self.stage,
            "progress": self.progress,
            "created_at": self.created_at,
            "file_orig": self.file_orig,
            "file_plm": self.file_plm,
            "owner": self.owner,
            "error": self.error,
            "diff_count": self.diff_count,
            "out_merged": self.out_merged,
            "out_compare": self.out_compare,
            "fuzzy_llm": self.fuzzy_llm,
        }
        (self.job_dir / "job.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def to_summary(self) -> dict:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "stage": self.stage,
            "progress": self.progress,
            "created_at": self.created_at,
            "file_orig": self.file_orig,
            "file_plm": self.file_plm,
            "diff_count": self.diff_count,
            "error": self.error,
        }


class JobRegistry:
    def __init__(self):
        self._jobs: dict[str, JobRecord] = {}

    def create(self, owner: str) -> JobRecord:
        rec = JobRecord()
        rec.owner = owner
        self._jobs[rec.job_id] = rec
        rec.save()
        return rec

    def get(self, job_id: str) -> JobRecord | None:
        return self._jobs.get(job_id)

    def list_all(self, owner: str | None = None) -> list[JobRecord]:
        jobs = list(self._jobs.values())
        if owner:
            jobs = [j for j in jobs if j.owner == owner]
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)

    def recover(self) -> None:
        """进程重启时从磁盘恢复历史任务。"""
        if not settings.JOBS_DIR.exists():
            return
        for d in settings.JOBS_DIR.iterdir():
            if not d.is_dir():
                continue
            jf = d / "job.json"
            if jf.exists():
                data = json.loads(jf.read_text(encoding="utf-8"))
                rec = JobRecord(data["job_id"])
                for k, v in data.items():
                    if hasattr(rec, k):
                        setattr(rec, k, v)
                self._jobs[rec.job_id] = rec


registry = JobRegistry()
