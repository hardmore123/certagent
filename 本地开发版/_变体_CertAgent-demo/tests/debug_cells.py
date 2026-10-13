"""诊断：打印表1 表头与前几行的真实 (RowIndex, ColumnIndex, 文本)。"""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import win32com.client as win32

from compare_core.parser.doc_parser import _clean

DOC = r"c:\Users\likunyuan\Desktop\项目\项目需求\20.认证智能体PRD\图片和附件\75U66Q(01)_原报告清单.doc"

word = win32.Dispatch("Word.Application")
word.Visible = False
doc = word.Documents.Open(DOC, ReadOnly=True)
try:
    t = doc.Tables(1)
    by_row = defaultdict(list)
    cells = t.Range.Cells
    limit = min(45, cells.Count)          # 只读前 ~45 个单元格（表头+前几行）
    for i in range(1, limit + 1):
        c = cells.Item(i)
        by_row[int(c.RowIndex)].append((int(c.ColumnIndex), _clean(c.Range.Text)[:16]))
    for ri in sorted(by_row):
        print(f"ROW {ri}: ", sorted(by_row[ri]))
finally:
    doc.Close(False)
    word.Quit()
print("DEBUG_DONE")
