"""候选接受后的确定性重核对边界（任务 2.4）。

本模块只处理 ``LLMReviewCandidate`` 的**接受/重核对生命周期**，不接入
FastAPI 路由，也不写 trace/evidence 文件。候选的 ``reason`` 等 LLM 输出不会
进入本模块返回的审计结果；返回值只包含状态、规则版本和确定性重核对摘要。

不变量：

* ``candidate_key`` 必须能由候选的 CERT/DRAFT 引用重新计算；
* 只接受 ``source=llm`` 且 ``status=pending`` 的 candidate 能力候选；
* CERT 引用只从 ``VerifyResult.cert_blocks`` 查找，DRAFT 引用只从
  ``VerifyResult.draft_blocks`` 查找，且两侧必须同物理表、同分组；
* 接受后先形成 ``accepted_for_recheck`` 状态，再调用注入的确定性回调；
* 回调只收到行的深拷贝和规则副本，不能通过本 API 改写原始 ``VerifyDiff``、人工
  verdict、discipline 或下载状态；
* LLM 失败/候选过期只产生纯数据状态，不清空或重写确定性差异。

默认回调 ``same_value_recheck`` 使用 ReportVerify 当前 ``same_value`` 和规则版本
对候选两行逐字段重核对。上层也可以注入现有确定性对齐入口的适配器；适配器的
返回值会被压缩为安全的 ``DeterministicRecheckSummary``，不会把 prompt、response
或秘密带入返回结果。
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

from ..models import DocumentRow, VerifyResult
from ..rules import load_rules, same_value
from ..verify_differ import CHANGE_FIELDS, LIST_FIELDS
from .orchestrator import LLMReviewCandidate

# Candidate lifecycle states.  The returned outcome represents the state after the
# requested transition; ``accepted_for_recheck`` is deliberately not a final verdict.
CANDIDATE_STATUS_PENDING = "pending"
CANDIDATE_STATUS_ACCEPTED_FOR_RECHECK = "accepted_for_recheck"
CANDIDATE_STATUS_REJECTED = "rejected"
CANDIDATE_STATUS_EXPIRED = "expired"

# Short aliases are useful to callers that use the status-oriented naming from the
# design document.
STATUS_PENDING = CANDIDATE_STATUS_PENDING
STATUS_ACCEPTED_FOR_RECHECK = CANDIDATE_STATUS_ACCEPTED_FOR_RECHECK
STATUS_REJECTED = CANDIDATE_STATUS_REJECTED
STATUS_EXPIRED = CANDIDATE_STATUS_EXPIRED

CANDIDATE_SOURCE_LLM = "llm"
CANDIDATE_CAPABILITY = "candidate"

RECHECK_STATUS_NOT_REQUESTED = "not_requested"
RECHECK_STATUS_SUCCESS = "success"
RECHECK_STATUS_FAILED = "failed"

ERROR_CANDIDATE_UNKNOWN = "candidate_unknown"
ERROR_CANDIDATE_AMBIGUOUS = "candidate_ambiguous"
ERROR_CANDIDATE_KEY_INVALID = "candidate_key_invalid"
ERROR_CANDIDATE_KEY_MISMATCH = "candidate_key_mismatch"
ERROR_CANDIDATE_SOURCE_INVALID = "candidate_source_invalid"
ERROR_CANDIDATE_STATUS_INVALID = "candidate_status_invalid"
ERROR_CANDIDATE_CAPABILITY_INVALID = "candidate_capability_invalid"
ERROR_CANDIDATE_REFERENCE_INVALID = "candidate_reference_invalid"
ERROR_CANDIDATE_REFERENCE_AMBIGUOUS = "candidate_reference_ambiguous"
ERROR_CANDIDATE_EXPIRED = "candidate_expired"
ERROR_CANDIDATE_DIRECTION_INVALID = "candidate_direction_invalid"
ERROR_CANDIDATE_TABLE_MISMATCH = "candidate_table_mismatch"
ERROR_CANDIDATE_GROUP_MISMATCH = "candidate_group_mismatch"
ERROR_RECHECK_CALLBACK_FAILED = "recheck_callback_failed"
ERROR_RECHECK_RESULT_INVALID = "recheck_result_invalid"
ERROR_RECHECK_RULE_VERSION_MISMATCH = "recheck_rule_version_mismatch"

# The recheck callback is intentionally a one-argument callback.  This keeps the
# boundary explicit: it receives a request containing row copies, never VerifyResult.
RecheckCallback = Callable[["DeterministicRecheckRequest"], Any]
CandidateLike = LLMReviewCandidate | Mapping[str, Any]


@dataclass(frozen=True)
class DeterministicRecheckRequest:
    """Input supplied to a deterministic recheck adapter.

    ``cert_row`` and ``draft_row`` are deep copies.  A callback may run the existing
    alignment/``same_value`` logic over them, but it cannot mutate the caller's
    ``VerifyResult`` through this request.  ``candidate`` intentionally contains only
    non-LLM metadata; the original LLM reason is not forwarded to the callback API.
    """

    candidate_key: str
    candidate: Mapping[str, Any]
    cert_row: DocumentRow
    draft_row: DocumentRow
    rules: Mapping[str, Any]
    rule_version: str


@dataclass(frozen=True)
class DeterministicRecheckSummary:
    """Auditable, bounded summary returned by a deterministic recheck."""

    status: str
    rule_version: str
    same_value: bool | None = None
    changed_fields: tuple[str, ...] = ()
    diff_count: int = 0
    error_code: str = ""

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status,
            "rule_version": self.rule_version,
            "same_value": self.same_value,
            "changed_fields": list(self.changed_fields),
            "diff_count": self.diff_count,
        }
        if self.error_code:
            result["error_code"] = self.error_code
        return result


@dataclass(frozen=True)
class CandidateRecheckOutcome:
    """Pure-data result of candidate validation, acceptance, and recheck.

    ``status`` is the resulting candidate lifecycle state.  For a valid candidate with
    a successful deterministic callback it is ``accepted_for_recheck``; this is never a
    final verdict.  If the callback fails, ``status`` is ``rejected`` and
    ``recheck_result.status`` is ``failed``.  ``acceptance_status`` records the explicit
    intermediate state reached before that callback, making the failure transition
    auditable without inventing another candidate state.
    """

    candidate_key: str
    status: str
    recheck_requested: bool
    recheck_result: Mapping[str, Any]
    rule_version: str = ""
    acceptance_status: str = ""
    error_code: str = ""
    reason: str = ""
    source: str = CANDIDATE_SOURCE_LLM
    # Explicit compatibility flags: this module never performs any of these writes.
    diffs_unchanged: bool = True
    verdict_unchanged: bool = True
    discipline_unchanged: bool = True
    manual_confirmation_required: bool = True
    download_ready: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_key": self.candidate_key,
            "status": self.status,
            "acceptance_status": self.acceptance_status,
            "recheck_requested": self.recheck_requested,
            "recheck_result": dict(self.recheck_result),
            "rule_version": self.rule_version,
            "error_code": self.error_code,
            "reason": self.reason,
            "source": self.source,
            "diffs_unchanged": self.diffs_unchanged,
            "verdict_unchanged": self.verdict_unchanged,
            "discipline_unchanged": self.discipline_unchanged,
            "manual_confirmation_required": self.manual_confirmation_required,
            "download_ready": self.download_ready,
        }


# ---------------------------------------------------------------------------
# Stable candidate/reference handling
# ---------------------------------------------------------------------------


def candidate_key_for_refs(
    cert_ref: Mapping[str, Any], draft_ref: Mapping[str, Any]
) -> str:
    """Return the same stable key format used by the candidate orchestrator.

    The implementation is kept local so the acceptance boundary does not need to call
    an LLM or mutate the orchestrator.  Only stable CERT/DRAFT references participate;
    no row value, reason, prompt, response, or secret is hashed.
    """

    source = json.dumps(
        {"cert": dict(cert_ref), "draft": dict(draft_ref)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"cand-{hashlib.sha1(source.encode('utf-8')).hexdigest()[:16]}"


def _candidate_dict(candidate: CandidateLike) -> dict[str, Any] | None:
    if isinstance(candidate, LLMReviewCandidate):
        return candidate.to_dict()
    if isinstance(candidate, Mapping):
        return {str(key): copy.deepcopy(value) for key, value in candidate.items()}
    return None


def _candidate_values(
    candidates: Iterable[CandidateLike] | Mapping[str, CandidateLike] | CandidateLike,
) -> list[CandidateLike]:
    # Accept a keyed registry as well as a plain sequence.  A single candidate mapping
    # is distinguished by its required candidate_key field.
    if isinstance(candidates, LLMReviewCandidate):
        return [candidates]
    if isinstance(candidates, Mapping):
        if "candidate_key" in candidates:
            return [candidates]
        return list(candidates.values())
    if isinstance(candidates, (str, bytes)):
        return []
    try:
        return list(candidates)
    except TypeError:
        return []


def _normalise_group(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold().strip()


def _ref_tuple(value: Any) -> tuple[str, int, int] | None:
    if not isinstance(value, Mapping):
        return None
    block_type = value.get("block_type")
    table_idx = value.get("table_idx")
    row_idx = value.get("row_idx")
    if not isinstance(block_type, str) or not block_type.strip():
        return None
    # bool is an int subclass but is not a valid document position.
    if isinstance(table_idx, bool) or not isinstance(table_idx, int):
        return None
    if isinstance(row_idx, bool) or not isinstance(row_idx, int):
        return None
    return block_type, table_idx, row_idx


def _row_ref(row: DocumentRow) -> tuple[str, int, int]:
    return row.block_type, row.source_table, row.row_idx


def _row_index(blocks: Sequence[Any]) -> tuple[dict[tuple[str, int, int], DocumentRow], set[tuple[str, int, int]]]:
    index: dict[tuple[str, int, int], DocumentRow] = {}
    duplicates: set[tuple[str, int, int]] = set()
    for block in blocks or ():
        for row in getattr(block, "rows", ()) or ():
            token = _row_ref(row)
            if token in index:
                duplicates.add(token)
            else:
                index[token] = row
    return index, duplicates


def _rule_context(
    result: VerifyResult, rules: Mapping[str, Any] | None
) -> tuple[dict[str, Any], str]:
    if rules is None:
        resolved = dict(load_rules())
    else:
        resolved = {str(key): copy.deepcopy(value) for key, value in rules.items()}
    result_version = str(getattr(result, "rule_version", "") or "")
    rule_version = str(resolved.get("version") or result_version or "normalized-v2")
    resolved.setdefault("version", rule_version)
    return resolved, rule_version


def _not_requested_result() -> dict[str, Any]:
    return {
        "status": RECHECK_STATUS_NOT_REQUESTED,
        "same_value": None,
        "changed_fields": [],
        "diff_count": 0,
    }


def _outcome(
    *,
    candidate_key: str,
    status: str,
    rule_version: str,
    recheck_requested: bool,
    recheck_result: Mapping[str, Any] | None = None,
    acceptance_status: str = "",
    error_code: str = "",
    reason: str = "",
) -> CandidateRecheckOutcome:
    return CandidateRecheckOutcome(
        candidate_key=candidate_key,
        status=status,
        acceptance_status=acceptance_status,
        recheck_requested=recheck_requested,
        recheck_result=dict(recheck_result or _not_requested_result()),
        rule_version=rule_version,
        error_code=error_code,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Deterministic recheck implementation and callback result sanitisation
# ---------------------------------------------------------------------------


def _fields_for_recheck(cert_row: DocumentRow, draft_row: DocumentRow) -> tuple[str, ...]:
    block_type = cert_row.block_type or draft_row.block_type
    if block_type in {"safety_list", "emc_list"}:
        fields = tuple(LIST_FIELDS)
    elif block_type == "change_confirmation":
        fields = tuple(CHANGE_FIELDS)
    elif block_type == "product_description":
        fields = ("值",)
    else:
        fields = tuple(
            sorted(
                {
                    str(field_name)
                    for field_name in set(cert_row.values) | set(draft_row.values)
                    if not str(field_name).endswith("__2")
                }
            )
        )
    return fields


def same_value_recheck(
    request: DeterministicRecheckRequest,
) -> DeterministicRecheckSummary:
    """Run the local deterministic field comparison for one accepted pair.

    This is the safe default callback.  It reports whether each deterministic field is
    equal under ``same_value`` and never creates or mutates a ``VerifyDiff``.
    """

    changed_fields: list[str] = []
    for field_name in _fields_for_recheck(request.cert_row, request.draft_row):
        cert_value = request.cert_row.values.get(field_name, "") or ""
        draft_value = request.draft_row.values.get(field_name, "") or ""
        if not same_value(cert_value, draft_value, dict(request.rules)):
            changed_fields.append(field_name)
    return DeterministicRecheckSummary(
        status=RECHECK_STATUS_SUCCESS,
        rule_version=request.rule_version,
        same_value=not changed_fields,
        changed_fields=tuple(changed_fields),
        diff_count=len(changed_fields),
    )


def _safe_field_names(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return ()
    fields: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        # Field names are deterministic metadata, not free-form provider output.
        clean = item.strip()
        if clean and len(clean) <= 200 and clean not in fields:
            fields.append(clean)
        if len(fields) >= 100:
            break
    return tuple(fields)


def _safe_error_code(value: Any, default: str) -> str:
    if not isinstance(value, str):
        return default
    clean = value.strip().lower()
    if not clean or len(clean) > 80 or not re.fullmatch(r"[a-z0-9_.-]+", clean):
        return default
    return clean


def _summary_from_mapping(
    value: Mapping[str, Any],
    *,
    rule_version: str,
) -> DeterministicRecheckSummary:
    nested = value.get("summary")
    payload = nested if isinstance(nested, Mapping) else value
    raw_status = payload.get("status", value.get("status", ""))
    if not isinstance(raw_status, str):
        raw_status = ""
    status = raw_status.strip().lower()
    if status in {"ok", "passed", "pass", "rechecked", "success"}:
        normalized_status = RECHECK_STATUS_SUCCESS
    elif status in {"failed", "failure", "error", "fallback", "rejected"}:
        normalized_status = RECHECK_STATUS_FAILED
    elif value.get("ok") is True:
        normalized_status = RECHECK_STATUS_SUCCESS
    elif value.get("ok") is False:
        normalized_status = RECHECK_STATUS_FAILED
    else:
        normalized_status = RECHECK_STATUS_FAILED

    reported_version = payload.get("rule_version", value.get("rule_version"))
    if reported_version is not None and str(reported_version) != rule_version:
        return DeterministicRecheckSummary(
            status=RECHECK_STATUS_FAILED,
            rule_version=rule_version,
            error_code=ERROR_RECHECK_RULE_VERSION_MISMATCH,
        )

    same = payload.get("same_value", value.get("same_value"))
    same_value_result = same if isinstance(same, bool) else None
    raw_count = payload.get("diff_count", value.get("diff_count", 0))
    diff_count = raw_count if isinstance(raw_count, int) and not isinstance(raw_count, bool) and raw_count >= 0 else 0
    error_code = ""
    if normalized_status == RECHECK_STATUS_FAILED:
        error_code = _safe_error_code(
            payload.get("error_code", value.get("error_code")),
            ERROR_RECHECK_RESULT_INVALID,
        )
    return DeterministicRecheckSummary(
        status=normalized_status,
        rule_version=rule_version,
        same_value=same_value_result,
        changed_fields=_safe_field_names(payload.get("changed_fields", value.get("changed_fields", []))),
        diff_count=min(diff_count, 10000),
        error_code=error_code,
    )


def _normalise_recheck_result(
    value: Any,
    *,
    rule_version: str,
) -> DeterministicRecheckSummary:
    if isinstance(value, DeterministicRecheckSummary):
        if value.rule_version and value.rule_version != rule_version:
            return DeterministicRecheckSummary(
                status=RECHECK_STATUS_FAILED,
                rule_version=rule_version,
                error_code=ERROR_RECHECK_RULE_VERSION_MISMATCH,
            )
        if value.status not in {RECHECK_STATUS_SUCCESS, RECHECK_STATUS_FAILED}:
            return DeterministicRecheckSummary(
                status=RECHECK_STATUS_FAILED,
                rule_version=rule_version,
                error_code=ERROR_RECHECK_RESULT_INVALID,
            )
        return DeterministicRecheckSummary(
            status=value.status,
            rule_version=rule_version,
            same_value=value.same_value if isinstance(value.same_value, bool) else None,
            changed_fields=_safe_field_names(value.changed_fields),
            diff_count=min(max(value.diff_count, 0), 10000),
            error_code=(
                _safe_error_code(value.error_code, ERROR_RECHECK_RESULT_INVALID)
                if value.status == RECHECK_STATUS_FAILED
                else ""
            ),
        )
    if isinstance(value, bool):
        return DeterministicRecheckSummary(
            status=RECHECK_STATUS_SUCCESS,
            rule_version=rule_version,
            same_value=value,
            changed_fields=(),
            diff_count=0,
        )
    if isinstance(value, Mapping):
        return _summary_from_mapping(value, rule_version=rule_version)
    return DeterministicRecheckSummary(
        status=RECHECK_STATUS_FAILED,
        rule_version=rule_version,
        error_code=ERROR_RECHECK_RESULT_INVALID,
    )


# ---------------------------------------------------------------------------
# Public acceptance flow
# ---------------------------------------------------------------------------


def accept_candidate_for_recheck(
    candidate_key: str,
    candidates: Iterable[CandidateLike] | Mapping[str, CandidateLike] | CandidateLike,
    result: VerifyResult,
    *,
    recheck_callback: RecheckCallback | None = None,
    rules: Mapping[str, Any] | None = None,
) -> CandidateRecheckOutcome:
    """Accept one pending LLM candidate and run deterministic recheck.

    Parameters
    ----------
    candidate_key:
        Caller-selected key.  It must identify exactly one candidate and match the
        stable key recomputed from that candidate's CERT/DRAFT refs.
    candidates:
        The pending candidate collection (or one candidate).  A keyed mapping is also
        accepted for in-memory stores; no persistence is performed here.
    result:
        The existing deterministic result.  It is read only.  The callback receives
        only copied rows, never this object.
    recheck_callback:
        One-argument deterministic adapter.  If omitted, ``same_value_recheck`` is
        used.  A callback failure returns ``status=rejected`` with an explicit nested
        ``recheck_result.status=failed``; it never turns into a final verdict.
    rules:
        Optional already-loaded deterministic rules.  When omitted, the current local
        version is loaded through ``load_rules``.
    """

    _, rule_version = _rule_context(result, rules)
    requested_key = candidate_key if isinstance(candidate_key, str) else ""
    if not requested_key:
        return _outcome(
            candidate_key=requested_key,
            status=CANDIDATE_STATUS_REJECTED,
            rule_version=rule_version,
            recheck_requested=False,
            error_code=ERROR_CANDIDATE_KEY_INVALID,
            reason="candidate_key 为空或类型无效",
        )

    matches: list[dict[str, Any]] = []
    for candidate in _candidate_values(candidates):
        payload = _candidate_dict(candidate)
        if payload is not None and payload.get("candidate_key") == requested_key:
            matches.append(payload)
    if not matches:
        return _outcome(
            candidate_key=requested_key,
            status=CANDIDATE_STATUS_REJECTED,
            rule_version=rule_version,
            recheck_requested=False,
            error_code=ERROR_CANDIDATE_UNKNOWN,
            reason="候选 key 不存在",
        )
    if len(matches) != 1:
        return _outcome(
            candidate_key=requested_key,
            status=CANDIDATE_STATUS_REJECTED,
            rule_version=rule_version,
            recheck_requested=False,
            error_code=ERROR_CANDIDATE_AMBIGUOUS,
            reason="候选 key 对应多个候选",
        )

    candidate = matches[0]
    cert_ref = candidate.get("cert_ref")
    draft_ref = candidate.get("draft_ref")
    try:
        expected_key = candidate_key_for_refs(cert_ref, draft_ref)
    except (TypeError, ValueError):
        expected_key = ""
    if expected_key != requested_key:
        return _outcome(
            candidate_key=requested_key,
            status=CANDIDATE_STATUS_REJECTED,
            rule_version=rule_version,
            recheck_requested=False,
            error_code=ERROR_CANDIDATE_KEY_MISMATCH,
            reason="candidate_key 与 CERT/DRAFT 引用不匹配",
        )
    if candidate.get("source") != CANDIDATE_SOURCE_LLM:
        return _outcome(
            candidate_key=requested_key,
            status=CANDIDATE_STATUS_REJECTED,
            rule_version=rule_version,
            recheck_requested=False,
            error_code=ERROR_CANDIDATE_SOURCE_INVALID,
            reason="候选来源不是 llm",
        )
    if candidate.get("capability") not in {None, CANDIDATE_CAPABILITY}:
        return _outcome(
            candidate_key=requested_key,
            status=CANDIDATE_STATUS_REJECTED,
            rule_version=rule_version,
            recheck_requested=False,
            error_code=ERROR_CANDIDATE_CAPABILITY_INVALID,
            reason="候选能力不是 candidate",
        )
    if candidate.get("status") != CANDIDATE_STATUS_PENDING:
        return _outcome(
            candidate_key=requested_key,
            status=CANDIDATE_STATUS_REJECTED,
            rule_version=rule_version,
            recheck_requested=False,
            error_code=ERROR_CANDIDATE_STATUS_INVALID,
            reason="候选不是 pending 状态",
        )

    cert_token = _ref_tuple(cert_ref)
    draft_token = _ref_tuple(draft_ref)
    if cert_token is None or draft_token is None:
        return _outcome(
            candidate_key=requested_key,
            status=CANDIDATE_STATUS_REJECTED,
            rule_version=rule_version,
            recheck_requested=False,
            error_code=ERROR_CANDIDATE_REFERENCE_INVALID,
            reason="CERT/DRAFT 引用格式无效",
        )
    if cert_token[0] != draft_token[0]:
        return _outcome(
            candidate_key=requested_key,
            status=CANDIDATE_STATUS_REJECTED,
            rule_version=rule_version,
            recheck_requested=False,
            error_code=ERROR_CANDIDATE_DIRECTION_INVALID,
            reason="CERT/DRAFT 方向或子块不一致",
        )
    if cert_token[1] != draft_token[1]:
        return _outcome(
            candidate_key=requested_key,
            status=CANDIDATE_STATUS_REJECTED,
            rule_version=rule_version,
            recheck_requested=False,
            error_code=ERROR_CANDIDATE_TABLE_MISMATCH,
            reason="CERT/DRAFT 不在同一物理表",
        )

    cert_index, cert_duplicates = _row_index(getattr(result, "cert_blocks", ()))
    draft_index, draft_duplicates = _row_index(getattr(result, "draft_blocks", ()))
    if cert_token in cert_duplicates or draft_token in draft_duplicates:
        return _outcome(
            candidate_key=requested_key,
            status=CANDIDATE_STATUS_REJECTED,
            rule_version=rule_version,
            recheck_requested=False,
            error_code=ERROR_CANDIDATE_REFERENCE_AMBIGUOUS,
            reason="CERT/DRAFT 引用无法唯一定位",
        )
    cert_row = cert_index.get(cert_token)
    draft_row = draft_index.get(draft_token)
    # A swapped candidate is not merely stale when each reference is present on the
    # opposite side.  Reject it explicitly as a CERT -> DRAFT direction violation.
    swapped_direction = (
        (cert_row is None and cert_token in draft_index)
        or (draft_row is None and draft_token in cert_index)
    )
    if swapped_direction:
        return _outcome(
            candidate_key=requested_key,
            status=CANDIDATE_STATUS_REJECTED,
            rule_version=rule_version,
            recheck_requested=False,
            error_code=ERROR_CANDIDATE_DIRECTION_INVALID,
            reason="CERT/DRAFT 引用方向颠倒",
        )
    if cert_row is None or draft_row is None:
        # A previously generated candidate whose row disappeared is stale, not an
        # operator rejection.  It must not be rechecked against a different row.
        return _outcome(
            candidate_key=requested_key,
            status=CANDIDATE_STATUS_EXPIRED,
            rule_version=rule_version,
            recheck_requested=False,
            error_code=ERROR_CANDIDATE_EXPIRED,
            reason="候选引用的 CERT/DRAFT 行已不存在",
        )
    if _row_ref(cert_row) != cert_token or _row_ref(draft_row) != draft_token:
        return _outcome(
            candidate_key=requested_key,
            status=CANDIDATE_STATUS_EXPIRED,
            rule_version=rule_version,
            recheck_requested=False,
            error_code=ERROR_CANDIDATE_EXPIRED,
            reason="候选引用已无法精确定位原始行",
        )
    if _normalise_group(cert_row.group) != _normalise_group(draft_row.group):
        return _outcome(
            candidate_key=requested_key,
            status=CANDIDATE_STATUS_REJECTED,
            rule_version=rule_version,
            recheck_requested=False,
            error_code=ERROR_CANDIDATE_GROUP_MISMATCH,
            reason="CERT/DRAFT 不在同一分组",
        )

    # This is the explicit intermediate state.  The returned result never mutates the
    # frozen LLMReviewCandidate or a candidate registry; the caller can persist this
    # pure-data transition in a later Web task if/when that phase is implemented.
    acceptance_status = CANDIDATE_STATUS_ACCEPTED_FOR_RECHECK
    request_candidate = {
        "candidate_key": requested_key,
        "capability": CANDIDATE_CAPABILITY,
        "source": CANDIDATE_SOURCE_LLM,
        "status": acceptance_status,
        "confidence": candidate.get("confidence"),
        "cert_ref": dict(cert_ref),
        "draft_ref": dict(draft_ref),
    }
    resolved_rules, _ = _rule_context(result, rules)
    request = DeterministicRecheckRequest(
        candidate_key=requested_key,
        candidate=request_candidate,
        cert_row=copy.deepcopy(cert_row),
        draft_row=copy.deepcopy(draft_row),
        rules=copy.deepcopy(resolved_rules),
        rule_version=rule_version,
    )
    callback = recheck_callback or same_value_recheck
    try:
        callback_value = callback(request)
        summary = _normalise_recheck_result(callback_value, rule_version=rule_version)
    except Exception:  # noqa: BLE001 - never expose callback details to audit output
        summary = DeterministicRecheckSummary(
            status=RECHECK_STATUS_FAILED,
            rule_version=rule_version,
            error_code=ERROR_RECHECK_CALLBACK_FAILED,
        )

    summary_dict = summary.to_dict()
    if summary.status != RECHECK_STATUS_SUCCESS:
        return _outcome(
            candidate_key=requested_key,
            status=CANDIDATE_STATUS_REJECTED,
            acceptance_status=acceptance_status,
            rule_version=rule_version,
            recheck_requested=True,
            recheck_result=summary_dict,
            error_code=summary.error_code or ERROR_RECHECK_CALLBACK_FAILED,
            reason="确定性重核对失败，保留原始差异并要求人工确认",
        )
    return _outcome(
        candidate_key=requested_key,
        status=acceptance_status,
        acceptance_status=acceptance_status,
        rule_version=rule_version,
        recheck_requested=True,
        recheck_result=summary_dict,
        reason="已完成确定性重核对；仍需现有 /decisions 全量人工确认",
    )


def accept_candidate(
    candidate: CandidateLike,
    result: VerifyResult,
    *,
    candidates: Iterable[CandidateLike] | Mapping[str, CandidateLike] | None = None,
    recheck_callback: RecheckCallback | None = None,
    rules: Mapping[str, Any] | None = None,
) -> CandidateRecheckOutcome:
    """Convenience wrapper accepting one candidate object directly."""

    payload = _candidate_dict(candidate)
    key = payload.get("candidate_key", "") if payload else ""
    registry: Any = candidates if candidates is not None else [candidate]
    return accept_candidate_for_recheck(
        key,
        registry,
        result,
        recheck_callback=recheck_callback,
        rules=rules,
    )


# Descriptive alias for callers that prefer the operation name used in the design.
recheck_accepted_candidate = accept_candidate_for_recheck


__all__ = [
    "CANDIDATE_STATUS_PENDING",
    "CANDIDATE_STATUS_ACCEPTED_FOR_RECHECK",
    "CANDIDATE_STATUS_REJECTED",
    "CANDIDATE_STATUS_EXPIRED",
    "STATUS_PENDING",
    "STATUS_ACCEPTED_FOR_RECHECK",
    "STATUS_REJECTED",
    "STATUS_EXPIRED",
    "CANDIDATE_SOURCE_LLM",
    "CANDIDATE_CAPABILITY",
    "RECHECK_STATUS_NOT_REQUESTED",
    "RECHECK_STATUS_SUCCESS",
    "RECHECK_STATUS_FAILED",
    "ERROR_CANDIDATE_UNKNOWN",
    "ERROR_CANDIDATE_AMBIGUOUS",
    "ERROR_CANDIDATE_KEY_INVALID",
    "ERROR_CANDIDATE_KEY_MISMATCH",
    "ERROR_CANDIDATE_SOURCE_INVALID",
    "ERROR_CANDIDATE_STATUS_INVALID",
    "ERROR_CANDIDATE_CAPABILITY_INVALID",
    "ERROR_CANDIDATE_REFERENCE_INVALID",
    "ERROR_CANDIDATE_REFERENCE_AMBIGUOUS",
    "ERROR_CANDIDATE_EXPIRED",
    "ERROR_CANDIDATE_DIRECTION_INVALID",
    "ERROR_CANDIDATE_TABLE_MISMATCH",
    "ERROR_CANDIDATE_GROUP_MISMATCH",
    "ERROR_RECHECK_CALLBACK_FAILED",
    "ERROR_RECHECK_RESULT_INVALID",
    "ERROR_RECHECK_RULE_VERSION_MISMATCH",
    "DeterministicRecheckRequest",
    "DeterministicRecheckSummary",
    "CandidateRecheckOutcome",
    "candidate_key_for_refs",
    "same_value_recheck",
    "accept_candidate_for_recheck",
    "accept_candidate",
    "recheck_accepted_candidate",
]
