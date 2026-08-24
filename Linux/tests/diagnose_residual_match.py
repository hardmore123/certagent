"""诊断：A独有(ONLY_ORIG) 与 B独有(ONLY_PLM) 残余池里，是否存在
'相同 / 本应匹配却没配上' 的行。用多种信号交叉排查匹配漏网（假阴性）。

只读，不改核心。信号从强到弱：
  S1 归一后整行相同(rich 字段全等)  → 本应 SAME，未配=引擎bug
  S2 loose键相同(表+组+名称+型号)   → 本应 CHANGED，未配=跨组/消费顺序问题
  S3 名称+型号相同但跨组(组不同)     → 可能同件被分到不同组
  S4 证书号相同且非空                → 强信号：多半同一件
  S5 型号相同(名称不同)              → 候选：换名/详略
  S6 名称前缀关系(同组)              → 候选：名称细化(电线组件类)
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

FOLDER = ROOT.parent / "AI智能体-认证原始清单与新品清单合并"
ORIG = FOLDER / "输入--【原始清单，人工已整理docx】4720467-85Z970QF(东芝)_安全&EMC关键件清单.docx"
PLM = FOLDER / "输入--【PLM导出清单-新品docx】85ZXSF(01)(东芝)_安全&EMC关键件清单 - 副本.docx"

_RICH = ["group", "关键件名称", "型号", "位号", "规格材料", "证书号"]


def _n(r, f):
    return normalize(getattr(r, f, "") or "")


def _rich_key(r):
    return f"t{r.table}|" + "|".join(_n(r, f) for f in _RICH)


def _loose_key(r):
    return f"t{r.table}|" + "|".join(_n(r, f) for f in ["group", "关键件名称", "型号"])


def _desc(r):
    return f"表{r.table}[{(r.group or '')[:8]}] {(r.关键件名称 or '')[:16]} / {(r.型号 or '')[:24]} / 证{(r.证书号 or '')[:10]}"


def main():
    rules = load_rules()
    rows_orig = parse_docx(str(ORIG))
    rows_plm = parse_docx(str(PLM))
    diffs = run_diff(rows_orig, rows_plm, rules)  # 基线，无 AI

    A = [d.orig for d in diffs if d.type == DiffType.ONLY_ORIG and d.orig]
    B = [d.plm for d in diffs if d.type == DiffType.ONLY_PLM and d.plm]
    print(f"A独有(ONLY_ORIG)={len(A)} 行, B独有(ONLY_PLM)={len(B)} 行\n")

    usedB = set()
    findings = {k: [] for k in ["S1", "S2", "S3", "S4", "S5", "S6"]}

    # 建 B 侧索引
    B_rich = defaultdict(list)
    B_loose = defaultdict(list)
    B_nameModelNoGroup = defaultdict(list)
    B_cert = defaultdict(list)
    B_model = defaultdict(list)
    for j, b in enumerate(B):
        B_rich[_rich_key(b)].append(j)
        B_loose[_loose_key(b)].append(j)
        B_nameModelNoGroup[f"t{b.table}|{_n(b,'关键件名称')}|{_n(b,'型号')}"].append(j)
        if _n(b, "证书号"):
            B_cert[f"t{b.table}|{_n(b,'证书号')}"].append(j)
        if _n(b, "型号") and len(_n(b, "型号")) >= 3:
            B_model[f"t{b.table}|{_n(b,'型号')}"].append(j)

    def _take(idxs):
        for j in idxs:
            if j not in usedB:
                return j
        return None

    for a in A:
        # S1 rich 相同
        j = _take(B_rich.get(_rich_key(a), []))
        if j is not None:
            usedB.add(j); findings["S1"].append((a, B[j])); continue
        # S2 loose 相同
        j = _take(B_loose.get(_loose_key(a), []))
        if j is not None:
            usedB.add(j); findings["S2"].append((a, B[j])); continue
        # S3 名称+型号相同但跨组
        j = _take(B_nameModelNoGroup.get(f"t{a.table}|{_n(a,'关键件名称')}|{_n(a,'型号')}", []))
        if j is not None:
            usedB.add(j); findings["S3"].append((a, B[j])); continue
        # S4 证书号相同
        if _n(a, "证书号"):
            j = _take(B_cert.get(f"t{a.table}|{_n(a,'证书号')}", []))
            if j is not None:
                usedB.add(j); findings["S4"].append((a, B[j])); continue
        # S5 型号相同(名称不同)
        if _n(a, "型号") and len(_n(a, "型号")) >= 3:
            j = _take(B_model.get(f"t{a.table}|{_n(a,'型号')}", []))
            if j is not None:
                usedB.add(j); findings["S5"].append((a, B[j])); continue
        # S6 名称前缀关系(同组)
        na = _n(a, "关键件名称")
        if len(na) >= 3:
            for j2, b in enumerate(B):
                if j2 in usedB:
                    continue
                if a.table != b.table or _n(a, "group") != _n(b, "group"):
                    continue
                nb = _n(b, "关键件名称")
                if len(nb) < 3 or na == nb:
                    continue
                short, lng = (na, nb) if len(na) <= len(nb) else (nb, na)
                if lng.startswith(short):
                    usedB.add(j2); findings["S6"].append((a, b)); break

    labels = {
        "S1": "归一后整行相同(本应SAME，疑似引擎bug)",
        "S2": "loose键相同(本应CHANGED，疑似跨组/消费顺序)",
        "S3": "名称+型号相同但跨组(可能同件被分到不同组)",
        "S4": "证书号相同(强信号:多半同一件)",
        "S5": "型号相同/名称不同(候选:换名/详略)",
        "S6": "名称前缀关系/同组(候选:名称细化)",
    }
    total = 0
    for k in ["S1", "S2", "S3", "S4", "S5", "S6"]:
        fs = findings[k]
        total += len(fs)
        print(f"[{k}] {labels[k]}: {len(fs)} 对")
        for a, b in fs[:8]:
            print(f"    A: {_desc(a)}")
            print(f"    B: {_desc(b)}")
            print()
    print(f"=== 疑似漏配合计 {total} 对；剩余无信号 A={len(A)-total} 行（可能确为独有）===")
    print("DIAGNOSE_RESIDUAL_DONE")


if __name__ == "__main__":
    main()
