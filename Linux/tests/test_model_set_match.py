"""测试第 2.5 趟"型号集合匹配"：
1) 拆分器：'/' 既是型号内字符又是分隔符的歧义处理
2) 四种集合关系：equal / subset / overlap / disjoint 各自的判定结果
3) 顺序无关性（前缀判据的致命缺陷，集合判据应免疫）
4) overlap 默认不自动合并（标为待确认配对）；开关打开后行为变化
5) 真实东芝样例上的效果与守恒
"""
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from compare_core.differ import run_audit, run_diff
from compare_core.differ.diff_engine import (
    _model_set_relation,
    _MS_DEFAULTS,
    _split_models,
)
from compare_core.models import DiffType, Row
from compare_core.parser.docx_parser import parse_docx
from compare_core.rules import load_rules

SEP = _MS_DEFAULTS["separators"]
G = "以下部分适用于整机结构1"


def mk(name, model, table=1, group=G, **kw):
    d = dict(table=table, group=group, 关键件名称=name, 型号=model,
             规格材料="V-0", 制造商="厂甲", 生产企业="厂甲",
             认证标准="GB4943.1-2022", 证书号="CQC001")
    d.update(kw)
    return Row(**d)


def counts(diffs):
    return dict(Counter(d.type.value for d in diffs))


