"""对已解析的真实 fixture 做解析质量量化（无需 Word，稳定可复现）。"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compare_core.parser import load_rows_json

BASE = Path(__file__).resolve().parent.parent / "runs" / "parse_real"
FILES = {"原报告清单": "orig.json", "PLM导出清单": "plm.json"}
CERT = re.compile(r"^\d{10,}$")
FIELDS = ["关键件名称", "型号", "规格材料", "制造商", "生产企业", "认证标准", "证书号"]


def fill(rows, f):
    n = sum(1 for r in rows if getattr(r, f))
    return f"{n}/{len(rows)} ({100 * n // (len(rows) or 1)}%)"


def check(tag, path):
    print(f"\n===== {tag} ({path.name}) =====")
    if not path.exists():
        print("  [跳过] fixture 不存在")
        return
    rows = load_rows_json(str(path))
    t1 = [r for r in rows if r.table == 1]
    t2 = [r for r in rows if r.table == 2]
    print(f"  总行 {len(rows)}  表1 {len(t1)}  表2 {len(t2)}")
    for f in FIELDS:
        print(f"    {f:6} 填充率(表1) {fill(t1, f)}")
    no_name = sum(1 for r in t1 if r.型号 and not r.关键件名称)
    has_cert = sum(1 for r in t1 if r.证书号)
    cert_ok = sum(1 for r in t1 if CERT.match(r.证书号 or ""))
    shift_bug = sum(1 for r in t1 if r.规格材料 and r.规格材料 == r.制造商)
    groups = len({r.group for r in t1 if r.group})
    print(f"  [跨行填充失败] 有型号无名称: {no_name}")
    print(f"  [证书号形态] 合格 {cert_ok}/{has_cert}")
    print(f"  [列错位征兆] 规格材料==制造商: {shift_bug}")
    print(f"  [分组标题] 捕获 {groups} 种")


def main():
    for tag, fn in FILES.items():
        check(tag, BASE / fn)
    print("\nVERIFY_FIXTURES_DONE")


if __name__ == "__main__":
    main()
