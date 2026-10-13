"""ReportVerify 的 LLM 响应严格 Schema 与本地安全校验（任务 1.5）。

本模块承接任务 1.3 的 client：输入是 ``repair_json`` 之后的**语法层已修复**
字符串（去围栏、截取第一个 JSON 对象），本模块负责在其之上执行

- 严格 JSON 解析（拒绝非法 JSON）；
- 每个 capability 独立的 Schema（``candidate`` / ``explain`` / ``discipline``）；
- 本地安全校验：schema version 必须匹配、必需字段齐备、拒绝未知字段、索引越界、
  重复 cert/draft index、confidence 不在 ``[0, 1]``、跨子块（block_type）/跨组
  pair、未知 diff key、非允许专业、过长 reason，以及任何会被解释成**自动
  verdict** 的字段。

设计契约（与 design.md `report_verify.llm.schemas` 一致）：

- **CertAgent 的 JSON repair 只是语法容错，不是信任边界。** 任何 repair 之后的
  内容仍必须通过本模块的严格校验，才能进入后续候选/解释流程。
- 本模块**只产出结构化校验结果**，不改变确定性 ``result.diffs``、不写最终
  ``verdict``、不改变 ``normalize_for_compare``、不交换 CERT/DRAFT 方向。
- 索引/子块/组/一对一约束需要**调用方提供候选池上下文**（见
  :class:`CandidateContext`）：确定性引擎残余的 CERT/DRAFT 行索引集合，以及
  每个索引所属的逻辑子块（``block_type``）与分组。本模块只校验，不自行读取文档
  或规则。**注意**：CERT 与 DRAFT 是两个独立文档、物理表号各自独立编号，因此
  同块护栏比较的是 ``block_type``，绝不跨文档比较 ``table_idx``。
- 校验失败一律返回明确失败（:class:`ValidationOutcome`，``ok=False`` 且带
  分类错误码），调用方据此**回退到确定性证据**；本模块绝不猜测修复业务值。

安全：本模块不接触凭据、不发起网络请求、不记录原文；错误消息只包含结构化的
定位信息（字段名、索引、错误码），不回显完整响应正文。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

# 分类错误码，与 design.md 的 Error Handling 表一致。
ERROR_SCHEMA_INVALID = "llm_schema_invalid"
ERROR_SAFETY_REJECTED = "llm_safety_rejected"

# 能力标识（与 policy.CAPABILITY_FIELD_WHITELIST 对齐）。
CAPABILITY_CANDIDATE = "candidate"
CAPABILITY_EXPLAIN = "explain"
CAPABILITY_DISCIPLINE = "discipline"

ALL_CAPABILITIES: frozenset[str] = frozenset(
    {CAPABILITY_CANDIDATE, CAPABILITY_EXPLAIN, CAPABILITY_DISCIPLINE}
)

# reason / explanation 等自由文本的默认最大长度（字符）。过长即拒绝，避免模型
# 借由超长文本夹带指令或撑大后续存储。
DEFAULT_MAX_REASON_CHARS = 500

# 与确定性引擎（verify_differ）一致的 diff_type 全集。explain/discipline 引用的
# ``diff_key`` 必须来自已存在的确定性差异；这里额外用于结构合法性提示。
DETERMINISTIC_DIFF_TYPES: frozenset[str] = frozenset({
    "field_mismatch",
    "missing_in_draft",
    "extra_in_draft",
    "table_missing_in_draft",
    "table_extra_in_draft",
    "block_missing_in_draft",
    "block_extra_in_draft",
})

# 任何出现在模型输出里、会被解释成**自动 verdict / 自动决策 / 自动路由**的键，
# 一律拒绝。LLM 只能提名候选与解释，绝不能给出结论、动作或写最终字段。
FORBIDDEN_VERDICT_KEYS: frozenset[str] = frozenset({
    "verdict",
    "decision",
    "decisions",
    "accept",
    "accepted",
    "ignore",
    "ignored",
    "reject",
    "rejected",
    "resolution",
    "resolved",
    "auto_accept",
    "auto_verdict",
    "auto_apply",
    "apply",
    "action",
    "actions",
    "final",
    "final_verdict",
    "review_status",
    "reviewed_by",
    "download_ready",
    "discipline_status",
    "status",
    "approved",
    "approval",
    "route",
    "routing",
    "assign",
    "assignment",
})


class SchemaValidationError(Exception):
    """Schema / 安全校验失败。``code`` 为 design.md 中的分类错误码。

    消息只包含结构化定位信息（字段名、索引），不回显完整响应正文或凭据。
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# 调用方提供的候选池上下文
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CandidateContext:
    """候选匹配的候选池上下文，由**调用方**（orchestrator）提供。

    本模块用它校验 LLM 返回的候选 pair 的索引/表/组/一对一约束，而**不**自行
    读取文档或规则。

    **跨文档语义（重要）**：CERT 与 DRAFT 是两个**独立文档**，各自的物理表号
    独立编号（例如 CERT 的 ``safety_list`` 在第 7 张表，而 DRAFT 的 ``safety_list``
    在第 1 张表）。因此"同块"护栏比较的是**逻辑子块** ``block_type``，
    **绝不**跨 CERT/DRAFT 比较 ``table_idx``——那样任何合法候选都会被误拒。

    - ``cert_indices`` / ``draft_indices``：确定性引擎残余、可被候选引用的合法
      索引集合。任何超出集合的索引视为越界。
    - ``cert_block_type`` / ``draft_block_type``：索引 -> 逻辑子块标识
      （``safety_list`` / ``emc_list`` 等），用于同子块校验。两侧 block_type 必须
      相等；任一侧缺失映射即拒绝（fail closed）。
    - ``cert_table`` / ``draft_table``：索引 -> **同侧文档内**的物理表号。仅作
      同侧定位/诊断信息保留，**不参与**跨文档比较。
    - ``cert_group`` / ``draft_group``：索引 -> 分组标识，用于兼容分组校验。
      分组为空串表示未分组；两侧分组必须相等（含都为空）才视为同组。
    - ``same_block_only`` / ``same_group_only``：护栏开关，默认开启。
      ``same_table_only`` 是 ``same_block_only`` 的**已弃用别名**，仅为向后兼容
      保留：显式传入时按"同逻辑子块"语义生效（传 ``False`` 关闭该护栏）。
    - ``min_confidence``：候选置信度阈值（低于该值的候选被拒绝，不静默丢弃）。
    """

    cert_indices: frozenset[int] = field(default_factory=frozenset)
    draft_indices: frozenset[int] = field(default_factory=frozenset)
    cert_block_type: Mapping[int, str] = field(default_factory=dict)
    draft_block_type: Mapping[int, str] = field(default_factory=dict)
    cert_table: Mapping[int, int] = field(default_factory=dict)
    draft_table: Mapping[int, int] = field(default_factory=dict)
    cert_group: Mapping[int, str] = field(default_factory=dict)
    draft_group: Mapping[int, str] = field(default_factory=dict)
    same_block_only: bool = True
    same_group_only: bool = True
    min_confidence: float = 0.0
    # 已弃用别名：仅为兼容旧调用方（语义已改为"同逻辑子块"）。None 表示未显式传入。
    same_table_only: bool | None = None

    @property
    def block_guard_enabled(self) -> bool:
        """同逻辑子块护栏是否启用（兼容已弃用的 ``same_table_only`` 别名）。"""

        if self.same_table_only is None:
            return self.same_block_only
        return bool(self.same_table_only) and bool(self.same_block_only)


