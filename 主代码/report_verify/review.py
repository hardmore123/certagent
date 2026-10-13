"""人工确认、反馈记忆和最终双文档生成。"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .comment_writer import write_comments
from .models import Anchor, VerifyDiff, to_dict
from .summary_writer import write_summary
from .validation import validate_outputs

ALLOWED_VERDICTS = {"accept", "ignore", "modify", "needs_review"}
HUMAN_FEEDBACK_SOURCE = "human"

# A decision is deliberately a very small human-review protocol.  In particular,
# LLM candidate/explanation/discipline objects (status, reason, source, candidate
# keys, etc.) are not accepted as decisions even when they happen to contain a
# verdict-looking value.
_DECISION_KEYS = frozenset({"verdict", "note"})
_FEEDBACK_KEYS = frozenset(
    {
        "ts",
        "source",
        "reviewer",
        "document_version",
        "key",
        "sig",
        "verdict",
        "note",
        "diff_type",
        "field",
    }
)
_FEEDBACK_SENSITIVE_RE = re.compile(
    r"(?i)(?:api[ _-]?key|user[ _-]?key|authorization|bearer|"
    r"secret|password|passwd|token|cookie|prompt|response|"
    r"cert[ _-]?value|draft[ _-]?value|original[ _-]?(?:text|document)|"
    r"private[ _-]?key)\s*[:=]"
)
_URL_RE = re.compile(r"(?i)(?:https?|file)://")
_WINDOWS_PATH_RE = re.compile(r"(?:^[A-Za-z]:[\\/])|(?:^\\\\)")


def diff_from_dict(data: dict[str, Any]) -> VerifyDiff:
    payload = dict(data)
    anchor = payload.get("draft_anchor")
    payload["draft_anchor"] = Anchor(**anchor) if isinstance(anchor, dict) else None
    return VerifyDiff(**{key: value for key, value in payload.items() if key in VerifyDiff.__dataclass_fields__})


def _safe_feedback_text(
    value: Any,
    *,
    field: str,
    max_chars: int = 1000,
    allow_empty: bool = True,
) -> str:
    """Validate text that is allowed to enter feedback/review memory.

    Feedback is an audit record, not a second document or provider trace.  It may
    contain a short human note, but it must not carry credentials, prompt/response
    material, URLs, paths, or control characters.  Rejection uses fixed messages so
    the offending value is never reflected in an exception or job log.
    """

    if not isinstance(value, str):
        raise ValueError(f"{field} 必须是字符串")
    if not allow_empty and not value:
        raise ValueError(f"{field} 不能为空")
    if len(value) > max_chars:
        raise ValueError(f"{field} 超过反馈长度上限")
    if any(ord(char) < 32 and char not in "\t\n" for char in value) or "\x7f" in value:
        raise ValueError(f"{field} 含控制字符")
    if _URL_RE.search(value) or _WINDOWS_PATH_RE.search(value):
        raise ValueError(f"{field} 不得包含 URL 或文件路径")
    if _FEEDBACK_SENSITIVE_RE.search(value):
        raise ValueError(f"{field} 含禁止记录的敏感内容")
    return value


def _safe_feedback_note(value: str, *, diff: VerifyDiff | None = None) -> str:
    """Validate a human note without copying a complete compared value."""

    note = _safe_feedback_text(value, field="人工备注", max_chars=1000)
    if diff is not None and note:
        # A note may explain a decision, but an exact long CERT/DRAFT value is
        # document content rather than a review note and must not be persisted.
        compared_values = (diff.cert_value or "", diff.draft_value or "")
        if any(len(candidate) >= 8 and note == candidate for candidate in compared_values):
            raise ValueError("人工备注不得复制 CERT/DRAFT 原文")
    return note


def _decision_payload(value: Any) -> tuple[str, str]:
    """Parse one explicitly submitted human decision.

    Legacy callers may still submit a bare verdict string.  Mapping decisions must
    contain exactly ``verdict`` and optional ``note``; this prevents an LLM
    suggestion's ``status``/``reason``/``source`` fields from being treated as a
    verdict by omission or by a permissive ``dict.get`` fallback.
    """

    if isinstance(value, str):
        raw_verdict, raw_note = value, ""
    elif isinstance(value, Mapping):
        unknown = {str(key) for key in value if str(key) not in _DECISION_KEYS}
        if unknown:
            raise ValueError("人工决策只允许 verdict 和 note 字段")
        if "verdict" not in value:
            raise ValueError("人工决策缺少 verdict")
        raw_verdict, raw_note = value["verdict"], value.get("note", "")
    else:
        raise ValueError("人工决策必须是 verdict 字符串或对象")

    if not isinstance(raw_verdict, str):
        raise ValueError("人工 verdict 必须是字符串")
    verdict = raw_verdict.strip().lower()
    if verdict not in ALLOWED_VERDICTS:
        raise ValueError(f"人工 verdict 不受支持：{verdict or '空值'}")
    if not isinstance(raw_note, str):
        raise ValueError("人工备注必须是字符串")
    return verdict, _safe_feedback_note(raw_note)


def normalize_manual_decisions(
    decisions: Mapping[str, Any],
) -> dict[str, dict[str, str]]:
    """Return canonical decisions submitted by a human review client only.

    The canonical shape is intentionally separate from LLM evidence.  It is safe to
    persist in ``job.json`` and to pass to :func:`finalize_review`; no suggestion
    object can be silently coerced into it.
    """

    if not isinstance(decisions, Mapping):
        raise ValueError("decisions 必须是对象")
    normalized: dict[str, dict[str, str]] = {}
    for key, value in decisions.items():
        if not isinstance(key, str) or not key or key != key.strip():
            raise ValueError("人工决策 key 必须是非空字符串")
        verdict, note = _decision_payload(value)
        normalized[key] = {"verdict": verdict, "note": note}
    return normalized


def load_feedback(path: str | Path) -> list[dict[str, Any]]:
    """Load only canonical human feedback, while accepting the legacy shape.

    Legacy ``feedback.jsonl`` records have no ``source`` field and are treated as
    human records for backward compatibility.  A record explicitly marked as an
    LLM/provider source, or containing an invalid/sensitive value, is ignored rather
    than becoming memory input.
    """

    file_path = Path(path)
    if not file_path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(raw, Mapping):
            continue
        source = raw.get("source")
        if source is not None and source != HUMAN_FEEDBACK_SOURCE:
            continue
        try:
            verdict, note = _decision_payload(
                {"verdict": raw.get("verdict"), "note": raw.get("note", "")}
            )
            canonical: dict[str, Any] = {
                "ts": _safe_feedback_text(raw.get("ts", ""), field="ts", max_chars=80),
                "reviewer": _safe_feedback_text(raw.get("reviewer", ""), field="reviewer", max_chars=200),
                "document_version": _safe_feedback_text(
                    raw.get("document_version", ""), field="document_version", max_chars=255
                ),
                "key": _safe_feedback_text(raw.get("key", ""), field="key", max_chars=256, allow_empty=False),
                "sig": _safe_feedback_text(raw.get("sig", ""), field="sig", max_chars=1000, allow_empty=False),
                "verdict": verdict,
                "note": note,
                "diff_type": _safe_feedback_text(raw.get("diff_type", ""), field="diff_type", max_chars=128),
                "field": _safe_feedback_text(raw.get("field", ""), field="field", max_chars=256),
            }
        except ValueError:
            # Do not expose or retain malformed record content.
            continue
        if source is not None:
            canonical["source"] = HUMAN_FEEDBACK_SOURCE
        records.append(canonical)
    return records


def record_feedback(
    diffs: list[VerifyDiff], decisions: Mapping[str, Any], path: str | Path,
    *, reviewer: str = "anonymous", document_version: str = "",
) -> None:
    """Persist only explicit human verdicts, never LLM suggestions.

    The complete input is validated before opening the file, so an invalid decision
    cannot leave a partially written feedback log.  The added ``source=human`` marker
    is ignored by legacy readers but lets the memory loader reject provider records.
    """

    if not isinstance(decisions, Mapping):
        raise ValueError("decisions 必须是对象")
    by_key = {diff.key: diff for diff in diffs}
    unknown = [key for key in decisions if key not in by_key]
    if unknown:
        raise ValueError(f"包含未知差异 key：{unknown[:5]}")

    safe_reviewer = _safe_feedback_text(reviewer, field="reviewer", max_chars=200)
    safe_document_version = _safe_feedback_text(
        document_version, field="document_version", max_chars=255
    )
    now = datetime.now(timezone.utc).isoformat()
    pending_records: list[dict[str, Any]] = []
    for key, raw_decision in decisions.items():
        if not isinstance(key, str):
            raise ValueError("人工决策 key 必须是字符串")
        diff = by_key[key]
        verdict, note = _decision_payload(raw_decision)
        note = _safe_feedback_note(note, diff=diff)
        record = {
            "ts": now,
            "source": HUMAN_FEEDBACK_SOURCE,
            "reviewer": safe_reviewer,
            "document_version": safe_document_version,
            "key": _safe_feedback_text(key, field="key", max_chars=256, allow_empty=False),
            "sig": _safe_feedback_text(
                f"{diff.block_type}|{diff.item_name}|{diff.field}|{diff.diff_type}",
                field="sig",
                max_chars=1000,
                allow_empty=False,
            ),
            "verdict": verdict,
            "note": note,
            "diff_type": _safe_feedback_text(diff.diff_type, field="diff_type", max_chars=128),
            "field": _safe_feedback_text(diff.field, field="field", max_chars=256),
        }
        pending_records.append(record)

    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("a", encoding="utf-8") as handle:
        for record in pending_records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def memory_hints(diffs: list[VerifyDiff], path: str | Path) -> dict[str, dict[str, Any]]:
    """Aggregate human confirmation history as hints only.

    LLM/provider records and invalid legacy lines are filtered by ``load_feedback``.
    These hints never modify current diffs, rules, discipline, approval state, or the
    download gate.
    """

    stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"accept": 0, "ignore": 0, "needs_review": 0, "last_note": ""}
    )
    for record in load_feedback(path):
        if record.get("source", HUMAN_FEEDBACK_SOURCE) != HUMAN_FEEDBACK_SOURCE:
            continue
        sig = record.get("sig", "")
        stat = stats[sig]
        verdict = record.get("verdict", "")
        if verdict in ("accept", "modify"):
            stat["accept"] += 1
        elif verdict == "ignore":
            stat["ignore"] += 1
        elif verdict == "needs_review":
            stat["needs_review"] += 1
        stat["last_note"] = record.get("note", "")

    hints: dict[str, dict[str, Any]] = {}
    for diff in diffs:
        sig = f"{diff.block_type}|{diff.item_name}|{diff.field}|{diff.diff_type}"
        if sig in stats:
            hints[diff.key] = {"signature": sig, **stats[sig]}
    return hints


def finalize_review(
    trace: dict[str, Any], decisions: Mapping[str, Any], *, reviewer: str = "anonymous",
    feedback_path: str | Path | None = None,
) -> dict[str, Any]:
    """提交全部人工结论后，才生成可下载的最终双文档。"""

    raw_diffs = trace.get("result", {}).get("diffs", [])
    diffs = [diff_from_dict(item) for item in raw_diffs]
    known = {diff.key for diff in diffs}
    if not isinstance(decisions, Mapping):
        raise ValueError("decisions 必须是对象")
    decision_keys = set(decisions)
    unknown = sorted(
        (str(key) for key in decision_keys if not isinstance(key, str) or key not in known),
        key=str,
    )
    if unknown:
        raise ValueError(f"包含未知差异 key：{unknown[:5]}")
    if decision_keys != known:
        missing = sorted(known - decision_keys)
        raise ValueError(f"尚有 {len(missing)} 条差异未确认，不能生成最终下载文件")

    # Canonicalize before touching any diff or writing any output.  This is the
    # trust boundary between a Web request and human feedback persistence.
    try:
        normalized = normalize_manual_decisions(decisions)
    except ValueError:
        raise

    safe_reviewer = _safe_feedback_text(reviewer, field="reviewer", max_chars=200)
    final_decisions: dict[str, dict[str, str]] = {}
    final_diffs: list[VerifyDiff] = []
    for diff in diffs:
        verdict, note = _decision_payload(normalized[diff.key])
        note = _safe_feedback_note(note, diff=diff)
        if verdict not in ALLOWED_VERDICTS or verdict == "needs_review":
            raise ValueError(f"{diff.key} 使用了不支持完成确认的决策：{verdict}")
        final_decisions[diff.key] = {"verdict": verdict, "note": note}
        diff.review_status = verdict
        diff.review_note = note
        diff.reviewed_by = safe_reviewer
        if verdict in ("accept", "modify"):
            final_diffs.append(diff)

    output_dir = Path(trace["outputs"]["annotated_draft"]).parent
    if feedback_path is None:
        feedback_path = output_dir / "feedback.jsonl"
    record_feedback(
        diffs, final_decisions, feedback_path, reviewer=safe_reviewer,
        document_version=Path(trace.get("draft_path", "")).name,
    )
    hints = memory_hints(diffs, feedback_path)
    for diff in diffs:
        if diff.key in hints:
            diff.review_note = (diff.review_note + "；" if diff.review_note else "") + "已提供历史反馈提示"

    final_annotated = output_dir / "批注版报告草稿_最终.docx"
    comment_report = write_comments(
        trace["draft_docx"], final_diffs, str(final_annotated),
        author="ReportVerify", initials="RV",
    )
    final_summary = output_dir / "差异汇总_最终.docx"
    write_summary(
        final_diffs, str(final_summary),
        cert_name=Path(trace.get("cert_path", "")).name,
        draft_name=Path(trace.get("draft_path", "")).name,
        warnings=trace.get("result", {}).get("warnings", []),
    )
    consistency = validate_outputs(final_diffs, trace["draft_docx"])
    review = {
        "status": "completed",
        "reviewer": safe_reviewer,
        "total": len(diffs),
        "accepted": len(final_diffs),
        "ignored": len(diffs) - len(final_diffs),
        "memory_hints": hints,
        "decisions": final_decisions,
        "comment_report": comment_report,
        "consistency": consistency,
        "outputs": {"annotated_draft": str(final_annotated), "summary": str(final_summary)},
    }
    (output_dir / "review.json").write_text(
        json.dumps({"review": review, "diffs": to_dict(diffs)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return review
