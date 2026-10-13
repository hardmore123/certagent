"""用真实样例 .doc 跑解析器，输出结构化行摘要并核对畸形处理。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compare_core.parser import parse_document

BASE = Path(r"c:\Users\likunyuan\Desktop\项目\项目需求\20.认证智能体PRD\图片和附件")
FILES = {
    "orig": BASE / "75U66Q(01)_原报告清单.doc",
    "plm": BASE / "75U66Q(01)_PLM导出清单.doc",
}
OUT = Path(__file__).resolve().parent.parent / "runs" / "parse_real"
OUT.mkdir(parents=True, exist_ok=True)


def summarize(tag: str, rows):
    print(f"\n===== {tag}: 共 {len(rows)} 行 =====")
    by_table = {}
    for r in rows:
        by_table.setdefault(r.table, 0)
        by_table[r.table] += 1
    print("按表统计:", by_table)
    # 抽样前 6 行看字段映射/跨行填充/分组
    for r in rows[:6]:
        print(f"  [T{r.table}] 组={r.group[:18]!r} 序号={r.序号!r} 名称={r.关键件名称!r} "
              f"型号={r.型号[:24]!r} 证书号={r.证书号!r}")
    # 保存为 fixture，供后续无 Word 跑全流程
    fx = OUT / f"{tag}.json"
    fx.write_text(json.dumps([r.model_dump() for r in rows], ensure_ascii=False, indent=2), encoding="utf-8")
    print("已保存 fixture:", fx)


def main():
    for tag, path in FILES.items():
        if not path.exists():
            print(f"[跳过] 文件不存在: {path}")
            continue
        rows = parse_document(str(path))
        summarize(tag, rows)
    print("\nPARSE_REAL_DONE")


if __name__ == "__main__":
    main()
