"""ReportVerify 的独立数据模型。

模型不依赖 CertAgent 的旧 orig/plm 语义，明确区分 CERT（应然）和
DRAFT（实然），并让所有批注锚点只指向 DRAFT。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Anchor:
    """报告草稿中的 1-based 表/行/列位置。"""

    table_idx: int
    row_idx: int
    cell_idx: int
    para_hint: str = ""


@dataclass
class DocumentRow:
    """一个目标子块中的结构化行，同时保留写回批注所需的锚点。"""

    block_type: str
    row_idx: int
    values: dict[str, str] = field(default_factory=dict)
    anchors: dict[str, Anchor] = field(default_factory=dict)
    raw_cells: list[str] = field(default_factory=list)
    source_table: int = 0
    group: str = ""

    @property
    def item_name(self) -> str:
        return self.values.get("关键件名称", "") or self.values.get("项目", "")


@dataclass
class LocatedBlock:
    """认证资料或报告草稿中的一个被识别子块。"""

    block_type: str
    table_idx: int
    header: list[str] = field(default_factory=list)
    rows: list[DocumentRow] = field(default_factory=list)
    recognized: bool = True
    note: str = ""


@dataclass
class UnrecognizedTable:
    table_idx: int
    rows: int
    columns: int
    preview: str
    reason: str = "未命中目标子块表头指纹"


@dataclass
class VerifyDiff:
    """一个字段级差异；cert_value 永远是应然值。"""

    key: str
    block_type: str
    item_name: str
    diff_type: str
    field: str
    cert_value: str = ""
    draft_value: str = ""
    cert_location: str = ""
    draft_anchor: Anchor | None = None
    discipline: str | None = None
    discipline_status: str = "discipline_pending"
    rule_version: str | None = None
    comment_written: bool = False
    comment_error: str = ""
    review_status: str = "unreviewed"
    review_note: str = ""
    reviewed_by: str = ""
    match_confidence: float = 1.0
    match_reason: str = ""
    match_status: str = "matched"
    row_key: str = ""


@dataclass
class RowDiff:
    """一行的双侧对比结果；字段级差异仍由 diff_keys 指向 VerifyDiff。"""

    row_key: str
    block_type: str
    row_status: str
    row_kind: str = "row"
    item_name: str = ""
    cert_row: dict[str, str] = field(default_factory=dict)
    draft_row: dict[str, str] = field(default_factory=dict)
    cert_row_ref: dict[str, Any] = field(default_factory=dict)
    draft_row_ref: dict[str, Any] = field(default_factory=dict)
    changed_fields: list[str] = field(default_factory=list)
    diff_keys: list[str] = field(default_factory=list)
    match_confidence: float = 1.0
    match_reason: str = ""
    match_status: str = "matched"


@dataclass
class VerifyResult:
    cert_blocks: list[LocatedBlock] = field(default_factory=list)
    draft_blocks: list[LocatedBlock] = field(default_factory=list)
    unrecognized_cert_tables: list[UnrecognizedTable] = field(default_factory=list)
    diffs: list[VerifyDiff] = field(default_factory=list)
    row_diffs: list[RowDiff] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    rule_version: str = "normalized-v2"


def _jsonable(value: Any) -> Any:
    if isinstance(value, Anchor):
        return asdict(value)
    if isinstance(value, (DocumentRow, LocatedBlock, UnrecognizedTable, VerifyDiff, RowDiff, VerifyResult)):
        return {k: _jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def to_dict(value: Any) -> dict[str, Any] | list[Any] | Any:
    """把模型转为可直接 json.dumps 的普通对象。"""
    return _jsonable(value)
