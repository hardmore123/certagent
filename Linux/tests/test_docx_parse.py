"""验证 python-docx 解析真实转换后的 docx 文件。"""
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from compare_core.parser.docx_parser import parse_docx

FOLDER = ROOT.parent / "AI智能体-认证原始清单与新品清单合并"

# 候选 docx 文件
CANDIDATES = [
    "输入--【原始清单，人工已整理docx】4720467-85Z970QF(东芝)_安全&EMC关键件清单.docx",
    "输入--【PLM导出清单-新品docx】85ZXSF(01)(东芝)_安全&EMC关键件清单 - 副本.docx",
]


def main():
    for name in CANDIDATES:
        path = FOLDER / name
        print(f"\n=== {name} ===")
        if not path.exists():
            print(f"  文件不存在: {path}")
            continue
        try:
            rows = parse_docx(str(path))
            print(f"  解析成功: {len(rows)} 行")
            tables = Counter(r.table for r in rows)
            print(f"  表分布: {dict(tables)}")
            # 字段填充率（表1）
            t1 = [r for r in rows if r.table == 1]
            if t1:
                fields = ["关键件名称", "型号", "制造商", "生产企业", "认证标准", "证书号", "规格材料"]
                print("  表1 字段填充率:")
                for f in fields:
                    filled = sum(1 for r in t1 if getattr(r, f, ""))
                    print(f"    {f}: {filled}/{len(t1)} ({filled/len(t1)*100:.0f}%)")
            # 抽样前 3 行
            print("  前 3 行抽样:")
            for r in rows[:3]:
                print(f"    表{r.table} 组={r.group[:15]!r} 名称={r.关键件名称[:20]!r} 型号={r.型号[:30]!r}")
        except Exception as e:
            import traceback
            print(f"  解析失败: {type(e).__name__}: {e}")
            print(traceback.format_exc()[-500:])

    print("\nTEST_DOCX_PARSE_DONE")


if __name__ == "__main__":
    main()
