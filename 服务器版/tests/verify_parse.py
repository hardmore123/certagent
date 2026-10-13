"""Word 解析质量验证：跨多份真实清单样例，量化字段填充率与异常。"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compare_core.parser import parse_document

ATT = Path(r"c:\Users\likunyuan\Desktop\项目\项目需求\20.认证智能体PRD\图片和附件")
FILES = [
    "75U66Q(01)_PLM导出清单.doc",
    "75U66Q(01)_原报告清单.doc",
    "75U66Q(01)_安全&EMC关键件清单.doc",
    "75VX5S-PRO(01)_安全&EMC关键件清单.doc",
    "100E7S-PRO(01)_安全&EMC关键件清单.doc",
]
CERT = re.compile(r"^\d{10,}$")
FIELDS = ["关键件名称", "型号", "规格材料", "制造商", "生产企业", "认证标准", "证书号"]


def fill(rows, f):
    n = sum(1 for r in rows if getattr(r, f))
    tot = len(rows) or 1
    return f"{n}/{len(rows)} ({100 * n // tot}%)"


def check(path: Path):
    print(f"\n===== {path.name} =====")
    if not path.exists():
        print("  [跳过] 文件不存在")
        return
    rows = parse_document(str(path))
    t1 = [r for r in rows if r.table == 1]
    t2 = [r for r in rows if r.table == 2]
    print(f"  总行 {len(rows)}  表1 {len(t1)}  表2 {len(t2)}")
    for f in FIELDS:
        print(f"    {f:6} 填充率 表1 {fill(t1, f)}")
    # 异常指标
    no_name = sum(1 for r in t1 if r.型号 and not r.关键件名称)      # 跨行填充失败
    cert_ok = sum(1 for r in t1 if CERT.match(r.证书号 or ""))        # 证书号形态正确
    has_cert = sum(1 for r in t1 if r.证书号)
    shift_bug = sum(1 for r in t1 if r.规格材料 and r.规格材料 == r.制造商)  # 列错位征兆
    groups = len({r.group for r in t1 if r.group})
    print(f"  [异常] 有型号无名称(跨行填充失败): {no_name}")
    print(f"  [质量] 证书号形态合格: {cert_ok}/{has_cert}  分组标题捕获: {groups} 种")
    print(f"  [错位检测] 规格材料==制造商(列错位征兆): {shift_bug}")


def main():
    for f in FILES:
        check(ATT / f)
    print("\nVERIFY_DONE")


if __name__ == "__main__":
    main()
