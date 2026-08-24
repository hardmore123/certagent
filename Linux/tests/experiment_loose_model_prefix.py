"""实验：loose 阶段的型号判据，"全等"（现状）vs "前缀相同" 哪个更好。

只读实验。在同表+同组+同关键件名称的前提下，考察把型号判据放宽为"前缀关系"
会新增哪些配对，逐条列出供人工判断是否合理（是真·同一件，还是误配）。
"""
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from compare_core.differ import run_diff
from compare_core.differ.normalize import normalize
from compare_core.models import DiffType
from compare_core.parser.docx_parser import parse_docx
from compare_core.rules import load_rules

F = ROOT.parent / "AI智能体-认证原始清单与新品清单合并"
A_rows = parse_docx(str(F / "输入--【原始清单，人工已整理docx】4720467-85Z970QF(东芝)_安全&EMC关键件清单.docx"))
B_rows = parse_docx(str(F / "输入--【PLM导出清单-新品docx】85ZXSF(01)(东芝)_安全&EMC关键件清单 - 副本.docx"))
rules = load_rules()

diffs = run_diff(A_rows, B_rows, rules)
A = [d.orig for d in diffs if d.type == DiffType.ONLY_ORIG and d.orig]
B = [d.plm for d in diffs if d.type == DiffType.ONLY_PLM and d.plm]
print(f"现状(型号全等)残余：A独有={len(A)} B独有={len(B)}")


def base_key(r):
    """同表+同组+同名称（型号除外）"""
    return (r.table, normalize(r.group, drop_space=False), normalize(r.关键件名称))


def is_prefix(x: str, y: str, min_len: int = 3):
    """短的是长的前缀（且不相等）"""
    if not x or not y or x == y:
        return False
    s, l = (x, y) if len(x) <= len(y) else (y, x)
    return len(s) >= min_len and l.startswith(s)


# 在同表同组同名称的桶内，找型号有前缀关系的对
buckets = defaultdict(lambda: ([], []))
for r in A:
    buckets[base_key(r)][0].append(r)
for r in B:
    buckets[base_key(r)][1].append(r)

cand = []
for k, (aa, bb) in buckets.items():
    for a in aa:
        for b in bb:
            na, nb = normalize(a.型号), normalize(b.型号)
            if is_prefix(na, nb):
                cand.append((a, b, na, nb))

print(f"\n若把 loose 的型号判据放宽为『前缀关系』，新增候选配对 = {len(cand)} 对")
print("（约束仍为：同表 + 同组 + 同关键件名称）\n")
for i, (a, b, na, nb) in enumerate(cand, 1):
    short, long = (na, nb) if len(na) <= len(nb) else (nb, na)
    print(f"[{i}] {(a.关键件名称 or '')[:18]}  组={(a.group or '(顶层)')[:16]}")
    print(f"    A型号: {a.型号[:60]}")
    print(f"    B型号: {b.型号[:60]}")
    print(f"    前缀: {short[:40]!r} 是 {long[:40]!r} 的前缀")
    print(f"    证书号 A={(a.证书号 or '')[:22]}  B={(b.证书号 or '')[:22]}")
    print(f"    规格   A={(a.规格材料 or '')[:22]}  B={(b.规格材料 or '')[:22]}")
    print()

# 反向风险扫描：全量数据里，同名称下型号互为前缀但明显是不同物料的例子
print("=== 反向风险：全量数据中『同组同名称、型号互为前缀』的组合（潜在误配面）===")
allbuck = defaultdict(lambda: ([], []))
for r in A_rows:
    allbuck[base_key(r)][0].append(r)
for r in B_rows:
    allbuck[base_key(r)][1].append(r)
risk = 0
shown = 0
for k, (aa, bb) in allbuck.items():
    for a in aa:
        for b in bb:
            na, nb = normalize(a.型号), normalize(b.型号)
            if is_prefix(na, nb):
                risk += 1
                if shown < 8:
                    shown += 1
                    print(f"  {(a.关键件名称 or '')[:14]:<16} A={a.型号[:30]:<32} B={b.型号[:30]}")
print(f"  合计 {risk} 组合（含已被 rich/loose 正常配对的，仅示意前缀关系的普遍程度）")

print("\nEXPERIMENT_LOOSE_PREFIX_DONE")
