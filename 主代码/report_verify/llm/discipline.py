"""ReportVerify 的专业候选数据结构与生成入口（任务 2.3）。

本模块承接 design.md 的 ``Explanation and discipline algorithm`` 与 Data Models：
在确定性 ``compare_blocks`` 之后，仅**读取差异的 block/field/item 元数据和“已发布
规则摘要”**，产出**候选专业、理由、置信度**，供人工待确认展示。

强不变量（与 design.md / requirements 3.3、7.1、7.4 一致，且必须由本模块保证）：

- **LLM 的 ``discipline`` 字符串绝不写入最终 ``VerifyDiff.discipline`` 字段。**
  本模块只产出附属候选元数据（``DisciplineSuggestion``），不修改传入的
  ``VerifyResult`` / ``VerifyDiff`` 的任何字段。
- **所有 ``VerifyDiff.discipline_status`` 保持 ``discipline_pending``。** 本模块不写、
  不改 ``discipline_status``；不触发任何路由、审批或外部流程（KOA/Tims）。
- **无已发布规则、或规则版本未确认时，直接 ``skipped_policy``**，返回空候选，且
  不发起任何 provider 调用。
- 候选只作展示/待确认元数据，统一标 ``source="llm"``、``status="pending"``。
- 任何 provider/schema/安全失败都回退到确定性证据，并给出明确 ``status``，不静默
  变成“无差异”。

安全：本模块不接触凭据、不记录 prompt/response 原文或 CERT/DRAFT 字段原文；只读取
差异的结构化元数据（block/field/item/diff_key）和已发布规则摘要（专业 allowlist 与
版本号）。校验复用 :mod:`report_verify.llm.schemas`，不重复实现校验逻辑。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from .config import LLMSettings
from .schemas import (
    CAPABILITY_DISCIPLINE,
    DEFAULT_MAX_REASON_CHARS,
    DisciplineContext,
    DisciplineResponse,
    ValidationOutcome,
    validate_response,
)

# 候选来源与状态常量：候选永远是待人工确认的 LLM 建议，不是结论。
CANDIDATE_SOURCE_LLM = "llm"
CANDIDATE_STATUS_PENDING = "pending"

# design.md Error Handling / orchestrator 的状态码。
STATUS_DISABLED = "disabled"            # mode 未开启 discipline 能力
STATUS_SKIPPED_POLICY = "skipped_policy"  # 无已发布规则 / 规则版本未确认
STATUS_SUCCESS = "success"              # 产出候选（可能为空列表）
STATUS_FALLBACK = "fallback"           # provider/网络失败回退
STATUS_INVALID = "invalid"             # schema / 安全校验失败回退

# 本模块**绝不**触碰的最终字段名；用于自检与文档化不变量。
FINAL_DISCIPLINE_FIELD = "discipline"
PENDING_DISCIPLINE_STATUS = "discipline_pending"


@dataclass(frozen=True)
class PublishedDisciplineRules:
    """已发布的专业路由规则摘要（由调用方提供，不在此读取文件或规则库）。

    - ``allowed_disciplines``：已发布规则允许的专业集合。为空表示当前无可用专业
      规则；此时任何专业候选都不成立，生成入口返回 ``skipped_policy``。
    - ``version``：规则版本号。为空/``None`` 表示规则版本未确认，同样按
      ``skipped_policy`` 处理（design.md：无规则或规则版本未确认直接 skipped）。
    - ``confirmed``：版本是否已确认；默认要求已确认。
    """

    allowed_disciplines: frozenset[str] = field(default_factory=frozenset)
    version: str | None = None
    confirmed: bool = True

    @property
    def is_published(self) -> bool:
        """是否存在可用的已发布规则（有专业集合且版本已确认）。"""

        return bool(self.allowed_disciplines) and bool(self.version) and self.confirmed


@dataclass(frozen=True)
class DisciplineSuggestion:
    """一条专业候选的**待确认展示元数据**。

    这是附属证据，不是结论：``source`` 固定 ``llm``、``status`` 固定 ``pending``。
    它绝不会被写入 ``VerifyDiff.discipline``，也不改变 ``discipline_status``。
    """

    diff_key: str
    candidate_discipline: str
    reason: str
    confidence: float
    source: str = CANDIDATE_SOURCE_LLM
    status: str = CANDIDATE_STATUS_PENDING
    rule_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "diff_key": self.diff_key,
            "candidate_discipline": self.candidate_discipline,
            "reason": self.reason,
            "confidence": self.confidence,
            "source": self.source,
            "status": self.status,
            "rule_version": self.rule_version,
        }


@dataclass(frozen=True)
class DisciplineSuggestionSet:
    """专业候选生成结果。

    - ``status``：disabled / skipped_policy / success / fallback / invalid。
    - ``suggestions``：仅当 ``status == success`` 时可能非空；其余状态恒为空。
    - ``metadata``：脱敏元数据（状态、规则版本、候选数、可选 provider 调用摘要），
      绝不含 prompt/response 原文或凭据。
    - ``discipline_status_unchanged``：显式声明本次未改变任何 discipline_status，
      恒为 ``True``（本模块从不写该字段）。
    """

    status: str
    suggestions: tuple[DisciplineSuggestion, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    discipline_status_unchanged: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "suggestions": [s.to_dict() for s in self.suggestions],
            "metadata": dict(self.metadata),
            "discipline_status_unchanged": self.discipline_status_unchanged,
        }


# LLM 原始调用回调：给定 (capability, 差异元数据摘要, 规则摘要) 返回 repair 之后的
# 字符串（即任务 1.3 client.complete_raw + repair_json 的输出）。生成入口只负责编排
# 与安全校验，不在此实现 HTTP/SSE。测试可注入本地 stub，不访问真实 provider。
DisciplineRawCaller = Callable[[Sequence[Mapping[str, Any]], PublishedDisciplineRules], str]


def _diff_metadata(diff: Any) -> dict[str, Any]:
    """只提取差异的 block/field/item 元数据与 diff_key，不含 CERT/DRAFT 原文值。

    ``diff`` 是 :class:`report_verify.models.VerifyDiff`；这里用属性读取以避免与
    models 形成硬导入耦合（本模块只读元数据）。
    """

    return {
        "diff_key": getattr(diff, "key", ""),
        "block_type": getattr(diff, "block_type", ""),
        "field": getattr(diff, "field", ""),
        "item_name": getattr(diff, "item_name", ""),
        "diff_type": getattr(diff, "diff_type", ""),
    }


def _collect_diffs(result: Any) -> list[Any]:
    diffs = getattr(result, "diffs", None)
    if diffs is None:
        return []
    return list(diffs)


def _discipline_enabled(settings: LLMSettings) -> bool:
    """discipline 能力是否在当前 mode 下启用。

    design.md 的 mode allowlist 中 discipline 建议随 explain 能力开放（专业候选是
    对已存在差异的解释性建议）。因此 ``explain`` 与 ``candidate_explain`` 视为启用；
    ``off`` 与纯 ``candidate`` 不启用。
    """

    return settings.mode in ("explain", "candidate_explain")


def generate_discipline_suggestions(
    result: Any,
    rules: PublishedDisciplineRules,
    *,
    settings: LLMSettings,
    caller: DisciplineRawCaller | None = None,
    trace_id: str = "",
    min_confidence: float = 0.0,
    max_reason_chars: int = DEFAULT_MAX_REASON_CHARS,
) -> DisciplineSuggestionSet:
    """在确定性差异之上生成专业候选（只读元数据，不写最终字段）。

    编排（与 design.md orchestrator 第 4 步一致）：

    1. mode 未启用 discipline -> ``disabled``，不调用 provider；
    2. 无已发布规则或规则版本未确认 -> ``skipped_policy``，不调用 provider，且所有
       ``VerifyDiff.discipline_status`` 保持 ``discipline_pending``；
    3. 无 caller（未接入 client）-> ``skipped_policy``（没有可用建议来源，回退到
       确定性证据，不触发任何路由）；
    4. 有规则且有 caller -> 调用一次 provider，用 :mod:`schemas` 严格校验；
       - 校验通过：产出候选（``success``），全部标 ``source=llm``、``status=pending``，
         并附带规则版本；
       - provider 失败：``fallback``；schema/安全失败：``invalid``；均返回空候选。

    本函数**绝不**修改 ``result`` / ``VerifyDiff``：不写 ``discipline``、不改
    ``discipline_status``、不触发路由/审批。
    """

    schema_version = settings.response_schema_version

    # 1) 能力未启用。
    if not _discipline_enabled(settings):
        return DisciplineSuggestionSet(
            status=STATUS_DISABLED,
            metadata={
                "reason": "mode 未开启 discipline 能力",
                "mode": settings.mode,
                "trace_id": trace_id,
            },
        )

    # 2) 无已发布规则 / 版本未确认：直接 skipped_policy，不触发任何流程。
    if not rules.is_published:
        return DisciplineSuggestionSet(
            status=STATUS_SKIPPED_POLICY,
            metadata={
                "reason": "无已发布专业规则或规则版本未确认",
                "rule_version": rules.version,
                "rule_confirmed": rules.confirmed,
                "allowed_disciplines_count": len(rules.allowed_disciplines),
                "trace_id": trace_id,
            },
        )

    diffs = _collect_diffs(result)
    known_diff_keys = frozenset(
        getattr(d, "key", "") for d in diffs if getattr(d, "key", "")
    )

    # 3) 没有可用建议来源（未接入 client）：回退，不产出候选，不触发路由。
    if caller is None:
        return DisciplineSuggestionSet(
            status=STATUS_SKIPPED_POLICY,
            metadata={
                "reason": "未提供 provider 调用入口（未接入 LLM client）",
                "rule_version": rules.version,
                "known_diff_keys": len(known_diff_keys),
                "trace_id": trace_id,
            },
        )

    diff_meta = [_diff_metadata(d) for d in diffs]

    # 4) 调用 provider（一次），任何异常都回退为 fallback，不抛给上层。
    try:
        repaired_text = caller(diff_meta, rules)
    except Exception as exc:  # noqa: BLE001 - 只保留类型名，不泄露正文/凭据
        return DisciplineSuggestionSet(
            status=STATUS_FALLBACK,
            metadata={
                "reason": "provider 调用失败，回退到确定性证据",
                "error_type": type(exc).__name__,
                "error_code": getattr(exc, "code", ""),
                "rule_version": rules.version,
                "trace_id": trace_id,
            },
        )

    # 严格校验（复用 schemas；非允许专业 / 未知 diff key / 越界 confidence 等均拒绝）。
    context = DisciplineContext(
        known_diff_keys=known_diff_keys,
        allowed_disciplines=rules.allowed_disciplines,
        max_reason_chars=max_reason_chars,
        min_confidence=min_confidence,
    )
    outcome: ValidationOutcome = validate_response(
        CAPABILITY_DISCIPLINE,
        repaired_text,
        context,
        schema_version=schema_version,
        max_reason_chars=max_reason_chars,
    )

    if not outcome.ok:
        return DisciplineSuggestionSet(
            status=STATUS_INVALID,
            metadata={
                "reason": "schema/安全校验失败，不采纳输出",
                "error_code": outcome.error_code,
                "error_message": outcome.error_message,
                "rule_version": rules.version,
                "trace_id": trace_id,
            },
        )

    response: DisciplineResponse = outcome.data
    suggestions = tuple(
        DisciplineSuggestion(
            diff_key=c.diff_key,
            candidate_discipline=c.discipline,
            reason=c.reason,
            confidence=c.confidence,
            source=CANDIDATE_SOURCE_LLM,
            status=CANDIDATE_STATUS_PENDING,
            rule_version=rules.version,
        )
        for c in response.candidates
    )

    return DisciplineSuggestionSet(
        status=STATUS_SUCCESS,
        suggestions=suggestions,
        metadata={
            "rule_version": rules.version,
            "candidate_count": len(suggestions),
            "schema_version": response.schema_version,
            "trace_id": trace_id,
        },
    )
