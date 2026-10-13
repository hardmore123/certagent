"""文档解析：.doc/.docx 表格 -> 结构化 Row。

★ 对抗"不可信"的重心在这一层：畸形枚举 + 兜底 + 结果可核对。
本期用 Word COM(pywin32) 解析；提供 json fixture 兜底，便于无 Word 环境测试。
"""
from __future__ import annotations

import json
from pathlib import Path

from ..models import Row

# 表头别名 -> 统一字段。容错：不同清单表头措辞略有差异。
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

# 需要跨行向下填充的字段（空表示"延续上一个件"）
_CARRY = ["序号", "关键件名称"]


import re as _re

# 去除 XML/docx 不兼容的控制字符（保留常规空白由后续 strip 处理）
_CTRL = _re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _clean(text: str) -> str:
    s = (text or "").replace("\r", " ").replace("\x07", "").replace("\n", " ")
    s = _CTRL.sub("", s)
    return s.strip()


def parse_document(path: str) -> list[Row]:
    """解析 Word 文档所有表格为 Row 列表。"""
    try:
        import win32com.client as win32  # type: ignore
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "未安装 pywin32 或无 Word 环境；测试可改用 load_rows_json 加载 fixture。"
        ) from e

    word = win32.Dispatch("Word.Application")
    word.Visible = False
    rows: list[Row] = []
    try:
        doc = word.Documents.Open(str(Path(path).resolve()), ReadOnly=True)
        try:
            for ti in range(1, doc.Tables.Count + 1):
                rows.extend(_parse_table(doc.Tables(ti), ti))
        finally:
            doc.Close(False)
    finally:
        word.Quit()
    return rows


def _iter_table_cells(table) -> dict[int, list[tuple[int, str]]]:
    """一次遍历整表所有单元格 -> {行号: [(列号, 文本), ...]}。

    ★ 用 table.Range.Cells 的 RowIndex/ColumnIndex 读取真实行列号：
    同时兼容横向合并（型号+规格/材料）与纵向合并（序号/名称跨行）——
    避免 table.Rows(r) 在纵向合并表上直接抛错的问题。
    """
    from collections import defaultdict

    by_row: dict[int, list[tuple[int, str]]] = defaultdict(list)
    try:
        cells = table.Range.Cells
        count = cells.Count
    except Exception:  # noqa: BLE001
        return by_row
    for i in range(1, count + 1):
        try:
            cell = cells.Item(i)
            by_row[int(cell.RowIndex)].append((int(cell.ColumnIndex), _clean(cell.Range.Text)))
        except Exception:  # noqa: BLE001
            continue
    for ri in by_row:
        by_row[ri].sort()
    return by_row


def _map_header_ci(header_cells: list[tuple[int, str]]) -> dict[int, str]:
    """逻辑列号 -> 统一字段名。"""
    mapping: dict[int, str] = {}
    for ci, text in header_cells:
        key = HEADER_MAP.get(text.strip())
        if key:
            mapping[ci] = key
    return mapping


def _parse_table(table, table_no: int) -> list[Row]:
    rows: list[Row] = []
    by_row = _iter_table_cells(table)
    if not by_row:
        return rows

    header_row = min(by_row)
    header_cells = by_row.get(header_row, [])
    col_map = _map_header_ci(header_cells)
    header_max = max((ci for ci, _ in header_cells), default=0)
    # 型号 后一列（通常是"规格/材料"）在正文里常与型号横向合并 -> 正文少一列
    model_ci = next((ci for ci, f in col_map.items() if f == "型号"), None)
    merge_point = (model_ci + 1) if model_ci is not None else None
    carry: dict[str, str] = {}

    def _field_for(ci: int, row_max: int) -> str | None:
        """正文行比表头少列时，从合并点起把列号 +1 对齐回表头。"""
        if merge_point is not None and header_max and row_max < header_max and ci >= merge_point:
            return col_map.get(ci + 1)
        return col_map.get(ci)

    for ri in sorted(by_row):
        if ri == header_row:
            continue
        cells = by_row[ri]
        if not cells:
            continue
        row_max = max((ci for ci, _ in cells), default=0)
        non_empty = [t for _, t in cells if t]
        # 分组标题行：整行是一个跨列合并的单元格
        if len(cells) == 1 and non_empty:
            carry["group"] = non_empty[0]
            continue
        if not non_empty:
            continue

        data = {"table": table_no, "group": carry.get("group", ""), "row_index": ri}
        raw: dict[str, str] = {}
        for ci, text in cells:
            raw[str(ci)] = text
            field = _field_for(ci, row_max)
            if field and text:
                data[field] = text
        # 表1 的证书号来自"备注"列
        if table_no == 1 and data.get("备注"):
            data["证书号"] = data["备注"]
        # 跨行填充（纵向合并的序号/关键件名称）
        for f in _CARRY:
            if not data.get(f):
                data[f] = carry.get(f, "")
            else:
                carry[f] = data[f]
        data["raw"] = raw
        rows.append(Row(**{k: v for k, v in data.items() if k in Row.model_fields or k == "raw"}))
    return rows


def load_rows_json(path: str) -> list[Row]:
    """从 json fixture 加载 Row（测试/无 Word 环境用）。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Row(**r) for r in data]
