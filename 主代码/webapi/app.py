"""独立 ReportVerify FastAPI：上传、异步核对、人工确认、下载。"""
from __future__ import annotations

import asyncio
import json
import shutil
import time
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from starlette.datastructures import UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from report_verify.env_bootstrap import load_project_env
from report_verify.llm.client import ERROR_HTTP_ERROR, LLMClient
from report_verify.llm.config import LLMConfigurationError, LLMSettings
from report_verify.llm.evidence import (
    EvidenceError,
    build_evidence,
    read_evidence,
    write_evidence_for_verification,
)
from report_verify.llm.explain import generate_diff_explanations
from report_verify.llm.jobmode import authorize_job_creation
from report_verify.llm.orchestrator import run_candidate_orchestrator
from report_verify.llm.policy import (
    PolicyError,
    authorize_outbound,
    check_server_policy,
)
from report_verify.models import (
    Anchor,
    DocumentRow,
    LocatedBlock,
    RowDiff,
    UnrecognizedTable,
    VerifyDiff,
    VerifyResult,
)
from report_verify.pipeline import run_verification
from report_verify.review import (
    diff_from_dict,
    finalize_review,
    memory_hints,
    normalize_manual_decisions,
)

from .jobs import Job, store
from .settings import settings

app = FastAPI(title="报告草稿准确性核对", version="0.1.0")
semaphore = asyncio.Semaphore(settings.max_concurrent_jobs)
# This semaphore is intentionally separate from ``semaphore``.  Deterministic
# parsing/comparison can continue while another job waits for the provider, and
# all synchronous provider work is still bounded before it enters a worker.
provider_semaphore = asyncio.Semaphore(settings.llm_max_concurrent)

# LLM 状态是 deterministic review 的附属状态。它们只能影响 review 提示，
# 不能改变 Job.status 或下载门禁；所有从 evidence 投影到 job summary 的值也
# 必须先经过这里的有限集合/错误码白名单，避免不可信 provider 细节进入 job.json。
_LLM_EVIDENCE_STATUSES = frozenset({
    "disabled",
    "skipped_policy",
    "success",
    "fallback",
    "invalid",
    "misconfigured",
})
_LLM_WARNING_STATUSES = frozenset({"skipped_policy", "fallback", "invalid", "misconfigured"})
_LLM_CAPABILITIES = frozenset({"candidate", "explain", "discipline"})
_LLM_SAFE_ERROR_CODES = frozenset({
    "llm_policy_denied",
    "llm_image_externalization_rejected",
    "llm_task_mode_not_allowed",
    "llm_misconfigured",
    "llm_response_empty",
    "llm_response_too_large",
    "llm_http_error",
    "llm_attempt_timeout",
    "llm_total_timeout",
    "llm_rate_limited",
    "llm_auth_failed",
    "llm_circuit_open",
    "llm_schema_invalid",
    "llm_safety_rejected",
    "llm_trace_redaction_failed",
})
_LLM_DEFAULT_WARNING_CODES = {
    "skipped_policy": "llm_policy_denied",
    "fallback": "llm_http_error",
    "invalid": "llm_schema_invalid",
    "misconfigured": "llm_misconfigured",
}


def _load_llm_settings() -> LLMSettings:
    """Load server LLM settings without making invalid optional config fatal."""

    try:
        return LLMSettings.from_env()
    except LLMConfigurationError:
        # An invalid optional LLM configuration must leave the deterministic
        # service usable.  Do not include the rejected value in any diagnostic.
        return LLMSettings()


# Load project-root .env before reading the runtime LLM configuration.  Real
# process environment variables always take priority; load_project_env only
# fills in keys that are not already set, and never overrides mode=off behavior.
load_project_env()
llm_settings = _load_llm_settings()
# The client (and its thread-safe provider circuit breaker) is shared across
# jobs; the provider semaphore above limits concurrent calls to this client.
llm_client = LLMClient(llm_settings)


@app.middleware("http")
async def api_key_guard(request: Request, call_next):
    if settings.api_key and request.url.path != "/api/health":
        if request.headers.get("X-ReportVerify-Key") != settings.api_key:
            return JSONResponse({"detail": "API key 无效"}, status_code=401)
    return await call_next(request)


