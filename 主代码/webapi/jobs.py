"""独立 report-verify Web 任务记录和磁盘恢复。"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .settings import settings


@dataclass
class Job:
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "queued"
    stage: str = "等待处理"
    progress: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # 计时：started_at 为真正进入处理（running）的时刻，finished_at 为进入终态
    # （review/done/failed）的时刻；timings 记录各阶段墙钟秒数（deterministic /
    # llm / total）。均为可观测性字段，不影响任务生命周期与下载门禁。
    started_at: str = ""
    finished_at: str = ""
    timings: dict[str, float] = field(default_factory=dict)
    cert_name: str = ""
    draft_name: str = ""
    cert_path: str = ""
    draft_path: str = ""
    out_dir: str = ""
    trace_path: str = ""
    diff_count: int = 0
    decisions_count: int = 0
    error: str = ""
    decisions: dict[str, Any] = field(default_factory=dict)
    # LLM fields are optional sidecar state.  They never replace the
    # deterministic Job.status lifecycle or the download gate.
    llm_mode: str = "off"
    # Distinguishes an explicitly requested ``off`` from a directly constructed
    # legacy Job whose mode should inherit the current server default.  It is
    # persisted for restart-safe task-level mode semantics but omitted from the
    # public summary.
    llm_mode_explicit: bool = False
    llm_status: str = "disabled"
    llm_capabilities: list[str] = field(default_factory=list)
    llm_suggestion_count: int = 0
    llm_warning_count: int = 0
    llm_last_error_code: str = ""
    llm_trace_path: str = ""

    @property
    def job_dir(self) -> Path:
        path = settings.data_dir / self.job_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save(self) -> None:
        self.job_dir.joinpath("job.json").write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _elapsed_seconds(self) -> float | None:
        """已用/总耗时秒数：终态用 total（或 finished-started），运行中用 now-started。"""
        if isinstance(self.timings.get("total"), (int, float)):
            return round(float(self.timings["total"]), 2)
        if not self.started_at:
            return None
        try:
            start = datetime.fromisoformat(self.started_at)
        except ValueError:
            return None
        end = datetime.now(timezone.utc)
        if self.finished_at:
            try:
                end = datetime.fromisoformat(self.finished_at)
            except ValueError:
                pass
        return round((end - start).total_seconds(), 2)

    def summary(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "stage": self.stage,
            "progress": self.progress,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "timings": dict(self.timings),
            "elapsed_seconds": self._elapsed_seconds(),
            "cert_name": self.cert_name,
            "draft_name": self.draft_name,
            "diff_count": self.diff_count,
            "decisions_count": self.decisions_count,
            "llm_mode": self.llm_mode,
            "llm_status": self.llm_status,
            "llm_capabilities": list(self.llm_capabilities),
            "llm_suggestion_count": self.llm_suggestion_count,
            "llm_warning_count": self.llm_warning_count,
            "llm_last_error_code": self.llm_last_error_code,
            "error": self.error,
            "download_ready": self.status == "done",
        }


class JobStore:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.recover()

    def create(self) -> Job:
        job = Job()
        self.jobs[job.job_id] = job
        job.save()
        return job

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def list(self) -> list[Job]:
        return sorted(self.jobs.values(), key=lambda item: item.created_at, reverse=True)

    def recover(self) -> None:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        for job_dir in settings.data_dir.iterdir():
            file_path = job_dir / "job.json"
            if not job_dir.is_dir() or not file_path.exists():
                continue
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                job = Job(**{key: value for key, value in data.items() if key in Job.__dataclass_fields__})
                if job.status in {"running", "queued"}:
                    job.status = "failed"
                    job.stage = "服务重启后任务未完成"
                    job.error = "进程重启中断任务，请重新提交"
                    job.save()
                self.jobs[job.job_id] = job
            except (OSError, ValueError, TypeError):
                continue


store = JobStore()
