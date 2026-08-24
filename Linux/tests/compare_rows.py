"""对比行数：两份输入(缓存解析) vs 输出样例(docx 直接数)。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compare_core.parser import load_rows_json

FX = Path(__file__).resolve().parent.parent / "runs" / "parse_real"
OUT_SAMPLE = Path(r"c:\Users\likunyuan\Desktop\项目\样例\75U66Q(01)_安全&EMC关键件清单--输出.doc")


def input_counts(tag):
    rows = load_rows_json(str(FX / f"{tag}.json"))
    t1 = sum(1 for r in rows if r.table == 1)
    t2 = sum(1 for r in rows if r.table == 2)
    return len(rows), t1, t2


def sample_docx_rows(path):
    """输出样例是 docx(zip)，python-docx 可直接读，统计各表数据行(去表头)。"""
    from docx import Document
    doc = Document(str(path))
    info = []
    total = 0
    for i, t in enumerate(doc.tables, 1):
        n = len(t.rows)
        total += n
        info.append((i, len(t.columns), n))
    return total, info


def main():
    for tag, name in [("orig", "原报告清单--输入"), ("plm", "PLM导出清单-输入")]:
        tot, t1, t2 = input_counts(tag)
        print(f"[输入] {name}: 总行 {tot} (表1 {t1} + 表2 {t2})")

    print(f"\n[输出样例] {OUT_SAMPLE.name}: 存在={OUT_SAMPLE.exists()}")
    try:
        tot, info = sample_docx_rows(OUT_SAMPLE)
        print(f"  含表 {len(info)} 个，总行(含表头) {tot}")
        for i, cols, n in info:
            print(f"    表{i}: 列={cols} 行={n}(含表头) → 数据行≈{n-1}")
    except Exception as e:  # noqa: BLE001
        print(f"  python-docx 读取失败: {e}")
    print("COMPARE_ROWS_DONE")


if __name__ == "__main__":
    main()