async def _save_upload(upload: UploadFile, target: Path) -> None:
    filename = Path(upload.filename or "").name
    suffix = Path(filename).suffix.lower()
    if suffix not in settings.allowed_extensions:
        raise HTTPException(400, f"仅支持 .doc/.docx，收到：{suffix or '无扩展名'}")
    limit = settings.max_upload_mb * 1024 * 1024
    size = 0
    with target.open("wb") as output:
        while chunk := await upload.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                target.unlink(missing_ok=True)
                raise HTTPException(413, f"文件超过 {settings.max_upload_mb} MB 限制")
            output.write(chunk)


def _trace_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _trace_anchor(value: Any) -> Anchor | None:
    raw = _trace_mapping(value)
    if not raw:
        return None
    return Anchor(
        table_idx=int(raw.get("table_idx", 0)),
        row_idx=int(raw.get("row_idx", 0)),
        cell_idx=int(raw.get("cell_idx", 0)),
        para_hint=str(raw.get("para_hint", "") or ""),
    )


def _trace_row(value: Any) -> DocumentRow:
    raw = _trace_mapping(value)
    values_raw = _trace_mapping(raw.get("values"))
    anchors_raw = _trace_mapping(raw.get("anchors"))
    anchors = {
        str(key): anchor
        for key, item in anchors_raw.items()
        if (anchor := _trace_anchor(item)) is not None
    }
    return DocumentRow(
        block_type=str(raw.get("block_type", "") or ""),
        row_idx=int(raw.get("row_idx", 0)),
        values={
            str(key): "" if item is None else str(item)
            for key, item in values_raw.items()
        },
        anchors=anchors,
        raw_cells=[str(item) for item in (raw.get("raw_cells") or [])],
        source_table=int(raw.get("source_table", 0)),
        group=str(raw.get("group", "") or ""),
    )


def _trace_block(value: Any) -> LocatedBlock:
    raw = _trace_mapping(value)
    return LocatedBlock(
        block_type=str(raw.get("block_type", "") or ""),
        table_idx=int(raw.get("table_idx", 0)),
        header=[str(item) for item in (raw.get("header") or [])],
        rows=[_trace_row(item) for item in (raw.get("rows") or [])],
        recognized=bool(raw.get("recognized", True)),
        note=str(raw.get("note", "") or ""),
    )


def _trace_diff(value: Any) -> VerifyDiff:
    raw = _trace_mapping(value)
    return VerifyDiff(
        key=str(raw.get("key", "") or ""),
        block_type=str(raw.get("block_type", "") or ""),
        item_name=str(raw.get("item_name", "") or ""),
        diff_type=str(raw.get("diff_type", "") or ""),
        field=str(raw.get("field", "") or ""),
        cert_value=str(raw.get("cert_value", "") or ""),
        draft_value=str(raw.get("draft_value", "") or ""),
        cert_location=str(raw.get("cert_location", "") or ""),
        draft_anchor=_trace_anchor(raw.get("draft_anchor")),
        discipline=raw.get("discipline"),
        discipline_status=str(raw.get("discipline_status", "discipline_pending") or ""),
        rule_version=raw.get("rule_version"),
        comment_written=bool(raw.get("comment_written", False)),
        comment_error=str(raw.get("comment_error", "") or ""),
        review_status=str(raw.get("review_status", "unreviewed") or ""),
        review_note=str(raw.get("review_note", "") or ""),
        reviewed_by=str(raw.get("reviewed_by", "") or ""),
        match_confidence=float(raw.get("match_confidence", 1.0)),
        match_reason=str(raw.get("match_reason", "") or ""),
        match_status=str(raw.get("match_status", "matched") or ""),
        row_key=str(raw.get("row_key", "") or ""),
    )


