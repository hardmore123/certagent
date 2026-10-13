"""基于 python-docx 的表格解析。

底层表格遍历沿用 list-merge-demo 的 grid/table 思路，但这里保留
CERT/DRAFT 目标块和 DRAFT 批注锚点，避免复用旧 Row 的 orig/plm 语义。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from docx import Document

from .field_map import (
    PLACEHOLDER_VALUES,
    canonical_header,
    clean_text,
    normalize_for_compare,
)
from .models import Anchor, DocumentRow, LocatedBlock, UnrecognizedTable

_DUP_SUFFIX = re.compile(r"^(.*)__\d+$")


def _base_field(field: str) -> str:
    """去掉 _unique_fields 追加的 __2/__3 后缀，得到基础字段名。"""
    match = _DUP_SUFFIX.match(field)
    return match.group(1) if match else field


def _consolidate_duplicate_fields(
    values: dict[str, str], anchors: dict[str, Anchor]
) -> None:
    """重复表头列（如 认证标准 + 认证标准__2）合并到基础字段。

    某些 CERT 表把两列都命名成同一表头（如两列“认证标准”），而源表
    的横向合并会让相邻列（生产企业等）的公司名溢出到第一个重复列，
    真正的值落在 __2 列。这里跳过与本行其他字段重复的“合并溢出值”和
    占位符，选出真正属于该基础字段的值回填基础字段用于比较。

    - 只对同一基础字段出现 ≥2 列的情况生效；正常行完全不变。
    - 只改基础字段（认证标准/位号 等）的比较取值；__2 列原样保留供追溯。
    - 不改 raw_cells，不改展示原文。
    """
    groups: dict[str, list[str]] = {}
    for field in list(values.keys()):
        groups.setdefault(_base_field(field), []).append(field)
    for base, cols in groups.items():
        if len(cols) < 2:
            continue
        # 本行其他基础字段的归一值集合（用于识别溢出：认证标准==制造商/生产企业）
        others = {
            normalize_for_compare(values[f])
            for f in values
            if _base_field(f) != base and values.get(f)
        }
        ordered = sorted(cols, key=lambda f: (f != base, f))  # base 优先，其后 __2、__3…
        chosen = None
        for f in ordered:
            nv = normalize_for_compare(values.get(f, ""))
            if nv and nv not in PLACEHOLDER_VALUES and nv not in others:
                chosen = f
                break
        if chosen is None:  # 全是占位符/溢出，退回第一个非空
            for f in ordered:
                if (values.get(f, "") or "").strip():
                    chosen = f
                    break
        if chosen and chosen != base:
            values[base] = values[chosen]
            if chosen in anchors:
                anchors[base] = anchors[chosen]


def _table_preview(table) -> str:
    values = []
    for row in table.rows[:2]:
        values.append(" | ".join(clean_text(cell.text).replace("\n", " ") for cell in row.cells))
    return " / ".join(values)[:500]


def _headers(table) -> list[str]:
    if not table.rows:
        return []
    return [clean_text(cell.text) for cell in table.rows[0].cells]


def _unique_fields(headers: list[str]) -> list[str | None]:
    """表头转统一字段；重复列保留为 field__2，避免静默覆盖。"""
    seen: dict[str, int] = {}
    result: list[str | None] = []
    for header in headers:
        field = canonical_header(header)
        if field is None:
            result.append(None)
            continue
        seen[field] = seen.get(field, 0) + 1
        result.append(field if seen[field] == 1 else f"{field}__{seen[field]}")
    return result


def classify_headers(headers: list[str], first_rows: list[list[str]] | None = None) -> str | None:
    """按表头指纹分类目标子块，不把照片/声明表误识别为清单。"""
    canonical = {canonical_header(h) for h in headers}
    canonical.discard(None)
    if {"项目", "变更前", "变更后"}.issubset(canonical):
        return "change_confirmation"
    # 产品描述表的标题不一定是列名，而是第一行的合并标题。
    first_preview = " ".join((first_rows or [[]])[0]) if first_rows else ""
    if "产品描述报告" in first_preview:
        return "product_description"
    # “本次使用/备用”是 EMC 清单的强指纹。DRAFT 的 EMC 表可能同时
    # 带有生产企业列，不能再用“有生产企业”把它排除；必须优先于安全清单判断。
    if {"关键件名称", "型号"}.issubset(canonical) and "本次使用" in canonical:
        return "emc_list"
    if {"关键件名称", "型号", "认证标准"}.issubset(canonical):
        return "safety_list"
    if {"关键件名称", "型号"}.issubset(canonical) and (
        "生产企业" in canonical or "备注" in canonical
    ):
        return "safety_list"
    return None


def _data_rows(table, block_type: str, table_idx: int) -> list[DocumentRow]:
    if not table.rows:
        return []
    headers = [clean_text(cell.text) for cell in table.rows[0].cells]
    fields = _unique_fields(headers)
    rows: list[DocumentRow] = []
    carry: dict[str, str] = {}
    current_group = ""
    # 与 CertAgent parser 的 carry 语义一致：纵向合并的序号/名称续行
    # 不再被解析成空身份；分组标题只更新上下文，不生成数据行。
    carry_fields = ("序号", "关键件名称")
    for row_idx, row in enumerate(table.rows[1:], start=2):
        raw = [clean_text(cell.text) for cell in row.cells]
        if not any(raw):
            continue
        if len(raw) > 1 and len(set(raw)) == 1 and raw[0]:
            current_group = raw[0]
            continue
        values: dict[str, str] = {}
        anchors: dict[str, Anchor] = {}
        for cell_idx, text in enumerate(raw):
            if cell_idx >= len(fields):
                continue
            field = fields[cell_idx]
            if not field:
                continue
            values[field] = text
            anchors[field] = Anchor(table_idx, row_idx, cell_idx, text[:80])
        for field in carry_fields:
            if not values.get(field) and carry.get(field):
                values[field] = carry[field]
                # 续行批注锚点仍指向当前行；不回写到原合并起点。
                anchor = anchors.get(field)
                if anchor is None:
                    anchor = Anchor(table_idx, row_idx, 0, values[field][:80])
                anchors[field] = anchor
            elif values.get(field):
                carry[field] = values[field]
        _consolidate_duplicate_fields(values, anchors)
        if block_type == "safety_list" and values.get("备注") and not values.get("证书号"):
            values["证书号"] = values["备注"]
            anchors["证书号"] = anchors.get("备注")
        rows.append(DocumentRow(
            block_type=block_type,
            row_idx=row_idx,
            values=values,
            anchors=anchors,
            raw_cells=raw,
            source_table=table_idx,
            group=current_group,
        ))
    return rows


def _parse_product_table(table, table_idx: int) -> LocatedBlock:
    rows: list[DocumentRow] = []
    for row_idx, row in enumerate(table.rows[1:], start=2):
        raw = [clean_text(cell.text) for cell in row.cells]
        if not any(raw):
            continue
        key = raw[0].rstrip("：:").strip() if raw else ""
        if not key:
            key = f"第{row_idx}行"
        value = " | ".join(raw[1:]).strip()
        rows.append(DocumentRow(
            block_type="product_description",
            row_idx=row_idx,
            values={"项目": key, "值": value},
            anchors={
                "项目": Anchor(table_idx, row_idx, 0, key[:80]),
                "值": Anchor(table_idx, row_idx, min(1, len(raw) - 1), value[:80]),
            },
            raw_cells=raw,
            source_table=table_idx,
        ))
    return LocatedBlock(
        block_type="product_description", table_idx=table_idx,
        header=_headers(table), rows=rows,
    )


def parse_target_tables(path: str, *, role: str) -> tuple[list[LocatedBlock], list[UnrecognizedTable]]:
    """解析文档内所有表格，返回目标块和显式未识别表元数据。"""
    document = Document(str(Path(path).resolve()))
    blocks: list[LocatedBlock] = []
    unrecognized: list[UnrecognizedTable] = []
    for table_idx, table in enumerate(document.tables, start=1):
        headers = _headers(table)
        preview_rows = [[clean_text(cell.text) for cell in row.cells] for row in table.rows[:2]]
        block_type = classify_headers(headers, preview_rows)
        if block_type == "product_description":
            blocks.append(_parse_product_table(table, table_idx))
            continue
        if block_type:
            blocks.append(LocatedBlock(
                block_type=block_type,
                table_idx=table_idx,
                header=headers,
                rows=_data_rows(table, block_type, table_idx),
            ))
            continue
        unrecognized.append(UnrecognizedTable(
            table_idx=table_idx,
            rows=len(table.rows),
            columns=max((len(row.cells) for row in table.rows), default=0),
            preview=_table_preview(table),
        ))
    return blocks, unrecognized


def iter_target_rows(blocks: Iterable[LocatedBlock], block_type: str) -> list[DocumentRow]:
    return [row for block in blocks if block.block_type == block_type for row in block.rows]
