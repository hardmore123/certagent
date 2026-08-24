import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from compare_core.parser.docx_parser import parse_docx

FOLDER = ROOT.parent / "AI智能体-认证原始清单与新品清单合并"
ORIG = FOLDER / "输入--【原始清单，人工已整理docx】4720467-85Z970QF(东芝)_安全&EMC关键件清单.docx"
PLM = FOLDER / "输入--【PLM导出清单-新品docx】85ZXSF(01)(东芝)_安全&EMC关键件清单 - 副本.docx"

TARGET_MODEL = "C3216X7R472KPPS"


def show(label, rows):
    print(f"\n=== {label} 中型号含 {TARGET_MODEL} 的行 ===")
    for r in rows:
        if TARGET_MODEL in (r.型号 or ""):
            print(f"  名称={r.关键件名称!r}")
            print(f"  型号={r.型号!r}")
            print(f"  位号={r.位号!r}")
            print(f"  规格材料={r.规格材料!r}")
            print(f"  制造商={r.制造商!r}")
            print(f"  生产企业={r.生产企业!r}")
            print(f"  认证标准={r.认证标准!r}")
            print(f"  证书号={r.证书号!r}")
            print(f"  备注={r.备注!r}")
            print(f"  组={r.group!r}")
            print(f"  raw={r.raw}")
            print()


orig = parse_docx(str(ORIG))
plm = parse_docx(str(PLM))
show("A(原始清单)", orig)
show("B(PLM)", plm)
print("CHECK_CAPACITOR_DONE")