def _trace_row_diff(value: Any) -> RowDiff:
    raw = _trace_mapping(value)
    return RowDiff(
        row_key=str(raw.get("row_key", "") or ""),
        block_type=str(raw.get("block_type", "") or ""),
        row_status=str(raw.get("row_status", "") or ""),
        row_kind=str(raw.get("row_kind", "row") or ""),
        item_name=str(raw.get("item_name", "") or ""),
        cert_row=dict(_trace_mapping(raw.get("cert_row"))),
        draft_row=dict(_trace_mapping(raw.get("draft_row"))),
        cert_row_ref=dict(_trace_mapping(raw.get("cert_row_ref"))),
        draft_row_ref=dict(_trace_mapping(raw.get("draft_row_ref"))),
        changed_fields=[str(item) for item in (raw.get("changed_fields") or [])],
        diff_keys=[str(item) for item in (raw.get("diff_keys") or [])],
        match_confidence=float(raw.get("match_confidence", 1.0)),
        match_reason=str(raw.get("match_reason", "") or ""),
        match_status=str(raw.get("match_status", "matched") or ""),
    )


def _trace_result(trace: Mapping[str, Any]) -> VerifyResult:
    """Rehydrate only deterministic result data for the read-only LLM layer."""

    raw = _trace_mapping(trace.get("result"))
    rules = _trace_mapping(trace.get("rules"))
    return VerifyResult(
        cert_blocks=[_trace_block(item) for item in (raw.get("cert_blocks") or [])],
        draft_blocks=[_trace_block(item) for item in (raw.get("draft_blocks") or [])],
        unrecognized_cert_tables=[
            UnrecognizedTable(
                table_idx=int(table.get("table_idx", 0)),
                rows=int(table.get("rows", 0)),
                columns=int(table.get("columns", 0)),
                preview=str(table.get("preview", "") or ""),
                reason=str(table.get("reason", "未命中目标子块表头指纹") or ""),
            )
            for item in (raw.get("unrecognized_cert_tables") or [])
            if (table := _trace_mapping(item))
        ],
        diffs=[_trace_diff(item) for item in (raw.get("diffs") or [])],
        row_diffs=[_trace_row_diff(item) for item in (raw.get("row_diffs") or [])],
        warnings=[str(item) for item in (raw.get("warnings") or [])],
        rule_version=str(
            raw.get("rule_version") or rules.get("version") or "normalized-v2"
        ),
    )


def _settings_for_job(job: Job) -> LLMSettings:
    """Return server settings with only the already-authorized job mode.

    All provider, credential, endpoint, host/TLS, redaction and image fields
    remain server-owned.  ``llm_mode_explicit`` also lets a requested ``off``
    stay off; directly constructed legacy ``Job`` objects without that marker
    continue to inherit the server default used by older worker callers.
    """

    mode = job.llm_mode
    if mode not in {"off", "candidate", "explain", "candidate_explain"}:
        mode = llm_settings.mode
    if mode == "off" and not job.llm_mode_explicit:
        mode = llm_settings.mode
    if mode == llm_settings.mode:
        return llm_settings
    return replace(llm_settings, mode=mode)  # type: ignore[arg-type]


def _run_llm_orchestrator(
    trace: Mapping[str, Any],
    *,
    trace_id: str,
    verification_path: str,
    runtime_settings: LLMSettings | None = None,
) -> dict[str, Any]:
    """Run optional LLM capabilities synchronously in a worker thread.

    The caller owns the provider semaphore and this function never changes the
    deterministic trace.  It writes only the separately validated evidence
    sidecar; provider payloads and raw responses never leave this call boundary.
    ``runtime_settings`` may change only the mode selected by the already
    authorized task request; all server policy/provider fields stay unchanged.
    """

    settings_for_call = runtime_settings or llm_settings
    result = _trace_result(trace)
    mode = settings_for_call.mode
    candidate_result = None
    explanation_result = None
    capabilities: list[str] = []

    if mode in {"candidate", "candidate_explain"}:
        capabilities.append("candidate")
        candidate_result = run_candidate_orchestrator(
            result,
            llm_client,
            settings_for_call,
            trace_id=trace_id,
        )

    if mode in {"explain", "candidate_explain"}:
        capabilities.append("explain")
        explanation_result = generate_diff_explanations(
            result,
            settings_for_call,
            client=llm_client,
            trace_id=trace_id,
        )

    evidence = build_evidence(
        mode=mode,
        capabilities=capabilities,
        candidate_result=candidate_result,
        explanation_result=explanation_result,
        policy_version=settings_for_call.policy_version,
        schema_version=settings_for_call.response_schema_version,
        rule_version=result.rule_version,
        trace_id=trace_id,
        job_id=trace_id,
    )
    write_evidence_for_verification(verification_path, evidence)
    return evidence.to_dict()


