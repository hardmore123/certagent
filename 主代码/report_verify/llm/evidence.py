"""脱敏的 ReportVerify LLM 附属 evidence/trace。

本模块是 LLM 建议的独立证据边界。它只保存已经经过本地 Schema/策略校验的
状态、建议和调用摘要，不参与确定性核对，也不修改 ``verification.json``。

设计约束：

* ``llm-evidence.json`` 是独立 sidecar；旧 ``verification.json`` 只读 ``llm``
  节点（如果存在），不会把确定性 trace 读回或复制到 evidence；
* evidence 使用显式字段白名单，递归发现 secret、正文、文件/图片/工具等字段
  时拒绝写入；读取旧文件时同样重新校验并只返回 canonical 的脱敏 evidence；
* 文件写入先在同目录临时文件中 UTF-8 编码、flush/fsync，再 ``os.replace``，
  因此原有 evidence 在写入失败时保持不变；
* 此模块不导入 FastAPI，也不在 ``report_verify.llm.__init__`` 中注册，避免与
  其它阶段并行修改同一文件。

调用方可以把 2.1--2.3 的 ``to_dict()`` 结果传给 :func:`build_evidence`，再把
返回的 :class:`LLMEvidence` 交给 :func:`write_evidence`。直接写入时也可以传
canonical mapping；所有输入仍会经过同一套校验。
"""
from __future__ import annotations

import json
import math
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# ---------------------------------------------------------------------------
# Public constants and errors
# ---------------------------------------------------------------------------

EVIDENCE_FILENAME = "llm-evidence.json"
EVIDENCE_VERSION = "reportverify-llm-evidence-v1"

ERROR_EVIDENCE_INVALID = "llm_trace_redaction_failed"
ERROR_EVIDENCE_PATH = "llm_trace_path_invalid"
ERROR_EVIDENCE_READ = "llm_trace_read_failed"
ERROR_EVIDENCE_WRITE = "llm_trace_write_failed"
ERROR_EVIDENCE_MISSING = "llm_trace_missing"

_ALLOWED_MODES = frozenset({"off", "candidate", "explain", "candidate_explain"})
_ALLOWED_CAPABILITIES = frozenset({"candidate", "explain", "discipline"})
_ALLOWED_TRANSPORTS = frozenset({"", "sse", "json"})
_ALLOWED_CANDIDATE_STATUSES = frozenset(
    {"pending", "accepted_for_recheck", "rejected", "expired"}
)

# These names are checked recursively before the per-object whitelist.  The
# sha256 fields are deliberately not listed: their exact names are allowed by
# the call-summary whitelist and their values are separately validated as
# one-way hashes.
_FORBIDDEN_KEY_TOKENS = frozenset(
    {
        "apikey",
        "userkey",
        "authorization",
        "authheader",
        "bearer",
        "secret",
        "password",
        "passwd",
        "credential",
        "token",
        "cookie",
        "prompt",
        "response",
        "rawresponse",
        "responsetext",
        "completion",
        "content",
        "certvalue",
        "draftvalue",
        "certtext",
        "drafttext",
        "originaltext",
        "originaldocument",
        "originalbody",
        "filepath",
        "path",
        "paths",
        "file",
        "files",
        "document",
        "docx",
        "binary",
        "bytes",
        "blob",
        "attachment",
        "attachments",
        "image",
        "images",
        "imageurl",
        "imageurls",
        "photo",
        "picture",
        "embeddedobject",
        "embed",
        "embedding",
        "tool",
        "tools",
        "toolcall",
        "toolcalls",
        "functioncall",
        "url",
        "urls",
        "urlquery",
        "querystring",
        "privatekey",
        "encryptionkey",
        "ciphertext",
        "plaintext",
        "reversiblekey",
    }
)

# Explicitly permitted safe keys whose token contains a forbidden-looking
# word, or which carry a controlled value rather than raw content.
_SAFE_KEY_NAMES = frozenset(
    {
        "request_sha256",
        "response_sha256",
        "provider_host",
        "candidate_key",
        "cert_ref",
        "draft_ref",
        "cert_index",
        "draft_index",
        "candidate_discipline",
        "error_code",
        "error_codes",
        "evidence_version",
        "schema_version",
        "policy_version",
        "rule_version",
    }
)

_TOP_LEVEL_KEYS = frozenset(
    {
        "evidence_version",
        "mode",
        "status",
        "capabilities",
        "candidates",
        "explanations",
        "discipline_suggestions",
        "calls",
        "warnings",
        "error_code",
        "error_codes",
        "policy_version",
        "schema_version",
        "rule_version",
        "trace_id",
        "job_id",
    }
)
_TOP_LEVEL_ALIASES = frozenset(
    {
        "call_summaries",
        "candidate_suggestions",
        "explanation_suggestions",
        "discipline",
        "warning",
    }
)
_CALL_KEYS = frozenset(
    {
        "provider_host",
        "model",
        "schema_version",
        "attempts",
        "elapsed_ms",
        "elapsed",
        "transport",
        "status",
        "request_sha256",
        "response_sha256",
        "fallback_reason",
        "error_code",
    }
)
_CANDIDATE_KEYS = frozenset(
    {
        "candidate_key",
        "capability",
        "cert_ref",
        "draft_ref",
        "confidence",
        "reason",
        "status",
        "source",
        "policy_version",
        "schema_version",
    }
)
_REF_KEYS = frozenset({"block_type", "table_idx", "row_idx", "group", "item_name"})
_EXPLANATION_KEYS = frozenset(
    {"diff_key", "explanation", "risk", "source", "status", "schema_version"}
)
_DISCIPLINE_KEYS = frozenset(
    {
        "diff_key",
        "candidate_discipline",
        "discipline",
        "reason",
        "confidence",
        "source",
        "status",
        "rule_version",
        "schema_version",
    }
)
_WARNING_KEYS = frozenset({"code", "error_code", "message"})