@dataclass(frozen=True)
class ExplainContext:
    """差异解释上下文：调用方提供的**已存在**确定性 diff key 集合。

    解释只能引用已经落盘的 ``VerifyDiff.key``；未知 diff key 一律拒绝，防止模型
    凭空创造差异。
    """

    known_diff_keys: frozenset[str] = field(default_factory=frozenset)
    max_reason_chars: int = DEFAULT_MAX_REASON_CHARS


@dataclass(frozen=True)
class DisciplineContext:
    """专业候选上下文：调用方提供的已发布专业 allowlist 与已存在 diff key。

    - ``known_diff_keys``：候选必须引用已存在的确定性 diff key。
    - ``allowed_disciplines``：已发布规则允许的专业集合；非允许专业一律拒绝。
      为空表示当前无已发布专业规则，任何专业候选都拒绝（保持 discipline_pending）。
    """

    known_diff_keys: frozenset[str] = field(default_factory=frozenset)
    allowed_disciplines: frozenset[str] = field(default_factory=frozenset)
    max_reason_chars: int = DEFAULT_MAX_REASON_CHARS
    min_confidence: float = 0.0


# ---------------------------------------------------------------------------
# 校验后的结构化结果（只读、不含 verdict）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CandidatePair:
    cert_index: int
    draft_index: int
    confidence: float
    reason: str


