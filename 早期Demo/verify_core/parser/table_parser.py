"""纯 python-docx 表格解析（无 COM，线程安全）。

改编自 list-merge-demo/compare_core/parser/docx_parser.py，关键增强：
- 解析结果保留 doc_table_index（物理表序号）与 row_index（物理行号），
  供 comment_writer 把差异**批注回 B 文档原位**。
- 表头指纹判定：只有"关键件清单"类表才会被解析成 Row。
"""
from __future__ import annotations

import re
from typing import Any

from ..models import Row

# 表头别名 -> 统一字段
HEADER_MAP = {
    "序号": "序号",
    "位号": "位号",
    "部件号": "位号",
    "元件": "位号",
    "关键件名称": "关键件名称",
    "名称": "关键件名称",
    "型号": "型号",
    "规格/材料": "规格材料",
    "规格材料": "规格材料",
    "生产者(制造商)": "制造商",
    "生产者 (制造商)": "制造商",
    "制造商 (全称)": "制造商",
    "制造商(全称)": "制造商",
    "制造商": "制造商",
    "生产企业": "生产企业",
    "生产厂(全称)": "生产企业",
    "生产厂（全称）": "生产企业",
    "认证标准": "认证标准",
    "本次使用/备用": "本次使用",
    "备注": "备注",
}

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_CARRY = ["序号", "关键件名称"]


def _clean(value: Any) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ")
    return _CTRL.sub("", text).strip()


def _field_for_header(value: str) -> str | None:
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
        cells.append((column, _clean(_Cell(tc, table).text), span, _is_vertical_merge(tc)))
        column += span
    return cells


def _header_map(cells: list[tuple[int, str, int, bool]]) -> dict[int, str]:
    return {
        column: field
        for column, text, _span_value, _vertical in cells
        if (field := _field_for_header(text))
    }


def is_keylist_header(table: Any) -> bool:
    """表头指纹：命中"关键件清单"类表（含 关键件名称/名称 且含 型号）。"""
    if not table.rows:
        return False
    col_map = _header_map(_xml_cells(table.rows[0], table))
    fields = set(col_map.values())
    return "型号" in fields and ("关键件名称" in fields)


def parse_keylist_table(
    table: Any, doc_table_index: int, side: str, block: str
) -> list[Row]:
    """把一张"关键件清单"表解析为 Row 列表（携带批注定位信息）。"""
    rows: list[Row] = []
    if not table.rows:
        return rows

    header_cells = _xml_cells(table.rows[0], table)
    col_map = _header_map(header_cells)
    header_max = max((c for c, _t, _s, _v in header_cells), default=0)
    model_ci = next((ci for ci, field in col_map.items() if field == "型号"), None)
    name_ci = next((ci for ci, field in col_map.items() if field == "关键件名称"), None)
    merge_point = model_ci + 1 if model_ci is not None else None
    # 批注锚点列：优先关键件名称列，退化到型号列
    anchor_ci = name_ci if name_ci is not None else (model_ci or 1)
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
        for header_column in sorted(col_map):
            if header_column > column:
                return col_map[header_column]
        return None

    for row_index, word_row in enumerate(table.rows[1:], start=2):
        cells = _xml_cells(word_row, table)
        non_empty = [text for _c, text, _s, _v in cells if text]
        if len(cells) == 1 and non_empty:
            carry["group"] = non_empty[0]
            continue
        if not non_empty:
            continue

        row_max = max((c for c, _t, _s, _v in cells), default=0)
        data: dict[str, Any] = {
            "side": side,
            "block": block,
            "doc_table_index": doc_table_index,
            "row_index": row_index,
            "anchor_col": anchor_ci,
            "group": carry.get("group", ""),
        }
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
                data[field] = merged_values[field]
        # EMC 清单的证书号常放在"备注"列
        if block == "emc" and data.get("备注"):
            data["证书号"] = data["备注"]
        for field in _CARRY:
            if not data.get(field):
                data[field] = carry.get(field, "")
            else:
                carry[field] = data[field]
        data["raw"] = raw
        rows.append(Row(**{k: v for k, v in data.items() if k in Row.model_fields or k == "raw"}))
    return rows