_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_URL_RE = re.compile(r"(?i)(?:https?|file)://")
_WINDOWS_PATH_RE = re.compile(r"(?:^[A-Za-z]:[\\/])|(?:^\\\\)")
_SECRET_VALUE_RE = re.compile(
    r"(?i)(?:api[ _-]?key|user[ _-]?key|authorization|bearer|"
    r"private[ _-]?key|prompt|raw[ _-]?response|cert[ _-]?value|"
    r"draft[ _-]?value|original[ _-]?(?:text|document))\s*[:=]"
)


class EvidenceError(Exception):
    """Evidence 操作失败；``code`` 是稳定的、可写入 warning 的错误码。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class EvidenceValidationError(EvidenceError):
    """输入包含未授权字段、原文或不可审计值。"""

    def __init__(self, message: str) -> None:
        super().__init__(ERROR_EVIDENCE_INVALID, message)


class EvidencePathError(EvidenceError):
    """目标路径不是安全的本地 evidence 路径。"""

    def __init__(self, message: str) -> None:
        super().__init__(ERROR_EVIDENCE_PATH, message)


class EvidenceReadError(EvidenceError):
    """读取或 JSON 解码失败。"""

    def __init__(self, message: str, *, missing: bool = False) -> None:
        super().__init__(ERROR_EVIDENCE_MISSING if missing else ERROR_EVIDENCE_READ, message)


class EvidenceWriteError(EvidenceError):
    """原子写入失败；既有目标文件应保持不变。"""

    def __init__(self, message: str) -> None:
        super().__init__(ERROR_EVIDENCE_WRITE, message)


# ---------------------------------------------------------------------------
# Small validation / redaction helpers
# ---------------------------------------------------------------------------


def _key_name(value: Any) -> str:
    if not isinstance(value, str):
        raise EvidenceValidationError("evidence 字段名必须是字符串")
    return unicodedata.normalize("NFKC", value).strip().lower()


def _key_token(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", _key_name(value))


def _reject_forbidden_keys(value: Any, *, where: str = "evidence") -> None:
    """递归拒绝敏感/原文/文件/工具键，不能靠丢弃字段规避。"""

    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = _key_name(key)
            token = _key_token(key)
            if normalized not in _SAFE_KEY_NAMES and token in _FORBIDDEN_KEY_TOKENS:
                raise EvidenceValidationError(
                    f"{where} 含禁止落盘字段: {normalized}"
                )
            _reject_forbidden_keys(child, where=f"{where}.{normalized}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_forbidden_keys(child, where=f"{where}[{index}]")
    elif isinstance(value, (str, int, float, bool)) or value is None:
        return
    else:
        # Arbitrary objects can carry hidden document/source fields and are not
        # JSON evidence. Typed result objects are converted explicitly below.
        raise EvidenceValidationError(f"{where} 含不可序列化对象")


def _mapping(value: Any, *, where: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        result = dict(value)
    elif hasattr(value, "to_dict") and callable(value.to_dict):
        result = value.to_dict()
        if not isinstance(result, Mapping):
            raise EvidenceValidationError(f"{where} 的 to_dict() 必须返回对象")
        result = dict(result)
    else:
        raise EvidenceValidationError(f"{where} 必须是对象")
    _reject_forbidden_keys(result, where=where)
    return result


def _safe_text(value: Any, *, where: str, max_chars: int = 2000, allow_empty: bool = True) -> str:
    if not isinstance(value, str):
        raise EvidenceValidationError(f"{where} 必须是字符串")
    if not allow_empty and not value:
        raise EvidenceValidationError(f"{where} 不能为空")
    if len(value) > max_chars:
        raise EvidenceValidationError(f"{where} 超过脱敏长度上限")
    if any(ord(char) < 32 and char not in "\t\n" for char in value) or "\x7f" in value:
        raise EvidenceValidationError(f"{where} 含控制字符")
    # Evidence must not become a second outbound/document store.  These checks
    # are deliberately value-level in addition to the recursive key checks.
    if _URL_RE.search(value) or _WINDOWS_PATH_RE.search(value):
        raise EvidenceValidationError(f"{where} 不得包含 URL 或文件路径")
    if _SECRET_VALUE_RE.search(value):
        raise EvidenceValidationError(f"{where} 疑似包含 secret、prompt 或原文字段")
    return value


def _safe_token(value: Any, *, where: str, allow_empty: bool = True) -> str:
    if not isinstance(value, str):
        raise EvidenceValidationError(f"{where} 必须是安全标识字符串")
    if not value and allow_empty:
        return ""
    if not _TOKEN_RE.fullmatch(value):
        raise EvidenceValidationError(f"{where} 不是安全标识")
    return value


def _safe_version(value: Any, *, where: str) -> str:
    # Version identifiers are not secrets and may be empty for a disabled or
    # legacy record, but may never contain a path, query, or free-form text.
    return _safe_token(value, where=where, allow_empty=True)


def _safe_nonnegative_int(value: Any, *, where: str, allow_zero: bool = True) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EvidenceValidationError(f"{where} 必须是整数")
    if value < 0 or (not allow_zero and value == 0):
        raise EvidenceValidationError(f"{where} 必须是非负整数")
    return value


def _safe_confidence(value: Any, *, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvidenceValidationError(f"{where} 必须是数值")
    number = float(value)
    if not math.isfinite(number) or number < 0.0 or number > 1.0:
        raise EvidenceValidationError(f"{where} confidence 必须在 [0, 1]")
    return number


def _safe_hash(value: Any, *, where: str, allow_none: bool = False) -> str | None:
    if (value is None or value == "") and allow_none:
        return None
    if not isinstance(value, str):
        raise EvidenceValidationError(f"{where} 必须是 SHA-256 摘要")
    # Runtime clients emit a 64-character SHA-256.  Local contract stubs in
    # this project use labels such as ``request-hash``; permit only a clearly
    # marked, bounded placeholder so test metadata cannot force raw content
    # into a field intended for a digest.
    if _HASH_RE.fullmatch(value) or re.fullmatch(
        r"(?i)[A-Za-z0-9][A-Za-z0-9_.-]{0,126}hash", value
    ):
        return value
    raise EvidenceValidationError(f"{where} 必须是 SHA-256 摘要")


def _check_unknown(mapping: Mapping[str, Any], allowed: frozenset[str], *, where: str) -> None:
    unknown = {_key_name(key) for key in mapping} - allowed
    if unknown:
        raise EvidenceValidationError(
            f"{where} 含未授权字段: {sorted(unknown)}"
        )


def _sequence(value: Any, *, where: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise EvidenceValidationError(f"{where} 必须是数组")
    return list(value)


def _canonical_ref(value: Any, *, where: str) -> dict[str, Any]:
    raw = _mapping(value, where=where)
    _check_unknown(raw, _REF_KEYS, where=where)
    result: dict[str, Any] = {}
    for key in ("block_type", "group", "item_name"):
        if key in raw:
            result[key] = _safe_text(raw[key], where=f"{where}.{key}", max_chars=256)
    for key in ("table_idx", "row_idx"):
        if key in raw:
            result[key] = _safe_nonnegative_int(raw[key], where=f"{where}.{key}")
    if not result:
        raise EvidenceValidationError(f"{where} 不能为空")
    return result


def _canonical_call(value: Any, *, where: str) -> dict[str, Any]:
    # LLMCallMetadata is intentionally read by named attributes, not by
    # serializing an arbitrary object (which could include headers or content).
    if not isinstance(value, Mapping) and all(
        hasattr(value, name)
        for name in ("provider_host", "model", "attempts", "elapsed_ms", "transport", "status")
    ):
        raw: dict[str, Any] = {
            name: getattr(value, name)
            for name in _CALL_KEYS
            if hasattr(value, name)
        }
    else:
        raw = _mapping(value, where=where)
    _check_unknown(raw, _CALL_KEYS, where=where)

    provider_host = raw.get("provider_host", "")
    if not isinstance(provider_host, str):
        raise EvidenceValidationError(f"{where}.provider_host 必须是字符串")
    if provider_host:
        if (
            "://" in provider_host
            or any(char in provider_host for char in "/?#@\\")
            or any(char.isspace() for char in provider_host)
        ):
            raise EvidenceValidationError(
                f"{where}.provider_host 只能是 host，不能含完整 URL/query"
            )
        provider_host = _safe_text(provider_host, where=f"{where}.provider_host", max_chars=253)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.:-]{0,252}", provider_host):
            raise EvidenceValidationError(f"{where}.provider_host 不是合法 host")
        provider_host = provider_host.lower()

    model = _safe_text(raw.get("model", ""), where=f"{where}.model", max_chars=256)
    schema_version = _safe_version(raw.get("schema_version", ""), where=f"{where}.schema_version")
    attempts = _safe_nonnegative_int(raw.get("attempts", 0), where=f"{where}.attempts")
    if "elapsed" in raw and "elapsed_ms" in raw:
        raise EvidenceValidationError(f"{where} 同时包含 elapsed 与 elapsed_ms")
    elapsed_ms = _safe_nonnegative_int(
        raw.get("elapsed_ms", raw.get("elapsed", 0)), where=f"{where}.elapsed_ms"
    )
    transport = _safe_token(raw.get("transport", ""), where=f"{where}.transport")
    if transport not in _ALLOWED_TRANSPORTS:
        raise EvidenceValidationError(f"{where}.transport 不在允许集合")
    status = _safe_token(raw.get("status", ""), where=f"{where}.status")
    request_sha256 = _safe_hash(raw.get("request_sha256"), where=f"{where}.request_sha256")
    response_sha256 = _safe_hash(
        raw.get("response_sha256"), where=f"{where}.response_sha256", allow_none=True
    )
    result: dict[str, Any] = {
        "provider_host": provider_host,
        "model": model,
        "attempts": attempts,
        "elapsed_ms": elapsed_ms,
        "transport": transport,
        "status": status,
        "request_sha256": request_sha256,
        "response_sha256": response_sha256,
    }
    if schema_version:
        result["schema_version"] = schema_version
    if "error_code" in raw and raw["error_code"]:
        result["error_code"] = _safe_token(raw["error_code"], where=f"{where}.error_code")
    if "fallback_reason" in raw and raw["fallback_reason"]:
        result["fallback_reason"] = _safe_text(
            raw["fallback_reason"], where=f"{where}.fallback_reason", max_chars=512
        )
    return result


def _canonical_candidate(value: Any, *, where: str) -> dict[str, Any]:
    raw = _mapping(value, where=where)
    _check_unknown(raw, _CANDIDATE_KEYS, where=where)
    capability = _safe_token(raw.get("capability", "candidate"), where=f"{where}.capability")
    if capability not in _ALLOWED_CAPABILITIES:
        raise EvidenceValidationError(f"{where}.capability 未知")
    status = _safe_token(raw.get("status", "pending"), where=f"{where}.status")
    if status not in _ALLOWED_CANDIDATE_STATUSES:
        raise EvidenceValidationError(f"{where}.status 不是候选状态")
    source = _safe_token(raw.get("source", "llm"), where=f"{where}.source")
    result = {
        "candidate_key": _safe_token(
            raw.get("candidate_key", ""), where=f"{where}.candidate_key", allow_empty=False
        ),
        "capability": capability,
        "cert_ref": _canonical_ref(raw.get("cert_ref"), where=f"{where}.cert_ref"),
        "draft_ref": _canonical_ref(raw.get("draft_ref"), where=f"{where}.draft_ref"),
        "confidence": _safe_confidence(raw.get("confidence"), where=f"{where}.confidence"),
        "reason": _safe_text(raw.get("reason", ""), where=f"{where}.reason", max_chars=1000),
        "status": status,
        "source": source,
        "policy_version": _safe_version(
            raw.get("policy_version", ""), where=f"{where}.policy_version"
        ),
        "schema_version": _safe_version(
            raw.get("schema_version", ""), where=f"{where}.schema_version"
        ),
    }
    return result


def _canonical_explanation(value: Any, *, where: str) -> dict[str, Any]:
    raw = _mapping(value, where=where)
    _check_unknown(raw, _EXPLANATION_KEYS, where=where)
    status = _safe_token(raw.get("status", "pending"), where=f"{where}.status")
    source = _safe_token(raw.get("source", "llm"), where=f"{where}.source")
    return {
        "diff_key": _safe_text(
            raw.get("diff_key", ""), where=f"{where}.diff_key", max_chars=256, allow_empty=False
        ),
        "explanation": _safe_text(
            raw.get("explanation", ""), where=f"{where}.explanation", max_chars=2000
        ),
        "risk": _safe_text(raw.get("risk", ""), where=f"{where}.risk", max_chars=1000),
        "source": source,
        "status": status,
        "schema_version": _safe_version(
            raw.get("schema_version", ""), where=f"{where}.schema_version"
        ),
    }


def _canonical_discipline(value: Any, *, where: str) -> dict[str, Any]:
    raw = _mapping(value, where=where)
    _check_unknown(raw, _DISCIPLINE_KEYS, where=where)
    if "candidate_discipline" in raw and "discipline" in raw:
        raise EvidenceValidationError(f"{where} 同时包含 candidate_discipline 与 discipline")
    candidate_discipline = raw.get("candidate_discipline", raw.get("discipline", ""))
    status = _safe_token(raw.get("status", "pending"), where=f"{where}.status")
    source = _safe_token(raw.get("source", "llm"), where=f"{where}.source")
    return {
        "diff_key": _safe_text(
            raw.get("diff_key", ""), where=f"{where}.diff_key", max_chars=256, allow_empty=False
        ),
        # Output uses candidate_discipline even if the input came from the
        # model's raw ``discipline`` field, so it cannot be mistaken for the
        # final VerifyDiff.discipline field.
        "candidate_discipline": _safe_text(
            candidate_discipline,
            where=f"{where}.candidate_discipline",
            max_chars=256,
            allow_empty=False,
        ),
        "reason": _safe_text(raw.get("reason", ""), where=f"{where}.reason", max_chars=1000),
        "confidence": _safe_confidence(raw.get("confidence"), where=f"{where}.confidence"),
        "source": source,
        "status": status,
        "rule_version": _safe_version(
            raw.get("rule_version", ""), where=f"{where}.rule_version"
        ),
        "schema_version": _safe_version(
            raw.get("schema_version", ""), where=f"{where}.schema_version"
        ),
    }


def _canonical_warning(value: Any, *, where: str) -> dict[str, str]:
    if isinstance(value, str):
        return {
            "code": "llm_warning",
            "message": _safe_text(value, where=where, max_chars=1000),
        }
    raw = _mapping(value, where=where)
    _check_unknown(raw, _WARNING_KEYS, where=where)
    code = raw.get("code", raw.get("error_code", "llm_warning"))
    return {
        "code": _safe_token(code, where=f"{where}.code", allow_empty=False),
        "message": _safe_text(
            raw.get("message", ""), where=f"{where}.message", max_chars=1000
        ),
    }


# ---------------------------------------------------------------------------
# Typed evidence data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LLMCallSummary:
    """单次 provider 调用的非敏感摘要。"""

    provider_host: str = ""
    model: str = ""
    attempts: int = 0
    elapsed_ms: int = 0
    transport: str = ""
    status: str = ""
    request_sha256: str = ""
    response_sha256: str | None = None
    schema_version: str = ""
    error_code: str = ""
    fallback_reason: str = ""

    @classmethod
    def from_value(cls, value: Any, *, where: str = "call") -> "LLMCallSummary":
        data = _canonical_call(value, where=where)
        return cls(
            provider_host=data["provider_host"],
            model=data["model"],
            attempts=data["attempts"],
            elapsed_ms=data["elapsed_ms"],
            transport=data["transport"],
            status=data["status"],
            request_sha256=data["request_sha256"],
            response_sha256=data["response_sha256"],
            schema_version=data.get("schema_version", ""),
            error_code=data.get("error_code", ""),
            fallback_reason=data.get("fallback_reason", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "provider_host": self.provider_host,
            "model": self.model,
            "attempts": self.attempts,
            "elapsed_ms": self.elapsed_ms,
            "transport": self.transport,
            "status": self.status,
            "request_sha256": self.request_sha256,
            "response_sha256": self.response_sha256,
        }
        if self.schema_version:
            result["schema_version"] = self.schema_version
        if self.error_code:
            result["error_code"] = self.error_code
        if self.fallback_reason:
            result["fallback_reason"] = self.fallback_reason
        return result


# Names used by callers that prefer the design document's terminology.
CallSummary = LLMCallSummary
LLMCallEvidence = LLMCallSummary


@dataclass(frozen=True)
class LLMEvidence:
    """LLM 附属 evidence 的 typed representation。

    ``candidates``、``explanations`` 和 ``discipline_suggestions`` 内部使用 tuple
    防止调用方在写入前悄悄修改对象；真正序列化前仍会再次走白名单校验。
    """

    mode: str = "off"
    status: str = "disabled"
    capabilities: tuple[str, ...] = ()
    candidates: tuple[Mapping[str, Any], ...] = ()
    explanations: tuple[Mapping[str, Any], ...] = ()
    discipline_suggestions: tuple[Mapping[str, Any], ...] = ()
    calls: tuple[LLMCallSummary, ...] = ()
    warnings: tuple[Mapping[str, str], ...] = ()
    error_codes: tuple[str, ...] = ()
    policy_version: str = ""
    schema_version: str = ""
    rule_version: str = ""
    trace_id: str = ""
    job_id: str = ""
    evidence_version: str = EVIDENCE_VERSION
    error_code: str = ""

    def __post_init__(self) -> None:
        # Make direct construction predictable; write/read still revalidate.
        object.__setattr__(self, "capabilities", tuple(_input_items(self.capabilities)))
        object.__setattr__(self, "candidates", tuple(_input_items(self.candidates)))
        object.__setattr__(self, "explanations", tuple(_input_items(self.explanations)))
        object.__setattr__(
            self,
            "discipline_suggestions",
            tuple(_input_items(self.discipline_suggestions)),
        )
        object.__setattr__(self, "calls", tuple(_input_items(self.calls)))
        object.__setattr__(self, "warnings", tuple(_input_items(self.warnings)))
        object.__setattr__(self, "error_codes", tuple(_input_items(self.error_codes)))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "LLMEvidence":
        raw = dict(value)
        _reject_forbidden_keys(raw)
        _check_unknown(
            raw,
            _TOP_LEVEL_KEYS | _TOP_LEVEL_ALIASES,
            where="evidence",
        )

        mode = raw.get("mode", "off")
        if not isinstance(mode, str) or mode not in _ALLOWED_MODES:
            raise EvidenceValidationError("evidence.mode 不是允许的 LLM mode")
        status = _safe_token(raw.get("status", "disabled"), where="evidence.status")
        evidence_version = _safe_version(
            raw.get("evidence_version", EVIDENCE_VERSION), where="evidence.evidence_version"
        )
        capabilities_raw = _sequence(raw.get("capabilities", []), where="evidence.capabilities")
        capabilities: list[str] = []
        for index, item in enumerate(capabilities_raw):
            capability = _safe_token(item, where=f"evidence.capabilities[{index}]")
            if capability not in _ALLOWED_CAPABILITIES:
                raise EvidenceValidationError(f"未知 capability: {capability}")
            if capability not in capabilities:
                capabilities.append(capability)
        capabilities.sort()

        candidates_raw = raw.get("candidates", raw.get("candidate_suggestions", []))
        explanations_raw = raw.get("explanations", raw.get("explanation_suggestions", []))
        discipline_raw = raw.get(
            "discipline_suggestions", raw.get("discipline", [])
        )
        calls_raw = raw.get("calls", raw.get("call_summaries", []))
        warnings_raw = raw.get("warnings", raw.get("warning", []))
        if isinstance(warnings_raw, (str, Mapping)):
            warnings_raw = [warnings_raw]

        candidates = tuple(
            _canonical_candidate(item, where=f"evidence.candidates[{index}]")
            for index, item in enumerate(_sequence(candidates_raw, where="evidence.candidates"))
        )
        explanations = tuple(
            _canonical_explanation(item, where=f"evidence.explanations[{index}]")
            for index, item in enumerate(_sequence(explanations_raw, where="evidence.explanations"))
        )
        discipline_suggestions = tuple(
            _canonical_discipline(item, where=f"evidence.discipline_suggestions[{index}]")
            for index, item in enumerate(
                _sequence(discipline_raw, where="evidence.discipline_suggestions")
            )
        )
        calls = tuple(
            LLMCallSummary.from_value(item, where=f"evidence.calls[{index}]")
            for index, item in enumerate(_sequence(calls_raw, where="evidence.calls"))
        )
        warnings = tuple(
            _canonical_warning(item, where=f"evidence.warnings[{index}]")
            for index, item in enumerate(_sequence(warnings_raw, where="evidence.warnings"))
        )

        error_codes_raw = _sequence(raw.get("error_codes", []), where="evidence.error_codes")
        error_codes: list[str] = []
        for index, item in enumerate(error_codes_raw):
            code = _safe_token(item, where=f"evidence.error_codes[{index}]", allow_empty=False)
            if code not in error_codes:
                error_codes.append(code)
        singular_error = raw.get("error_code", "")
        if singular_error:
            singular_error = _safe_token(
                singular_error, where="evidence.error_code", allow_empty=False
            )
            if singular_error not in error_codes:
                error_codes.insert(0, singular_error)
        error_code = error_codes[0] if error_codes else ""

        for name in ("policy_version", "schema_version", "rule_version"):
            _safe_version(raw.get(name, ""), where=f"evidence.{name}")
        trace_id = _safe_token(raw.get("trace_id", ""), where="evidence.trace_id")
        job_id = _safe_token(raw.get("job_id", ""), where="evidence.job_id")

        return cls(
            mode=mode,
            status=status,
            capabilities=tuple(capabilities),
            candidates=candidates,
            explanations=explanations,
            discipline_suggestions=discipline_suggestions,
            calls=calls,
            warnings=warnings,
            error_codes=tuple(error_codes),
            policy_version=raw.get("policy_version", ""),
            schema_version=raw.get("schema_version", ""),
            rule_version=raw.get("rule_version", ""),
            trace_id=trace_id,
            job_id=job_id,
            evidence_version=evidence_version,
            error_code=error_code,
        )

    def _to_dict_unchecked(self) -> dict[str, Any]:
        return {
            "evidence_version": self.evidence_version,
            "mode": self.mode,
            "status": self.status,
            "capabilities": list(self.capabilities),
            "candidates": [
                dict(item) if isinstance(item, Mapping) else _mapping(item, where="candidates")
                for item in self.candidates
            ],
            "explanations": [
                dict(item) if isinstance(item, Mapping) else _mapping(item, where="explanations")
                for item in self.explanations
            ],
            "discipline_suggestions": [
                dict(item)
                if isinstance(item, Mapping)
                else _mapping(item, where="discipline_suggestions")
                for item in self.discipline_suggestions
            ],
            "calls": [
                (
                    item.to_dict()
                    if isinstance(item, LLMCallSummary)
                    else LLMCallSummary.from_value(
                        item, where="evidence.calls"
                    ).to_dict()
                )
                for item in self.calls
            ],
            "warnings": [
                dict(item)
                if isinstance(item, Mapping)
                else {"code": "llm_warning", "message": item}
                for item in self.warnings
            ],
            "error_codes": list(self.error_codes),
            "error_code": self.error_code,
            "policy_version": self.policy_version,
            "schema_version": self.schema_version,
            "rule_version": self.rule_version,
            "trace_id": self.trace_id,
            "job_id": self.job_id,
        }

    def to_dict(self) -> dict[str, Any]:
        """返回经过完整递归白名单校验的 canonical mapping。"""

        return sanitize_evidence(self)


    @property
    def call_summaries(self) -> tuple[LLMCallSummary, ...]:
        """兼容 design 文档中 ``call_summaries`` 的称呼。"""

        return self.calls


# ---------------------------------------------------------------------------
# Building and recursive redaction API
# ---------------------------------------------------------------------------


def _input_items(value: Any) -> list[Any]:
    """把单个 mapping/string 或 iterable 统一成 evidence item 列表。"""

    if value is None:
        return []
    if isinstance(value, (str, bytes, Mapping)):
        return [value]
    try:
        return list(value)
    except TypeError:
        return [value]


def _result_mapping(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        result = value.to_dict()
        return dict(result) if isinstance(result, Mapping) else None
    return None


def _result_value(value: Any, name: str, default: Any = None) -> Any:
    mapping = _result_mapping(value)
    if mapping is not None and name in mapping:
        return mapping[name]
    return getattr(value, name, default) if value is not None else default


def _result_metadata(value: Any) -> Mapping[str, Any]:
    metadata = _result_value(value, "metadata", {})
    return metadata if isinstance(metadata, Mapping) else {}


def _result_collection(value: Any, name: str) -> list[Any]:
    collection = _result_value(value, name, ())
    if collection is None:
        return []
    if isinstance(collection, (list, tuple)):
        return list(collection)
    return []


def _component_call(value: Any) -> list[Any]:
    """只投影已知调用摘要字段，不把 metadata 其它键带入 evidence。"""

    metadata = _result_metadata(value)
    calls = metadata.get("calls", metadata.get("call", []))
    if calls is None:
        return []
    raw_calls = list(calls) if isinstance(calls, (list, tuple)) else [calls]
    projected: list[Any] = []
    for call in raw_calls:
        if isinstance(call, Mapping):
            # ``metadata`` from an adapter may contain prompt/response or
            # transport internals.  Explicitly select only summary fields.
            projected.append({key: call[key] for key in _CALL_KEYS if key in call})
            continue
        if all(hasattr(call, name) for name in ("provider_host", "model", "attempts", "elapsed_ms", "transport", "status")):
            projected.append(
                {
                    name: getattr(call, name)
                    for name in _CALL_KEYS
                    if hasattr(call, name)
                }
            )
            continue
        # Leave unsupported objects for the normal validator to reject.
        projected.append(call)
    return projected


def build_evidence(
    *,
    mode: str = "off",
    status: str | None = None,
    capabilities: Iterable[str] | None = None,
    candidates: Iterable[Any] | None = None,
    explanations: Iterable[Any] | None = None,
    discipline_suggestions: Iterable[Any] | None = None,
    calls: Iterable[Any] | None = None,
    warnings: Iterable[Any] | None = None,
    error_code: str = "",
    error_codes: Iterable[str] | None = None,
    policy_version: str = "",
    schema_version: str = "",
    rule_version: str = "",
    trace_id: str = "",
    job_id: str = "",
    candidate_result: Any = None,
    explanation_result: Any = None,
    discipline_result: Any = None,
) -> LLMEvidence:
    """从已有 2.1--2.3 结果构造脱敏 evidence。

    ``candidate_result`` / ``explanation_result`` / ``discipline_result`` 可以是
    对应模块的结果对象或其 ``to_dict`` mapping；函数只读取它们的建议、状态、
    脱敏 call 摘要和 error code，不复制其 ``metadata`` 中的任意其它字段。
    """

    components = [candidate_result, explanation_result, discipline_result]
    component_items = [
        _result_collection(candidate_result, "candidates"),
        _result_collection(explanation_result, "explanations"),
        _result_collection(discipline_result, "suggestions"),
    ]

    all_candidates = _input_items(candidates) if candidates is not None else component_items[0]
    all_explanations = (
        _input_items(explanations) if explanations is not None else component_items[1]
    )
    all_discipline = (
        _input_items(discipline_suggestions)
        if discipline_suggestions is not None
        else component_items[2]
    )
    all_calls = _input_items(calls) if calls is not None else []
    for component in components:
        all_calls.extend(_component_call(component))

    explicit_warnings = _input_items(warnings) if warnings is not None else []
    collected_error_codes = _input_items(error_codes)
    component_statuses: list[str] = []
    for component in components:
        if component is None:
            continue
        component_status = _result_value(component, "status", "")
        if isinstance(component_status, str) and component_status:
            component_statuses.append(component_status)
        component_code = _result_value(component, "error_code", "")
        if isinstance(component_code, str) and component_code:
            collected_error_codes.append(component_code)
            explicit_warnings.append(
                {
                    "code": component_code,
                    "message": "LLM capability 未采纳，已保留确定性证据",
                }
            )

        metadata = _result_metadata(component)
        if not policy_version and isinstance(metadata.get("policy_version"), str):
            policy_version = metadata["policy_version"]
        if not schema_version and isinstance(metadata.get("schema_version"), str):
            schema_version = metadata["schema_version"]
        if not rule_version and isinstance(metadata.get("rule_version"), str):
            rule_version = metadata["rule_version"]
        if mode == "off" and isinstance(metadata.get("mode"), str):
            mode = metadata["mode"]

    if not all_calls:
        all_calls = []
    if capabilities is None:
        inferred: set[str] = set()
        if all_candidates:
            inferred.add("candidate")
        if all_explanations:
            inferred.add("explain")
        if all_discipline:
            inferred.add("discipline")
        capabilities = sorted(inferred)
    else:
        capabilities = _input_items(capabilities)

    if status is None:
        # Prefer an explicit component status; when there are several, a
        # non-disabled failure/success is more informative than disabled.
        status = next(
            (item for item in component_statuses if item not in {"disabled", "skipped_policy"}),
            component_statuses[0] if component_statuses else ("success" if capabilities else "disabled"),
        )

    return LLMEvidence(
        mode=mode,
        status=status,
        capabilities=tuple(capabilities),
        candidates=tuple(_mapping(item, where="candidates") if not isinstance(item, Mapping) else item for item in all_candidates),
        explanations=tuple(_mapping(item, where="explanations") if not isinstance(item, Mapping) else item for item in all_explanations),
        discipline_suggestions=tuple(
            _mapping(item, where="discipline_suggestions") if not isinstance(item, Mapping) else item
            for item in all_discipline
        ),
        calls=tuple(
            item if isinstance(item, LLMCallSummary) else item
            for item in all_calls
        ),
        warnings=tuple(
            item if isinstance(item, Mapping) else {"code": "llm_warning", "message": item}
            for item in explicit_warnings
        ),
        error_codes=tuple(collected_error_codes),
        error_code=error_code,
        policy_version=policy_version,
        schema_version=schema_version,
        rule_version=rule_version,
        trace_id=trace_id,
        job_id=job_id,
    )


def sanitize_evidence(value: LLMEvidence | Mapping[str, Any]) -> dict[str, Any]:
    """递归校验并返回只含白名单字段的 canonical evidence mapping。

    该函数不会把禁止字段“静默丢弃”：任何 secret、prompt/response、CERT/DRAFT
    原文、图片、路径、工具调用或未知字段都会抛出 :class:`EvidenceValidationError`。
    """

    if isinstance(value, LLMEvidence):
        raw = value._to_dict_unchecked()
    elif isinstance(value, Mapping):
        raw = dict(value)
    else:
        raise EvidenceValidationError("evidence 必须是 LLMEvidence 或对象")
    model = LLMEvidence.from_mapping(raw)
    return model._to_dict_unchecked()


# Common names for integrations/tests that call this operation redaction rather
# than sanitization.  They intentionally share the strict reject-on-failure
# behavior above.
redact_evidence = sanitize_evidence
validate_evidence = sanitize_evidence


# ---------------------------------------------------------------------------
# Safe path and atomic persistence
# ---------------------------------------------------------------------------


def _coerce_path(value: str | os.PathLike[str], *, for_write: bool) -> Path:
    try:
        raw = os.fspath(value)
    except TypeError:
        raise EvidencePathError("evidence 路径必须是本地文件路径") from None
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise EvidencePathError("evidence 路径为空或含非法字符")
    unresolved = Path(raw).expanduser()
    if unresolved.exists() and unresolved.is_symlink():
        raise EvidencePathError("evidence 目标不能是符号链接")
    if unresolved.parent.exists() and unresolved.parent.is_symlink():
        raise EvidencePathError("evidence 父路径不能是符号链接")
    target = unresolved
    try:
        target = target.resolve(strict=False)
    except OSError:
        raise EvidencePathError("evidence 路径无法解析") from None
    if target.name in {"job.json", "verification.json"} and for_write:
        raise EvidencePathError("不得覆盖 job.json 或确定性 verification.json")
    if target.exists() and target.is_symlink():
        raise EvidencePathError("evidence 目标不能是符号链接")
    if target.exists() and target.is_dir():
        raise EvidencePathError("evidence 目标必须是文件")
    parent = target.parent
    if parent.exists() and not parent.is_dir():
        raise EvidencePathError("evidence 父路径不是目录")
    return target


def evidence_path_for(verification_path: str | os.PathLike[str]) -> Path:
    """返回与确定性 ``verification.json`` 同目录的独立 sidecar 路径。"""

    source = _coerce_path(verification_path, for_write=False)
    return source.with_name(EVIDENCE_FILENAME)


def _atomic_write_json(target: Path, payload: Mapping[str, Any]) -> Path:
    parent = target.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
        if not parent.is_dir():
            raise EvidencePathError("evidence 父路径不是目录")
        if not os.access(parent, os.W_OK):
            raise EvidencePathError("evidence 父目录不可写")
        if target.exists() and not os.access(target, os.W_OK):
            raise EvidencePathError("已有 evidence 文件不可写")
    except EvidenceError:
        raise
    except OSError:
        raise EvidencePathError("evidence 目录创建或权限检查失败") from None

    temp_name: str | None = None
    try:
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=str(parent)
        )
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
        temp_name = None
        # Directory fsync is not available on every Windows filesystem.  The
        # rename is still atomic; ignore only this optional durability step.
        try:
            directory_fd = os.open(str(parent), os.O_RDONLY)
        except (AttributeError, OSError):
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            except OSError:
                pass
            finally:
                os.close(directory_fd)
        return target
    except EvidenceError:
        raise
    except (OSError, TypeError, ValueError):
        raise EvidenceWriteError("LLM evidence 原子写入失败，既有文件未被替换") from None
    finally:
        if temp_name:
            try:
                os.unlink(temp_name)
            except OSError:
                pass


def write_evidence(
    path: str | os.PathLike[str], evidence: LLMEvidence | Mapping[str, Any]
) -> Path:
    """校验并原子写入独立 evidence 文件，返回目标路径。

    ``verification.json`` / ``job.json`` 会被显式拒绝，调用方应使用
    :func:`write_evidence_for_verification` 写入同目录 ``llm-evidence.json``。
    """

    target = _coerce_path(path, for_write=True)
    payload = sanitize_evidence(evidence)
    return _atomic_write_json(target, payload)


write_llm_evidence = write_evidence
write_evidence_atomic = write_evidence


def write_evidence_for_verification(
    verification_path: str | os.PathLike[str],
    evidence: LLMEvidence | Mapping[str, Any],
) -> Path:
    """在 deterministic verification 旁写 sidecar，不读取或修改原文件。"""

    return write_evidence(evidence_path_for(verification_path), evidence)


# ---------------------------------------------------------------------------
# Read compatibility layer
# ---------------------------------------------------------------------------


def _read_json_file(path: Path) -> Any:
    if not path.exists():
        raise EvidenceReadError("evidence 文件不存在", missing=True)
    if path.is_symlink() or not path.is_file():
        raise EvidencePathError("evidence 读取目标不是普通文件")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise EvidenceReadError("evidence 文件读取失败") from None
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        raise EvidenceReadError("evidence 不是合法 UTF-8 JSON") from None


def _legacy_absent() -> dict[str, Any]:
    return LLMEvidence(
        status="disabled",
        warnings=(
            {
                "code": "llm_evidence_absent",
                "message": "旧 verification.json 未包含 LLM evidence",
            },
        ),
    ).to_dict()


def _extract_read_payload(raw: Any, *, source_name: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise EvidenceValidationError(f"{source_name} 顶层必须是对象")
    # A deterministic verification trace may contain many sensitive fields.  We
    # intentionally select only its llm node before any conversion, rather than
    # recursively sanitizing/copying the whole verification object.
    if "llm" in raw:
        node = raw["llm"]
        if not isinstance(node, Mapping):
            raise EvidenceValidationError("verification.json 的 llm 节点必须是对象")
        return node
    if "evidence_version" in raw or "mode" in raw or "candidates" in raw:
        return raw
    # An independent sidecar is authoritative evidence, not a legacy
    # verification container.  Even a malformed/unknown-only sidecar must pass
    # the normal whitelist validator so forbidden prompt/response/secret fields
    # cannot be silently downgraded to a disabled response.
    if source_name == EVIDENCE_FILENAME:
        return raw
    return _legacy_absent()


def read_evidence(
    path: str | os.PathLike[str], *, prefer_sidecar: bool = True
) -> dict[str, Any]:
    """读取并重新校验脱敏 evidence；兼容旧 ``verification.json``。

    传入 ``verification.json`` 时优先读取同目录 sidecar；若 sidecar 不存在，
    只读取旧文件的 ``llm`` 节点。旧文件没有该节点时返回 disabled/absent 的
    canonical evidence，而不会返回其 ``result``、路径或文档内容。
    """

    source = _coerce_path(path, for_write=False)
    if source.name == "verification.json" and prefer_sidecar:
        sidecar = source.with_name(EVIDENCE_FILENAME)
        if sidecar.exists():
            raw = _read_json_file(sidecar)
            payload = _extract_read_payload(raw, source_name=EVIDENCE_FILENAME)
            return sanitize_evidence(payload)

    raw = _read_json_file(source)
    payload = _extract_read_payload(raw, source_name=source.name)
    return sanitize_evidence(payload)


read_llm_evidence = read_evidence
read_evidence_compatible = read_evidence
read_verification_evidence = read_evidence


__all__ = [
    "EVIDENCE_FILENAME",
    "EVIDENCE_VERSION",
    "ERROR_EVIDENCE_INVALID",
    "ERROR_EVIDENCE_PATH",
    "ERROR_EVIDENCE_READ",
    "ERROR_EVIDENCE_WRITE",
    "ERROR_EVIDENCE_MISSING",
    "EvidenceError",
    "EvidenceValidationError",
    "EvidencePathError",
    "EvidenceReadError",
    "EvidenceWriteError",
    "LLMCallSummary",
    "LLMCallEvidence",
    "CallSummary",
    "LLMEvidence",
    "build_evidence",
    "sanitize_evidence",
    "redact_evidence",
    "validate_evidence",
    "evidence_path_for",
    "write_evidence",
    "write_llm_evidence",
    "write_evidence_atomic",
    "write_evidence_for_verification",
    "read_evidence",
    "read_llm_evidence",
    "read_evidence_compatible",
    "read_verification_evidence",
]