def _llm_review_stage(evidence: Mapping[str, Any]) -> str:
    """Render a fixed, non-sensitive review warning for LLM-only outcomes.

    This function intentionally has no transition to ``done``.  The caller
    always finishes in ``review`` and ``finalize_review`` remains the only
    success path to a downloadable result.
    """

    status = str(evidence.get("status", "") or "")
    if status == "success":
        return "等待人工确认（LLM 建议仅供复核）"
    if status == "disabled":
        return "等待人工确认（LLM 已关闭）"
    if status == "skipped_policy":
        return "等待人工确认（LLM 策略跳过）"
    if status == "misconfigured":
        return "等待人工确认（LLM 配置无效，已回退）"
    if status == "invalid":
        return "等待人工确认（LLM 响应无效，已回退）"
    if status == "fallback":
        return "等待人工确认（LLM 已回退）"
    # Unknown evidence is never allowed to become a success signal.  The
    # projection layer normalizes it to fallback, but keep this defensive
    # branch fixed and free of provider/error text as well.
    return "等待人工确认（LLM 状态无效，已回退）"


def _llm_capabilities(mode: str) -> list[str]:
    capabilities: list[str] = []
    if mode in {"candidate", "candidate_explain"}:
        capabilities.append("candidate")
    if mode in {"explain", "candidate_explain"}:
        capabilities.append("explain")
    return capabilities


def _apply_llm_evidence(job: Job, evidence: Mapping[str, Any]) -> None:
    """Project only canonical, non-sensitive evidence fields into job state.

    LLM evidence is untrusted input at this boundary.  Only stable status,
    capability, and error-code values are copied to ``job.json``; warning text,
    prompt/response content, credentials, and document values are never copied.
    Failure-like statuses always receive at least one review warning, including
    a policy skip with no provider call.
    """

    raw_status = str(evidence.get("status", "fallback") or "fallback")
    status = raw_status if raw_status in _LLM_EVIDENCE_STATUSES else "fallback"

    raw_codes = evidence.get("error_codes")
    error_codes = list(raw_codes) if isinstance(raw_codes, (list, tuple)) else []
    raw_error_code = evidence.get("error_code", "")
    if raw_error_code:
        error_codes.insert(0, raw_error_code)
    safe_error_codes = [
        code for code in error_codes
        if isinstance(code, str) and code in _LLM_SAFE_ERROR_CODES
    ]

    # A configuration failure is surfaced distinctly, while all other provider
    # failures remain non-terminal fallback states.  This mapping is intentionally
    # based only on allowlisted codes/statuses, never on exception text.
    if "llm_misconfigured" in safe_error_codes or status == "misconfigured":
        status = "misconfigured"
    error_code = (
        safe_error_codes[0]
        if safe_error_codes
        else _LLM_DEFAULT_WARNING_CODES.get(status, "")
    )
    if status == "disabled":
        error_code = ""
        safe_error_codes = []

    job.llm_status = status
    capabilities = evidence.get("capabilities")
    if isinstance(capabilities, (list, tuple)):
        job.llm_capabilities = [
            item for item in capabilities
            if isinstance(item, str) and item in _LLM_CAPABILITIES
        ]
    else:
        job.llm_capabilities = _llm_capabilities(job.llm_mode)

    warning_items = evidence.get("warnings")
    warning_count = len(warning_items) if isinstance(warning_items, (list, tuple)) else 0
    if status in _LLM_WARNING_STATUSES:
        # The warning is represented by a stable code/stage only.  Never expose
        # an evidence warning message in job summary or review UI.
        warning_count = max(warning_count, len(safe_error_codes), 1)
    job.llm_warning_count = warning_count
    job.llm_last_error_code = error_code
    job.llm_suggestion_count = sum(
        len(items) if isinstance(items, (list, tuple)) else 0
        for items in (
            evidence.get("candidates"),
            evidence.get("explanations"),
            evidence.get("discipline_suggestions"),
        )
    )
    sidecar = Path(job.out_dir) / "llm-evidence.json"
    job.llm_trace_path = str(sidecar) if sidecar.exists() else ""


