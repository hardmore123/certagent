"""验证：差异确认页顺序(order_for_output) == 最终文档行顺序(writer 输出的 docx)。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from compare_core import nodes, trace
from compare_core.differ import display_row, order_for_output
from compare_core.differ.normalize import normalize
from compare_core.parser.docx_parser import parse_docx
from compare_core.writer.docx_writer import write_merged_list

FOLDER = ROOT.parent / "AI智能体-认证原始清单与新品清单合并"
ORIG = FOLDER / "输入--【原始清单，人工已整理docx】4720467-85Z970QF(东芝)_安全&EMC关键件清单.docx"
PLM = FOLDER / "输入--【PLM导出清单-新品docx】85ZXSF(01)(东芝)_安全&EMC关键件清单 - 副本.docx"


def main():
    trace.new_run()
    state = {"rows_orig": parse_docx(str(ORIG)), "rows_plm": parse_docx(str(PLM))}
    state.update(nodes.judge_node(state))
    diffs = state["diffs"]
    decisions = {d.key: "accept" for d in diffs}

    # 1) 确认页顺序
    ordered = order_for_output(diffs)
    print(f"diffs={len(diffs)}, order_for_output={len(ordered)}")
    print("\n=== 确认页前 6 行（序号 | 类型 | 名称）===")
    for i, d in enumerate(ordered[:6], 1):
        r = display_row(d)
        print(f"  [{i}] {d.type.value:<10} | {(r.关键件名称 or '')[:26]}")

    # 表一必须全部排在表二之前
    tables = [d.table for d in ordered]
    assert tables == sorted(tables), "表一应全部排在表二之前"

    # 2) 生成文档并回读
    out = ROOT / "runs" / "review_order_test"
    out.mkdir(parents=True, exist_ok=True)
    docx_path = str(out / "整合版关键件清单.docx")
    write_merged_list(diffs, decisions, docx_path)

    from docx import Document
    doc = Document(docx_path)
    doc_rows = []
    for t in doc.tables:
        for i, r in enumerate(t.rows):
            if i == 0:
                continue
            texts = [c.text for c in r.cells]
            if texts and texts[0] and len(set(texts)) == 1:
                continue  # 分组标题行
            doc_rows.append((normalize(texts[2] if len(texts) > 2 else ""),
                             normalize(texts[3] if len(texts) > 3 else "")))

    page_rows = []
    for d in ordered:
        r = display_row(d)
        page_rows.append((normalize(r.关键件名称 or ""), normalize(r.型号 or "")))

    print(f"\n文档数据行={len(doc_rows)}, 确认页行={len(page_rows)}")
    assert len(doc_rows) == len(page_rows), "行数应一致"

    mismatch = [(i, p, dd) for i, (p, dd) in enumerate(zip(page_rows, doc_rows), 1) if p != dd]
    print(f"逐行顺序不一致处={len(mismatch)}")
    for i, p, dd in mismatch[:5]:
        print(f"  行{i}: 页={p[0][:20]}/{p[1][:16]}  文档={dd[0][:20]}/{dd[1][:16]}")
    assert not mismatch, "确认页顺序应与文档逐行一致"

    print("\n[OK] 确认页顺序 == 最终文档顺序")
    print("TEST_REVIEW_ORDER_DONE")


if __name__ == "__main__":
    main()