@dataclass(frozen=True)
class CandidateResponse:
    schema_version: str
    pairs: tuple[CandidatePair, ...]


@dataclass(frozen=True)
class Explanation:
    diff_key: str
    explanation: str
    risk: str


@dataclass(frozen=True)
class ExplanationResponse:
    schema_version: str
    explanations: tuple[Explanation, ...]


@dataclass(frozen=True)
class DisciplineCandidate:
    diff_key: str
    discipline: str
    confidence: float
    reason: str


@dataclass(frozen=True)
class DisciplineResponse:
    schema_version: str
    candidates: tuple[DisciplineCandidate, ...]


@dataclass(frozen=True)
class ValidationOutcome:
    """校验结果。``ok=False`` 时 ``error_code`` 为分类错误码，调用方应回退。"""

    ok: bool
    capability: str
    data: Any = None            # 成功时为对应的 *Response 对象
    error_code: str = ""
    error_message: str = ""


# ---------------------------------------------------------------------------
# 内部校验辅助
# ---------------------------------------------------------------------------


def _parse_json_object(text: str) -> dict[str, Any]:
    """把 repair 后的字符串严格解析为 JSON 对象。

    非法 JSON 或非对象顶层结构一律作为 ``llm_schema_invalid`` 拒绝。错误消息不
    回显响应正文。
    """

    try:
        obj = json.loads(text)
    except Exception:  # noqa: BLE001 - 不放响应正文到消息
        raise SchemaValidationError(
            ERROR_SCHEMA_INVALID, "响应不是合法 JSON"
        ) from None
    if not isinstance(obj, dict):
        raise SchemaValidationError(
            ERROR_SCHEMA_INVALID, "响应顶层不是 JSON 对象"
        )
    return obj


def _require_schema_version(obj: Mapping[str, Any], expected: str) -> str:
    version = obj.get("schema_version")
    if not isinstance(version, str) or not version:
        raise SchemaValidationError(
            ERROR_SCHEMA_INVALID, "缺少 schema_version"
        )
    if version != expected:
        raise SchemaValidationError(
            ERROR_SCHEMA_INVALID,
            f"schema_version 不匹配: 期望 {expected!r}",
        )
    return version


def _reject_verdict_keys(obj: Any, *, where: str) -> None:
    """递归拒绝任何自动 verdict / 决策 / 路由字段。"""

    if isinstance(obj, Mapping):
        for key, value in obj.items():
            name = str(key).strip().lower()
            if name in FORBIDDEN_VERDICT_KEYS:
                raise SchemaValidationError(
                    ERROR_SAFETY_REJECTED,
                    f"{where} 含被禁的自动决策字段: {name!r}",
                )
            _reject_verdict_keys(value, where=where)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            _reject_verdict_keys(item, where=where)


def _require_exact_keys(
    row: Mapping[str, Any], *, required: frozenset[str], where: str
) -> None:
    """要求字段集合与 ``required`` **完全一致**：既不缺必需字段，也不含未知字段。"""

    keys = {str(k) for k in row.keys()}
    missing = required - keys
    if missing:
        raise SchemaValidationError(
            ERROR_SCHEMA_INVALID,
            f"{where} 缺少必需字段: {sorted(missing)}",
        )
    unknown = keys - required
    if unknown:
        raise SchemaValidationError(
            ERROR_SCHEMA_INVALID,
            f"{where} 含未知字段: {sorted(unknown)}",
        )


def _as_int_index(value: Any, *, where: str) -> int:
    # 严格拒绝 bool（bool 是 int 子类）与非整数。
    if isinstance(value, bool) or not isinstance(value, int):
        raise SchemaValidationError(
            ERROR_SCHEMA_INVALID, f"{where} 索引必须是整数"
        )
    return value