def _mark_llm_fallback(job: Job) -> None:
    """Record a generic optional-provider failure without exception details."""

    job.llm_status = "fallback"
    job.llm_capabilities = _llm_capabilities(job.llm_mode)
    job.llm_suggestion_count = 0
    job.llm_warning_count = 1
    job.llm_last_error_code = ERROR_HTTP_ERROR
    job.llm_trace_path = ""


async def _execute(job: Job) -> None:
    # Keep deterministic work under its own limit.  The provider phase is
    # intentionally outside this context so a slow provider cannot consume a
    # deterministic worker slot while waiting for the independent LLM limit.
    t_start = time.monotonic()
    async with semaphore:
        job.status, job.stage, job.progress = "running", "解析、定位和核对", 0.1
        job.started_at = datetime.now(timezone.utc).isoformat()
        job.save()
        try:
            trace = await asyncio.to_thread(
                run_verification,
                job.cert_path,
                job.draft_path,
                job.out_dir,
                author=settings.comment_author,
                initials=settings.comment_initials,
            )
        except Exception as exc:  # noqa: BLE001
            # Only deterministic pipeline failures enter the terminal failed
            # state; the optional LLM phase is handled below independently.
            job.status, job.stage, job.error = "failed", "失败", f"{type(exc).__name__}: {exc}"
            job.finished_at = datetime.now(timezone.utc).isoformat()
            job.timings["total"] = round(time.monotonic() - t_start, 2)
            job.save()
            return
        job.timings["deterministic"] = round(time.monotonic() - t_start, 2)

    job.trace_path = str(Path(job.out_dir) / "verification.json")
    job.diff_count = len(trace.get("result", {}).get("diffs", []))

    review_stage = "等待人工确认"
    runtime_settings = _settings_for_job(job)
    # Persist the resolved server/task mode in state before the optional phase;
    # the mode itself has already passed the server allowlist gate at creation.
    job.llm_mode = runtime_settings.mode
    if runtime_settings.enabled:
        # Status remains running while the optional provider phase executes, but
        # no deterministic semaphore is held.  The blocking orchestrator and
        # client transport are both inside asyncio.to_thread.
        job.llm_capabilities = _llm_capabilities(job.llm_mode)
        job.llm_status = "running"
        job.llm_trace_path = str(Path(job.out_dir) / "llm-evidence.json")
        job.stage = "LLM 建议处理中"
        t_llm = time.monotonic()
        try:
            job.save()
            if runtime_settings.status() == "misconfigured":
                # Do not enter the provider path with incomplete server config.
                # This is a review warning, not a deterministic job failure.
                evidence = {
                    "status": "misconfigured",
                    "capabilities": list(job.llm_capabilities),
                    "error_code": "llm_misconfigured",
                    "warnings": [{
                        "code": "llm_misconfigured",
                        "message": "LLM 配置不完整，已回退到确定性证据",
                    }],
                }
            else:
                async with provider_semaphore:
                    evidence = await asyncio.to_thread(
                        _run_llm_orchestrator,
                        trace,
                        trace_id=job.job_id,
                        verification_path=job.trace_path,
                        runtime_settings=runtime_settings,
                    )
            _apply_llm_evidence(job, evidence)
            review_stage = _llm_review_stage(evidence)
        except Exception:  # noqa: BLE001 - LLM failure must not fail the job
            # Do not copy exception text into job state: it could contain a
            # provider detail.  Deterministic evidence remains available.
            _mark_llm_fallback(job)
            review_stage = "等待人工确认（LLM 已回退）"
        finally:
            job.timings["llm"] = round(time.monotonic() - t_llm, 2)

    job.status, job.stage, job.progress = "review", review_stage, 0.7
    job.finished_at = datetime.now(timezone.utc).isoformat()
    job.timings["total"] = round(time.monotonic() - t_start, 2)
    job.save()


