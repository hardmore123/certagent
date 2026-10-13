"""实验：能否用"相似度"判断残余池里两行是不是同一个物料。

只读实验，不改核心。对 A独有 × B独有 的残余池两两打分，考察：
1. 各相似度指标的分布
2. 用阈值自动配对的精确率/召回率（金标准 = 人工判定）
3. 与"跨组换型"这类必须拒绝的负例能否分开

指标：
- name_ratio  : 关键件名称 SequenceMatcher 比率
- model_ratio : 型号 SequenceMatcher 比率
- model_jac   : 型号按分隔符拆成集合的 Jaccard（应对"一格多型号"）
- cert_eq     : 证书号是否相同
- combo       : 综合分（名称 0.5 + max(型号ratio, 型号jaccard) 0.5）
"""
import sys
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from compare_core.differ import run_diff
from compare_core.differ.normalize import normalize
from compare_core.models import DiffType
from compare_core.parser.docx_parser import parse_docx
from compare_core.rules import load_rules

F = ROOT.parent / "AI智能体-认证原始清单与新品清单合并"
ORIG = F / "输入--【原始清单，人工已整理docx】4720467-85Z970QF(东芝)_安全&EMC关键件清单.docx"
PLM = F / "输入--【PLM导出清单-新品docx】85ZXSF(01)(东芝)_安全&EMC关键件清单 - 副本.docx"

SEPS = "、,;；/／+＋"


def _split_models(s: str) -> set[str]:
    t = normalize(s)
    for ch in SEPS:
        t = t.replace(ch, "|")
    return {x for x in (p.strip() for p in t.split("|")) if x and x != "/"}


def ratio(a: str, b: str) -> float:
    na, nb = normalize(a), normalize(b)
    if not na and not nb:
        return 1.0
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def jaccard(a: str, b: str) -> float:
    sa, sb = _split_models(a), _split_models(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def score(a, b) -> dict:
    nr = ratio(a.关键件名称, b.关键件名称)
    mr = ratio(a.型号, b.型号)
    mj = jaccard(a.型号, b.型号)
    return {
        "name_ratio": nr, "model_ratio": mr, "model_jac": mj,
        "cert_eq": normalize(a.证书号) == normalize(b.证书号) and bool(normalize(a.证书号)),
        "combo": 0.5 * nr + 0.5 * max(mr, mj),
        "same_group": normalize(a.group, drop_space=False) == normalize(b.group, drop_space=False),
    }


def main():
    rules = load_rules()
    A_rows = parse_docx(str(ORIG))
    B_rows = parse_docx(str(PLM))
    diffs = run_diff(A_rows, B_rows, rules)
    A = [d.orig for d in diffs if d.type == DiffType.ONLY_ORIG and d.orig]
    B = [d.plm for d in diffs if d.type == DiffType.ONLY_PLM and d.plm]
    print(f"残余池：A独有={len(A)}  B独有={len(B)}  两两组合={len(A)*len(B)}")

    # 全量打分
    pairs = []
    for a in A:
        for b in B:
            if a.table != b.table:
                continue
            s = score(a, b)
            pairs.append((s["combo"], a, b, s))
    pairs.sort(key=lambda x: -x[0])

    print("\n=== combo 得分 Top 15（含是否同组）===")
    print(f"{'combo':>6} {'name':>5} {'mRatio':>6} {'mJac':>5} {'同组':>4} | A名称 / B名称")
    for c, a, b, s in pairs[:15]:
        print(f"{c:6.3f} {s['name_ratio']:5.2f} {s['model_ratio']:6.2f} {s['model_jac']:5.2f} "
              f"{'是' if s['same_group'] else '否':>4} | {(a.关键件名称 or '')[:16]} / {(b.关键件名称 or '')[:16]}")

    # 金标准：LLM 曾提名且业务可接受的（同组、名称同或前缀）视为正例；跨组同名视为负例
    print("\n=== 关键对照：同名但跨组（电源单元换型，必须【拒绝】配对）===")
    cross = [(c, a, b, s) for c, a, b, s in pairs
             if normalize(a.关键件名称) == normalize(b.关键件名称) and not s["same_group"]]
    print(f"共 {len(cross)} 对，combo 得分区间: "
          f"{min((c for c,_,_,_ in cross), default=0):.3f} ~ {max((c for c,_,_,_ in cross), default=0):.3f}")
    for c, a, b, s in cross[:5]:
        print(f"  combo={c:.3f} | {(a.关键件名称 or '')[:14]} | A组={(a.group or '')[:14]} B组={(b.group or '')[:14]}")

    print("\n=== 关键对照：同组且名称有前缀关系（应【接受】，如电线组件）===")
    good = []
    for c, a, b, s in pairs:
        if not s["same_group"]:
            continue
        na, nb = normalize(a.关键件名称), normalize(b.关键件名称)
        if na == nb:
            continue
        short, lng = (na, nb) if len(na) <= len(nb) else (nb, na)
        if len(short) >= 3 and lng.startswith(short):
            good.append((c, a, b, s))
    print(f"共 {len(good)} 对，combo 得分区间: "
          f"{min((c for c,_,_,_ in good), default=0):.3f} ~ {max((c for c,_,_,_ in good), default=0):.3f}")
    for c, a, b, s in good[:5]:
        print(f"  combo={c:.3f} name={s['name_ratio']:.2f} | {(a.关键件名称 or '')[:14]} → {(b.关键件名称 or '')[:22]}")

    print("\n=== 关键对照：证书号相同（强信号，但含反例）===")
    cert = [(c, a, b, s) for c, a, b, s in pairs if s["cert_eq"]]
    print(f"共 {len(cert)} 对")
    for c, a, b, s in cert[:8]:
        flag = "同组" if s["same_group"] else "跨组"
        print(f"  combo={c:.3f} name={s['name_ratio']:.2f} mJac={s['model_jac']:.2f} {flag} | "
              f"{(a.关键件名称 or '')[:12]} / {(b.关键件名称 or '')[:12]}")

    # 阈值扫描：只在同组内用 combo 阈值配对，看会命中多少、误配多少
    print("\n=== 阈值扫描（限同组 + combo 阈值，贪心一对一）===")
    print(f"{'阈值':>5} {'配对数':>6} {'其中前缀关系(合理)':>18} {'其中同名跨组(误配)':>18} {'其它(需人工)':>12}")
    for th in [0.95, 0.9, 0.85, 0.8, 0.75, 0.7, 0.6, 0.5]:
        usedA, usedB = set(), set()
        picked = []
        for c, a, b, s in pairs:
            if c < th or not s["same_group"]:
                continue
            if id(a) in usedA or id(b) in usedB:
                continue
            usedA.add(id(a)); usedB.add(id(b))
            picked.append((c, a, b, s))
        n_prefix = 0
        n_other = 0
        for c, a, b, s in picked:
            na, nb = normalize(a.关键件名称), normalize(b.关键件名称)
            short, lng = (na, nb) if len(na) <= len(nb) else (nb, na)
            if na != nb and len(short) >= 3 and lng.startswith(short):
                n_prefix += 1
            else:
                n_other += 1
        print(f"{th:5.2f} {len(picked):6d} {n_prefix:18d} {0:18d} {n_other:12d}")

    print("\nEXPERIMENT_SIMILARITY_DONE")


if __name__ == "__main__":
    main()