def _as_confidence(value: Any, *, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchemaValidationError(
            ERROR_SCHEMA_INVALID, f"{where} confidence 必须是数值"
        )
    conf = float(value)
    if conf < 0.0 or conf > 1.0:
        raise SchemaValidationError(
            ERROR_SAFETY_REJECTED,
            f"{where} confidence 越界 [0,1]",
        )
    return conf


def _as_bounded_str(value: Any, *, where: str, max_chars: int) -> str:
    if not isinstance(value, str):
        raise SchemaValidationError(
            ERROR_SCHEMA_INVALID, f"{where} 必须是字符串"
        )
    if len(value) > max_chars:
        raise SchemaValidationError(
            ERROR_SAFETY_REJECTED,
            f"{where} 文本超过上限 {max_chars} 字符",
        )
    return value


def _require_list(obj: Mapping[str, Any], key: str) -> list[Any]:
    value = obj.get(key)
    if not isinstance(value, list):
        raise SchemaValidationError(
            ERROR_SCHEMA_INVALID, f"字段 {key!r} 必须是数组"
        )
    return value


# ---------------------------------------------------------------------------
# 每能力的严格校验
# ---------------------------------------------------------------------------

_CANDIDATE_PAIR_FIELDS = frozenset(
    {"cert_index", "draft_index", "confidence", "reason"}
)
_EXPLANATION_FIELDS = frozenset({"diff_key", "explanation", "risk"})
_DISCIPLINE_FIELDS = frozenset({"diff_key", "discipline", "confidence", "reason"})

# 顶层只允许出现的键（除 schema_version 外）。
_CANDIDATE_TOP_KEYS = frozenset({"schema_version", "pairs"})
_EXPLAIN_TOP_KEYS = frozenset({"schema_version", "explanations"})
_DISCIPLINE_TOP_KEYS = frozenset({"schema_version", "candidates"})


def _validate_top_level(
    obj: Mapping[str, Any], *, allowed: frozenset[str], where: str
) -> None:
    unknown = {str(k) for k in obj.keys()} - allowed
    if unknown:
        raise SchemaValidationError(
            ERROR_SCHEMA_INVALID,
            f"{where} 顶层含未知字段: {sorted(unknown)}",
        )


def validate_candidate_response(
    obj: Mapping[str, Any],
    context: CandidateContext,
    *,
    schema_version: str,
    max_reason_chars: int = DEFAULT_MAX_REASON_CHARS,
) -> CandidateResponse:
    """校验候选匹配响应，应用索引/同子块/同组/一对一/阈值护栏。

    同块护栏按**逻辑子块** ``block_type`` 判定（CERT/DRAFT 是独立文档，物理表号
    不可跨文档比较）。
    """

    _reject_verdict_keys(obj, where="candidate 响应")
    _require_schema_version(obj, schema_version)
    _validate_top_level(obj, allowed=_CANDIDATE_TOP_KEYS, where="candidate")

    raw_pairs = _require_list(obj, "pairs")
    pairs: list[CandidatePair] = []
    seen_cert: set[int] = set()
    seen_draft: set[int] = set()

    for i, raw in enumerate(raw_pairs):
        where = f"pairs[{i}]"
        if not isinstance(raw, Mapping):
            raise SchemaValidationError(
                ERROR_SCHEMA_INVALID, f"{where} 必须是对象"
            )
        _require_exact_keys(raw, required=_CANDIDATE_PAIR_FIELDS, where=where)

        cert_index = _as_int_index(raw["cert_index"], where=f"{where}.cert_index")
        draft_index = _as_int_index(raw["draft_index"], where=f"{where}.draft_index")
        confidence = _as_confidence(raw["confidence"], where=where)
        reason = _as_bounded_str(
            raw["reason"], where=f"{where}.reason", max_chars=max_reason_chars
        )

        # 索引越界。
        if cert_index not in context.cert_indices:
            raise SchemaValidationError(
                ERROR_SAFETY_REJECTED,
                f"{where}.cert_index 越界: {cert_index}",
            )
        if draft_index not in context.draft_indices:
            raise SchemaValidationError(
                ERROR_SAFETY_REJECTED,
                f"{where}.draft_index 越界: {draft_index}",
            )

        # 一对一：cert/draft 索引都不能重复出现。
        if cert_index in seen_cert:
            raise SchemaValidationError(
                ERROR_SAFETY_REJECTED,
                f"{where}.cert_index 重复: {cert_index}",
            )
        if draft_index in seen_draft:
            raise SchemaValidationError(
                ERROR_SAFETY_REJECTED,
                f"{where}.draft_index 重复: {draft_index}",
            )

        # 阈值：低于阈值的候选拒绝，不静默丢弃。
        if confidence < context.min_confidence:
            raise SchemaValidationError(
                ERROR_SAFETY_REJECTED,
                f"{where}.confidence 低于阈值 {context.min_confidence}",
            )

        # 同逻辑子块护栏（跨文档只比 block_type，绝不比物理表号）。
        if context.block_guard_enabled:
            cert_block = context.cert_block_type.get(cert_index)
            draft_block = context.draft_block_type.get(draft_index)
            if cert_block is None or draft_block is None or cert_block != draft_block:
                raise SchemaValidationError(
                    ERROR_SAFETY_REJECTED,
                    f"{where} 跨子块候选被拒绝",
                )

        # 同组/兼容分组护栏（分组标识必须相等，含都为空）。
        if context.same_group_only:
            cert_grp = context.cert_group.get(cert_index, "")
            draft_grp = context.draft_group.get(draft_index, "")
            if cert_grp != draft_grp:
                raise SchemaValidationError(
                    ERROR_SAFETY_REJECTED,
                    f"{where} 跨组候选被拒绝",
                )

        seen_cert.add(cert_index)
        seen_draft.add(draft_index)
        pairs.append(
            CandidatePair(
                cert_index=cert_index,
                draft_index=draft_index,
                confidence=confidence,
                reason=reason,
            )
        )

    return CandidateResponse(schema_version=schema_version, pairs=tuple(pairs))


def validate_explanation_response(
    obj: Mapping[str, Any],
    context: ExplainContext,
    *,
    schema_version: str,
) -> ExplanationResponse:
    """校验差异解释响应；只能引用已存在的确定性 diff key。"""

    _reject_verdict_keys(obj, where="explain 响应")
    _require_schema_version(obj, schema_version)
    _validate_top_level(obj, allowed=_EXPLAIN_TOP_KEYS, where="explain")

    raw_items = _require_list(obj, "explanations")
    explanations: list[Explanation] = []
    seen_keys: set[str] = set()

    for i, raw in enumerate(raw_items):
        where = f"explanations[{i}]"
        if not isinstance(raw, Mapping):
            raise SchemaValidationError(
                ERROR_SCHEMA_INVALID, f"{where} 必须是对象"
            )
        _require_exact_keys(raw, required=_EXPLANATION_FIELDS, where=where)

        diff_key = _as_bounded_str(
            raw["diff_key"], where=f"{where}.diff_key",
            max_chars=context.max_reason_chars,
        )
        explanation = _as_bounded_str(
            raw["explanation"], where=f"{where}.explanation",
            max_chars=context.max_reason_chars,
        )
        risk = _as_bounded_str(
            raw["risk"], where=f"{where}.risk",
            max_chars=context.max_reason_chars,
        )

        # 未知 diff key：拒绝（不允许模型凭空创造差异）。
        if diff_key not in context.known_diff_keys:
            raise SchemaValidationError(
                ERROR_SAFETY_REJECTED,
                f"{where}.diff_key 未知: 引用了不存在的确定性差异",
            )
        # 同一 diff key 不允许重复解释。
        if diff_key in seen_keys:
            raise SchemaValidationError(
                ERROR_SAFETY_REJECTED,
                f"{where}.diff_key 重复",
            )
        seen_keys.add(diff_key)
        explanations.append(
            Explanation(diff_key=diff_key, explanation=explanation, risk=risk)
        )

    return ExplanationResponse(
        schema_version=schema_version, explanations=tuple(explanations)
    )


def validate_discipline_response(
    obj: Mapping[str, Any],
    context: DisciplineContext,
    *,
    schema_version: str,
) -> DisciplineResponse:
    """校验专业候选响应；只产出候选，绝不写最终 discipline 或触发路由。"""

    _reject_verdict_keys(obj, where="discipline 响应")
    _require_schema_version(obj, schema_version)
    _validate_top_level(obj, allowed=_DISCIPLINE_TOP_KEYS, where="discipline")

    raw_items = _require_list(obj, "candidates")
    candidates: list[DisciplineCandidate] = []
    seen_keys: set[str] = set()

    for i, raw in enumerate(raw_items):
        where = f"candidates[{i}]"
        if not isinstance(raw, Mapping):
            raise SchemaValidationError(
                ERROR_SCHEMA_INVALID, f"{where} 必须是对象"
            )
        _require_exact_keys(raw, required=_DISCIPLINE_FIELDS, where=where)

        diff_key = _as_bounded_str(
            raw["diff_key"], where=f"{where}.diff_key",
            max_chars=context.max_reason_chars,
        )
        discipline = _as_bounded_str(
            raw["discipline"], where=f"{where}.discipline",
            max_chars=context.max_reason_chars,
        )
        confidence = _as_confidence(raw["confidence"], where=where)
        reason = _as_bounded_str(
            raw["reason"], where=f"{where}.reason",
            max_chars=context.max_reason_chars,
        )

        if diff_key not in context.known_diff_keys:
            raise SchemaValidationError(
                ERROR_SAFETY_REJECTED,
                f"{where}.diff_key 未知: 引用了不存在的确定性差异",
            )
        # 非允许专业：拒绝（无已发布规则时 allowed_disciplines 为空，全部拒绝）。
        if discipline not in context.allowed_disciplines:
            raise SchemaValidationError(
                ERROR_SAFETY_REJECTED,
                f"{where}.discipline 非允许专业",
            )
        if confidence < context.min_confidence:
            raise SchemaValidationError(
                ERROR_SAFETY_REJECTED,
                f"{where}.confidence 低于阈值 {context.min_confidence}",
            )
        if diff_key in seen_keys:
            raise SchemaValidationError(
                ERROR_SAFETY_REJECTED,
                f"{where}.diff_key 重复",
            )
        seen_keys.add(diff_key)
        candidates.append(
            DisciplineCandidate(
                diff_key=diff_key,
                discipline=discipline,
                confidence=confidence,
                reason=reason,
            )
        )

    return DisciplineResponse(
        schema_version=schema_version, candidates=tuple(candidates)
    )


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------


def validate_response(
    capability: str,
    repaired_text: str,
    context: CandidateContext | ExplainContext | DisciplineContext,
    *,
    schema_version: str,
    max_reason_chars: int = DEFAULT_MAX_REASON_CHARS,
) -> ValidationOutcome:
    """对 repair 后的字符串执行严格 Schema + 安全校验。

    ``repaired_text`` 是任务 1.3 ``repair_json`` 的输出（语法层已修复）。本函数
    在其之上做严格业务校验；任何失败都返回 ``ok=False`` 的
    :class:`ValidationOutcome`（带分类错误码），供调用方回退到确定性证据。

    ``context`` 的类型必须与 ``capability`` 匹配：

    - ``candidate`` -> :class:`CandidateContext`
    - ``explain``   -> :class:`ExplainContext`
    - ``discipline`` -> :class:`DisciplineContext`
    """

    if capability not in ALL_CAPABILITIES:
        return ValidationOutcome(
            ok=False,
            capability=capability,
            error_code=ERROR_SCHEMA_INVALID,
            error_message=f"未知 capability: {capability!r}",
        )

    try:
        obj = _parse_json_object(repaired_text)

        if capability == CAPABILITY_CANDIDATE:
            if not isinstance(context, CandidateContext):
                raise SchemaValidationError(
                    ERROR_SCHEMA_INVALID,
                    "candidate 能力需要 CandidateContext",
                )
            data: Any = validate_candidate_response(
                obj, context,
                schema_version=schema_version,
                max_reason_chars=max_reason_chars,
            )
        elif capability == CAPABILITY_EXPLAIN:
            if not isinstance(context, ExplainContext):
                raise SchemaValidationError(
                    ERROR_SCHEMA_INVALID,
                    "explain 能力需要 ExplainContext",
                )
            data = validate_explanation_response(
                obj, context, schema_version=schema_version
            )
        else:  # CAPABILITY_DISCIPLINE
            if not isinstance(context, DisciplineContext):
                raise SchemaValidationError(
                    ERROR_SCHEMA_INVALID,
                    "discipline 能力需要 DisciplineContext",
                )
            data = validate_discipline_response(
                obj, context, schema_version=schema_version
            )
    except SchemaValidationError as exc:
        return ValidationOutcome(
            ok=False,
            capability=capability,
            error_code=exc.code,
            error_message=exc.message,
        )

    return ValidationOutcome(ok=True, capability=capability, data=data)