def _read_trace(job: Job) -> dict[str, Any]:
    if not job.trace_path or not Path(job.trace_path).exists():
        raise HTTPException(404, "核对结果尚未生成")
    try:
        return json.loads(Path(job.trace_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(500, f"核对结果读取失败：{exc}") from exc


def _diff_items(job: Job, *, limit: int = 200, offset: int = 0) -> dict[str, Any]:
    trace = _read_trace(job)
    diffs = trace.get("result", {}).get("diffs", [])
    end = min(offset + min(limit, 10000), len(diffs))
    items = []
    for diff in diffs[offset:end]:
        item = dict(diff)
        decision = job.decisions.get(diff.get("key"))
        item["review_status"] = decision.get("verdict", "unreviewed") if isinstance(decision, dict) else (decision or "unreviewed")
        item["review_note"] = decision.get("note", "") if isinstance(decision, dict) else ""
        items.append(item)
    return {"total": len(diffs), "offset": offset, "limit": limit, "items": items}


def _row_review_state(job: Job, diff_keys: list[str]) -> tuple[str, str, dict[str, Any]]:
    decisions: dict[str, Any] = {
        key: job.decisions[key] for key in diff_keys if key in job.decisions
    }
    if not diff_keys:
        return "not_required", "", decisions
    if not decisions:
        return "unreviewed", "", decisions
    verdicts: list[str] = []
    notes: list[str] = []
    for value in decisions.values():
        if isinstance(value, dict):
            verdicts.append(str(value.get("verdict", "needs_review")))
            note = str(value.get("note", ""))
        else:
            verdicts.append(str(value))
            note = ""
        if note and note not in notes:
            notes.append(note)
    status = verdicts[0] if len(decisions) == len(diff_keys) and len(set(verdicts)) == 1 else "partial"
    return status, "；".join(notes), decisions


def _row_diff_items(job: Job, *, limit: int = 200, offset: int = 0) -> dict[str, Any]:
    trace = _read_trace(job)
    row_diffs = trace.get("result", {}).get("row_diffs", [])
    end = min(offset + min(limit, 10000), len(row_diffs))
    items = []
    for raw_row in row_diffs[offset:end]:
        item = dict(raw_row)
        diff_keys = list(item.get("diff_keys", []))
        review_status, review_note, decisions = _row_review_state(job, diff_keys)
        item["review_status"] = review_status
        item["review_note"] = review_note
        item["decisions"] = decisions
        items.append(item)
    return {"total": len(row_diffs), "offset": offset, "limit": limit, "items": items}


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/jobs", status_code=202)
async def create_job(request: Request):
    # 手动解析 multipart，而不是用 ``File(...)``/``Form(...)`` 参数。原因：
    # Starlette 新版把单个 part 的默认上限 ``max_part_size`` 降到 1 MiB，正常的
    # .doc/.docx 往往就 >1 MiB（个别含内嵌对象可达上百 MB），会在进入函数体前
    # 就被解析器判成 ``There was an error parsing the body`` 并返回 400。这里把
    # 上限放开到业务允许的 ``max_upload_mb``；真正的大小上限仍由 ``_save_upload``
    # 逐块累加后以 413 兜底，二者职责不变。只解析一次 form，兼作字段名审查来源。
    max_part = settings.max_upload_mb * 1024 * 1024 + 1024 * 1024
    try:
        form = await request.form(max_part_size=max_part)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "malformed_upload",
                "message": (
                    "上传解析失败：请确认是有效的 .doc/.docx，"
                    f"且单个文件不超过 {settings.max_upload_mb} MB"
                ),
            },
        ) from exc

    # Inspect the complete multipart/query field name set before creating a job.
    # ``authorize_job_creation`` only reads names for forbidden override checks;
    # it never serializes file contents or credential values.
    submitted_fields: dict[str, Any] = {
        str(key): value for key, value in request.query_params.multi_items()
    }
    for key, value in form.multi_items():
        submitted_fields[str(key)] = value

    cert = form.get("cert")
    draft = form.get("draft")
    if not isinstance(cert, UploadFile) or not isinstance(draft, UploadFile):
        raise HTTPException(
            status_code=400,
            detail={"code": "missing_file", "message": "缺少 cert 或 draft 上传文件"},
        )

    llm_mode_raw = form.get("llm_mode")
    llm_mode = llm_mode_raw if isinstance(llm_mode_raw, str) else None
    if llm_mode is not None:
        submitted_fields["llm_mode"] = llm_mode

    try:
        mode_decision = authorize_job_creation(llm_settings, submitted_fields)
    except PolicyError as exc:
        # Return a stable classification without echoing an arbitrary request
        # value or any potential credential-looking content.
        raise HTTPException(
            status_code=400,
            detail={
                "code": exc.code,
                "message": "任务级 llm_mode 不被服务器策略允许，或请求包含禁止的策略覆盖",
            },
        ) from exc

    job = store.create()
    job.llm_mode = mode_decision.mode
    # Persist the resolved server default as well as an explicit ``off`` so a
    # restart cannot reinterpret this task under a later server default.
    job.llm_mode_explicit = True
    cert_name = Path(cert.filename or "cert.docx").name
    draft_name = Path(draft.filename or "draft.docx").name
    job.cert_name, job.draft_name = cert_name, draft_name
    job.cert_path = str(job.job_dir / f"cert{Path(cert_name).suffix.lower()}")
    job.draft_path = str(job.job_dir / f"draft{Path(draft_name).suffix.lower()}")
    job.out_dir = str(job.job_dir / "run")
    try:
        await _save_upload(cert, Path(job.cert_path))
        await _save_upload(draft, Path(job.draft_path))
    except Exception:
        shutil.rmtree(job.job_dir, ignore_errors=True)
        raise
    finally:
        # 手动解析 form 时需自行关闭上传（释放 SpooledTemporaryFile / 磁盘临时文件）。
        await cert.close()
        await draft.close()
    job.save()
    asyncio.create_task(_execute(job))
    return job.summary()