def main():
    rules = load_rules()
    print("model_set_match 配置:", rules.get("model_set_match"))

    # ===== 1) 拆分器：'/' 的歧义 =====
    print("\n[1] 型号拆分（关键：型号自带 '/' 不应被误拆）")
    cases = [
        ("PC/ABS-5140", {"pc/abs-5140"}),
        ("PC/ABS-5140、PC/ABS-5143、PC/ABS-5144", {"pc/abs-5140", "pc/abs-5143", "pc/abs-5144"}),
        ("A001", {"a001"}),
        ("B001,B002,A001,C001", {"a001", "b001", "b002", "c001"}),
        ("S1000 H、S1000-2M", {"s1000h", "s1000-2m"}),   # 去空格
        ("/", set()),                                     # 占位符应被过滤
        # 括号说明必须剥离，否则"字母""数字"等会成为伪型号 token
        ("HD850K8U61-TBLC*(*代表企业内部代码，由一个或多个空、字母、数字、符号、汉字等组成，不影响产品安全和EMC性能)",
         {"hd850k8u61-tblc*"}),
        ("（全角括号说明，含、分隔）ABC-123", {"abc-123"}),
    ]
    for raw, expect in cases:
        got = _split_models(raw, SEP, 2)
        ok = "OK" if got == expect else "FAIL"
        print(f"  [{ok}] {raw[:44]:<46} -> {sorted(got)}")
        assert got == expect, f"{raw}: 期望 {expect}, 实得 {got}"

    # ===== 2) 四种集合关系 =====
    print("\n[2] 集合关系判定")
    rel_cases = [
        ("A001", "A001", "equal"),
        ("A001", "A001、B001", "subset"),
        ("A001、B001", "A001", "subset"),
        ("A001、A002", "A001、B001", "overlap"),
        ("A001", "B001", "disjoint"),
    ]
    for a, b, expect in rel_cases:
        rel = _model_set_relation(_split_models(a, SEP, 2), _split_models(b, SEP, 2))
        ok = "OK" if rel == expect else "FAIL"
        print(f"  [{ok}] A={a:<14} B={b:<16} -> {rel}")
        assert rel == expect

    # ===== 3) 端到端：subset 被配成 CHANGED 并标注新增型号 =====
    print("\n[3] subset(型号列表扩充) -> CHANGED")
    A = [mk("后壳材料", "PC/ABS-5140")]
    B = [mk("后壳材料", "PC/ABS-5140、PC/ABS-5143、PC/ABS-5144")]
    ds = run_diff(A, B, rules)
    print("  分布:", counts(ds))
    assert counts(ds) == {"changed": 1}, "应配成 1 条 CHANGED"
    print("  changed_fields:", ds[0].changed_fields)
    assert any("型号集合" in f and "新增" in f for f in ds[0].changed_fields), "应标注新增型号"
    assert not ds[0].pair_reason, "subset 语义明确，不应标为待确认配对"

    # ===== 4) 顺序无关性（前缀判据在此会失效，集合判据应免疫）=====
    print("\n[4] 顺序无关性")
    A2 = [mk("PCB", "F-D、F-M")]
    for b_model in ("F-D、F-M、F-X", "F-X、F-M、F-D", "F-M、F-X、F-D"):
        d2 = run_diff(A2, [mk("PCB", b_model)], rules)
        print(f"  B={b_model:<18} -> {counts(d2)}")
        assert counts(d2) == {"changed": 1}, f"顺序 {b_model} 应同样配成 CHANGED"

    # ===== 5) overlap 默认不自动合并，标为待确认配对 =====
    print("\n[5] overlap(部分重叠) -> 待确认配对")
    A3 = [mk("保险丝", "A001、A002")]
    B3 = [mk("保险丝", "A001、B001")]
    d3 = run_diff(A3, B3, rules)
    print("  分布:", counts(d3))
    print("  pair_reason:", d3[0].pair_reason[:56] if d3[0].pair_reason else "(无)")
    assert counts(d3) == {"changed": 1}
    assert d3[0].pair_reason, "overlap 应标为待确认配对（交人工）"
    assert d3[0].pair_confidence < 0.8, "overlap 置信度应低于自动阈值"

    # ===== 6) disjoint 不配对 =====
    print("\n[6] disjoint(无交集) -> 各自独有")
    d4 = run_diff([mk("保险丝", "A001")], [mk("保险丝", "B001")], rules)
    print("  分布:", counts(d4))
    assert counts(d4) == {"only_plm": 1, "only_orig": 1}, "无交集不应配对"

    # ===== 7) 跨组/跨表约束不放宽 =====
    print("\n[7] 跨组/跨表仍不配对")
    d5 = run_diff([mk("保险丝", "A001", group="旧电源单元")],
                  [mk("保险丝", "A001、B001", group="新电源单元")], rules)
    print("  跨组:", counts(d5))
    assert counts(d5) == {"only_plm": 1, "only_orig": 1}, "跨组不应配对"
    d6 = run_diff([mk("保险丝", "A001", table=1)],
                  [mk("保险丝", "A001、B001", table=2)], rules)
    print("  跨表:", counts(d6))
    assert counts(d6) == {"only_plm": 1, "only_orig": 1}, "跨表不应配对"

    # ===== 8) 关闭开关时行为回退 =====
    print("\n[8] 关闭 model_set_match 时回退为原行为")
    r_off = dict(rules)
    r_off["model_set_match"] = {**_MS_DEFAULTS, "enabled": False}
    d7 = run_diff([mk("后壳材料", "PC/ABS-5140")],
                  [mk("后壳材料", "PC/ABS-5140、PC/ABS-5143")], r_off)
    print("  分布:", counts(d7))
    assert counts(d7) == {"only_plm": 1, "only_orig": 1}, "关闭后应回退为各自独有"

    # ===== 9) 真实东芝样例：效果 + 守恒 =====
    print("\n[9] 真实东芝样例")
    F = ROOT.parent / "AI智能体-认证原始清单与新品清单合并"
    ra = parse_docx(str(F / "输入--【原始清单，人工已整理docx】4720467-85Z970QF(东芝)_安全&EMC关键件清单.docx"))
    rb = parse_docx(str(F / "输入--【PLM导出清单-新品docx】85ZXSF(01)(东芝)_安全&EMC关键件清单 - 副本.docx"))

    r_off2 = dict(rules)
    r_off2["model_set_match"] = {**_MS_DEFAULTS, "enabled": False}
    base = run_diff(ra, rb, r_off2)
    new = run_diff(ra, rb, rules)
    print("  关闭:", counts(base))
    print("  启用:", counts(new))

    ms_rows = [d for d in new if any("型号集合" in f for f in d.changed_fields)]
    pend = [d for d in new if d.pair_reason and "部分重叠" in d.pair_reason]
    print(f"  型号集合新配对 = {len(ms_rows)} 对（自动合并，subset）")
    for d in ms_rows:
        print(f"    {(d.plm.关键件名称 or '')[:16]}")
        print(f"      A: {d.orig.型号[:56]}")
        print(f"      B: {d.plm.型号[:56]}")
        print(f"      {[f for f in d.changed_fields if '型号集合' in f][0][:70]}")
    print(f"  待确认(部分重叠) = {len(pend)} 对")
    for d in pend:
        print(f"    {(d.plm.关键件名称 or '')[:16]} | {d.pair_reason[:52]}")

    # 守恒必须保持
    au = run_audit(ra, rb, new, {d.key: "accept" for d in new})
    print(f"  审计: a_conserved={au.a_conserved} b_conserved={au.b_conserved}")
    assert au.a_conserved and au.b_conserved, "型号集合匹配不得破坏守恒"

    print("\nTEST_MODEL_SET_MATCH_DONE")


if __name__ == "__main__":
    main()
