"""标识方式①：把差异项以 Word 批注写回报告草稿(B)原位。

依赖 python-docx>=1.1 的原生 add_comment(runs, text, author, initials)。
定位：VerifyItem.b_row 记录 doc_table_index / row_index / anchor_col，
据此找到 B 文档对应单元格的段落 run，锚定批注。
无 b_row 的差异（如 MISSING_IN_REPORT）无法锚定，交由 summary_writer 汇总。
"""
from __future__ import annotations

from pathlib import Path

from ..models import VerifyItem, VerifyType

_AUTHOR = "报告核对Agent"
_INITIALS = "RV"


def _anchor_runs(table, row_index: int, anchor_col: int):
    """取目标单元格首段落的 runs（无 run 则补一个空 run 供锚定）。"""
    row = table.rows[row_index - 1]          # row_index 1-based
    # anchor_col 为逻辑列号；python-docx 的 row.cells 已按网格展开，用列号近似定位
    cells = row.cells
    ci = min(max(anchor_col - 1, 0), len(cells) - 1)
    cell = cells[ci]
    para = cell.paragraphs[0] if cell.paragraphs else cell.add_paragraph("")
    if not para.runs:
        para.add_run(cell.text or " ")
    return para.runs


def write_comments(report_docx: str, items: list[VerifyItem], out_path: str) -> dict:
    """在报告草稿副本上写批注，另存到 out_path。返回统计。"""
    from docx import Document

    doc = Document(str(Path(report_docx).resolve()))
    tables = doc.tables
    anchored = 0
    unanchored = 0

    for it in items:
        if it.type == VerifyType.CONSISTENT:
            continue
        b = it.b_row
        if b is None or b.doc_table_index < 1 or b.doc_table_index > len(tables):
            unanchored += 1
            continue
        try:
            table = tables[b.doc_table_index - 1]
            runs = _anchor_runs(table, b.row_index, b.anchor_col)
            doc.add_comment(runs, text=it.describe(), author=_AUTHOR, initials=_INITIALS)
            anchored += 1
        except Exception:  # noqa: BLE001  锚定失败不阻断，落到未锚定计数
            unanchored += 1

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_path)
    return {"anchored": anchored, "unanchored": unanchored, "out": out_path}
