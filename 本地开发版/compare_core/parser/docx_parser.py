"""纯 python-docx 解析 .docx（无 Word COM，线程安全）。

从 parser test0727/docx_route.py 迁移而来，作为 Word COM 的替代路径：
- 解析 .docx 表格为 Row 列表
- 处理横向合并（gridSpan）、纵向合并（vMerge）、跨行填充、分组标题
- 完全纯 Python，可在 Web 异步线程/子进程里安全调用

用法：
    from compare_core.parser.docx_parser import parse_docx
    rows = parse_docx("path/to/file.docx")
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..models import Row
from .doc_parser import HEADER_MAP

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_CARRY = ["序号", "关键件名称"]


def _clean(value: Any) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ")
    return _CTRL.sub("", text).strip()


def _field_for_header(value: str) -> str | None:
    """表头文本 → 统一字段名（含全角括号归一 + 规格别名）。"""
    text = _clean(value).replace("（", "(").replace("）", ")")
    direct = HEADER_MAP.get(text)
    if direct:
        return direct
    compact = "".join(text.split())
    if compact == "规格":
        return "规格材料"
    for header, field in HEADER_MAP.items():
        normalized = header.replace("（", "(").replace("）", ")")
        if "".join(normalized.split()) == compact:
            return field
    return None


def _span(tc: Any) -> int:
    try:
        value = tc.tcPr.gridSpan.val
        return max(int(value), 1) if value else 1
    except Exception:
        return 1


def _is_vertical_merge(tc: Any) -> bool:
    try:
        return tc.tcPr.vMerge is not None
    except Exception:
        return False


def _xml_cells(row: Any, table: Any) -> list[tuple[int, str, int, bool]]:
    """返回 (逻辑起始列号, 文本, gridSpan, 是否纵向合并)。"""
    from docx.table import _Cell

    cells: list[tuple[int, str, int, bool]] = []
    column = 1
    for tc in row._tr.tc_lst:
        span = _span(tc)
        # CT_Tc.text 在新版 python-docx 里为 None；用 _Cell 取段落文本
        cells.append((column, _clean(_Cell(tc, table).text), span, _is_vertical_merge(tc)))
        column += span
    return cells


def _header_map(cells: list[tuple[int, str, int, bool]]) -> dict[int, str]:
    return {
        column: field
        for column, text, _span_value, _vertical in cells
        if (field := _field_for_header(text))
    }


def _parse_table(table: Any, table_no: int) -> list[Row]:
    rows: list[Row] = []
    if not table.rows:
        return rows

    header_cells = _xml_cells(table.rows[0], table)
    col_map = _header_map(header_cells)
    header_max = max((c for c, _t, _s, _v in header_cells), default=0)
    model_ci = next((ci for ci, field in col_map.items() if field == "型号"), None)
    merge_point = model_ci + 1 if model_ci is not None else None
    carry: dict[str, str] = {}
    merged_values: dict[str, str] = {}

    def field_for(column: int, row_max: int) -> str | None:
        if merge_point and header_max and row_max < header_max and column >= merge_point:
            direct = col_map.get(column + 1)
            if direct:
                return direct
        direct = col_map.get(column)
        if direct:
            return direct
        # 转换后某些合并行单元格起始列落在两个表头列之间，归到右侧最近表头
        for header_column in sorted(col_map):
            if header_column > column:
                return col_map[header_column]
        return None

    for row_index, word_row in enumerate(table.rows[1:], start=2):
        cells = _xml_cells(word_row, table)
        non_empty = [text for _c, text, _s, _v in cells if text]
        # 分组标题行：整行一个跨列合并单元格
        if len(cells) == 1 and non_empty:
            carry["group"] = non_empty[0]
            continue
        if not non_empty:
            continue

        row_max = max((c for c, _t, _s, _v in cells), default=0)
        data: dict[str, Any] = {"table": table_no, "group": carry.get("group", ""), "row_index": row_index}
        raw: dict[str, str] = {}
        for column, text, _span_value, vertical in cells:
            raw[str(column)] = text
            field = field_for(column, row_max)
            if not field:
                continue
            if text:
                data[field] = text
                if vertical:
                    merged_values[field] = text
            elif vertical and field in merged_values:
                # python-docx 对 vMerge 续行返回空；用记录的合并值恢复
                data[field] = merged_values[field]
        # 表1 证书号来自"备注"列
        if table_no == 1 and data.get("备注"):
            data["证书号"] = data["备注"]
        # 跨行填充
        for field in _CARRY:
            if not data.get(field):
                data[field] = carry.get(field, "")
            else:
                carry[field] = data[field]
        data["raw"] = raw
        rows.append(Row(**{k: v for k, v in data.items() if k in Row.model_fields or k == "raw"}))
    return rows


def parse_docx(path: str) -> list[Row]:
    """解析 .docx 所有表格为 Row 列表（纯 python-docx，无 COM）。"""
    from docx import Document

    document = Document(str(Path(path).resolve()))
    rows: list[Row] = []
    for table_no, table in enumerate(document.tables, start=1):
        rows.extend(_parse_table(table, table_no))
    return rows