@app.get("/api/jobs")
async def list_jobs() -> list[dict[str, Any]]:
    return [job.summary() for job in store.list()]


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
    job = store.get(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    return job.summary()


@app.get("/api/jobs/{job_id}/diffs")
async def get_diffs(job_id: str, limit: int = 200, offset: int = 0) -> dict[str, Any]:
    job = store.get(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    if job.status not in {"review", "done"}:
        raise HTTPException(409, f"当前任务状态为 {job.status}")
    return _diff_items(job, limit=limit, offset=offset)


@app.get("/api/jobs/{job_id}/row-diffs")
async def get_row_diffs(job_id: str, limit: int = 200, offset: int = 0) -> dict[str, Any]:
    job = store.get(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    if job.status not in {"review", "done"}:
        raise HTTPException(409, f"当前任务状态为 {job.status}")
    return _row_diff_items(job, limit=limit, offset=offset)


@app.get("/api/jobs/{job_id}/llm-evidence")
async def get_llm_evidence(job_id: str) -> dict[str, Any]:
    """Return only the validated, redacted LLM evidence sidecar.

    ``read_evidence`` prefers the independent ``llm-evidence.json`` next to
    deterministic ``verification.json`` and validates every field before this
    response is serialized.  Its legacy fallback reads only a safe ``llm`` node,
    never the deterministic trace.  This route is read-only and never writes or
    replaces either file.
    """

    job = store.get(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    if job.status not in {"review", "done"}:
        raise HTTPException(409, f"当前任务状态为 {job.status}")
    if not job.trace_path:
        raise HTTPException(404, "LLM evidence 尚未生成")
    try:
        return read_evidence(job.trace_path)
    except EvidenceError as exc:
        # Do not expose a filesystem path, raw JSON, prompt, response or
        # validation details.  The stable code is sufficient for a controlled
        # client and mirrors the evidence module's audit classification.
        status_code = 404 if exc.code == "llm_trace_missing" else 500
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "message": "LLM evidence 不可用"},
        ) from exc


@app.post("/api/jobs/{job_id}/decisions")
async def submit_decisions(job_id: str, request: Request) -> dict[str, Any]:
    job = store.get(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    if job.status != "review":
        raise HTTPException(409, f"当前任务状态不允许确认：{job.status}")
    body = await request.json()
    if isinstance(body, dict) and "candidate_decisions" in body:
        # Candidate acceptance is not a verdict and is not implemented by this
        # route.  Reject it instead of silently persisting an AI suggestion as a
        # human decision.
        raise HTTPException(400, "AI 候选必须经过单独人工接受和确定性重核对")
    decisions = body.get("decisions", body) if isinstance(body, dict) else {}
    if not isinstance(decisions, dict):
        raise HTTPException(400, "decisions 必须是对象")
    try:
        canonical_decisions = normalize_manual_decisions(decisions)
    except ValueError as exc:
        # Do not echo a submitted note, provider payload, or arbitrary field in
        # the API error or job log.  Only the stable validation category leaves
        # this boundary.
        raise HTTPException(400, "人工 decisions 格式无效，仅允许 verdict 和 note") from exc

    trace = _read_trace(job)
    known = {
        str(item.get("key"))
        for item in trace.get("result", {}).get("diffs", [])
        if item.get("key")
    }
    unknown_request = sorted(set(canonical_decisions) - known)
    if unknown_request:
        raise HTTPException(400, f"包含未知差异 key：{unknown_request[:5]}")
    unknown_stored = sorted(set(job.decisions) - known)
    if unknown_stored:
        raise HTTPException(400, f"任务中存在未知差异 key：{unknown_stored[:5]}")
    job.decisions.update(canonical_decisions)
    job.decisions_count = len(set(job.decisions) & known)
    missing = sorted(known - set(job.decisions))
    if missing:
        job.save()
        return {
            **job.summary(),
            "confirmed": job.decisions_count,
            "total": len(known),
            "missing_keys": missing,
            "unknown_keys": [],
        }
    try:
        review = await asyncio.to_thread(
            finalize_review, trace, job.decisions,
            reviewer=request.headers.get("X-Reviewer", "web-user"),
            feedback_path=Path(job.out_dir) / "feedback.jsonl",
        )
        job.status, job.stage, job.progress = "done", "完成，可下载", 1.0
        job.save()
        return {**job.summary(), "review": review}
    except Exception as exc:  # noqa: BLE001
        job.status, job.stage, job.error = "review", "人工确认失败", str(exc)
        job.save()
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/jobs/{job_id}/result/{kind}")
async def download_result(job_id: str, kind: str):
    job = store.get(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    if job.status != "done":
        raise HTTPException(409, "全部差异尚未人工确认，暂不可下载")
    names = {
        "draft": ("批注版报告草稿_最终.docx", "批注版报告草稿_最终.docx"),
        "summary": ("差异汇总_最终.docx", "差异汇总_最终.docx"),
    }
    if kind not in names:
        raise HTTPException(404, "结果类型只能是 draft 或 summary")
    path = Path(job.out_dir) / names[kind][0]
    if not path.exists():
        raise HTTPException(404, "最终文件不存在")
    return FileResponse(path, filename=names[kind][1])


@app.get("/api/jobs/{job_id}/memory")
async def get_memory(job_id: str) -> dict[str, Any]:
    job = store.get(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    feedback_path = Path(job.out_dir) / "feedback.jsonl"
    if not feedback_path.exists() or not job.trace_path:
        return {"hints": {}}
    try:
        trace = _read_trace(job)
        diffs = [
            diff_from_dict(item)
            for item in trace.get("result", {}).get("diffs", [])
            if isinstance(item, dict)
        ]
        # Recompute from the canonical feedback log.  Do not trust a review.json
        # memory_hints node that could have been copied from LLM evidence.
        return {"hints": memory_hints(diffs, feedback_path)}
    except (OSError, TypeError, ValueError, KeyError):
        return {"hints": {}}


_FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
if _FRONTEND.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND), html=True), name="frontend")
