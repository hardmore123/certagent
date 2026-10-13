"""验证 LLM fuzzy 候选提名：
1) 基线（无 proposer）= 纯确定性，保持原行为；
2) mock proposer（模拟 LLM，按同组名称前缀提名，conf=0.9）→ 残余候选配成 CHANGED(待确认)，守恒不破；
3) 阈值：conf<0.8 的提名不被接受；
4) 可选：真 LLM 提名分析（设环境 RUN_REAL_LLM=1 且 .env 配好时）。
"""
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# .env 必须在导入 compare_core.config 之前加载（config 在 import 时读环境变量）
if os.getenv("RUN_REAL_LLM") == "1":
    _env = ROOT / ".env"
    if _env.exists():
        for _line in _env.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

from compare_core.differ import run_audit, run_diff
from compare_core.differ.normalize import normalize
from compare_core.models import DiffType
from compare_core.parser.docx_parser import parse_docx
from compare_core.rules import load_rules

FOLDER = ROOT.parent / "AI智能体-认证原始清单与新品清单合并"
ORIG = FOLDER / "输入--【原始清单，人工已整理docx】4720467-85Z970QF(东芝)_安全&EMC关键件清单.docx"
PLM = FOLDER / "输入--【PLM导出清单-新品docx】85ZXSF(01)(东芝)_安全&EMC关键件清单 - 副本.docx"


def _counts(diffs):
    return dict(Counter(d.type.value for d in diffs))


def _mock_proposer(conf=0.9):
    """模拟 LLM：对未配对残余，按同表同组 + 名称前缀关系提名（一对一）。"""
    def proposer(unmatched_orig, unmatched_plm):
        pairs = []
        used_p = set()
        for oi, o in enumerate(unmatched_orig):
            no = normalize(o.关键件名称)
            if len(no) < 3:
                continue
            for pi, p in enumerate(unmatched_plm):
                if pi in used_p:
                    continue
                if p.table != o.table:
                    continue
                if normalize(p.group, drop_space=False) != normalize(o.group, drop_space=False):
                    continue
                np_ = normalize(p.关键件名称)
                if len(np_) < 3 or no == np_:
                    continue
                short, long = (no, np_) if len(no) <= len(np_) else (np_, no)
                if long.startswith(short):
                    pairs.append((oi, pi, conf, f"名称前缀关系：{o.关键件名称} < {p.关键件名称}"))
                    used_p.add(pi)
                    break
        return pairs
    return proposer


def main():
    rules = load_rules()
    rows_orig = parse_docx(str(ORIG))
    rows_plm = parse_docx(str(PLM))
    print(f"输入 A={len(rows_orig)} 行, B={len(rows_plm)} 行")

    # 1) 基线：无 proposer
    base = run_diff(rows_orig, rows_plm, rules)
    print("\n[1] 基线(纯确定性):", _counts(base))
    a1 = run_audit(rows_orig, rows_plm, base, {d.key: "accept" for d in base})
    print(f"    审计 a_conserved={a1.a_conserved} b_conserved={a1.b_conserved}")
    assert a1.a_conserved and a1.b_conserved

    # 2) mock proposer（conf=0.9 >= 阈值）
    diffs = run_diff(rows_orig, rows_plm, rules, fuzzy_proposer=_mock_proposer(0.9))
    print("\n[2] +mock proposer(conf=0.9):", _counts(diffs))
    nominated = [d for d in diffs if d.pair_reason]
    print(f"    LLM提名配对数={len(nominated)}")
    for d in nominated[:5]:
        print(f"      A『{d.orig.关键件名称[:16]}』-> B『{d.plm.关键件名称[:24]}』 conf={d.pair_confidence} | {d.pair_reason[:40]}")
        assert d.type == DiffType.CHANGED
        assert "(AI疑似同一件)" in d.changed_fields
    # 提名后应减少 only_orig/only_plm，增加 changed
    assert _counts(diffs).get("only_orig", 0) < _counts(base).get("only_orig", 0)
    assert _counts(diffs).get("only_plm", 0) < _counts(base).get("only_plm", 0)

    # 守恒：提名后审计仍守恒（每行仍被唯一 diff 引用）
    a2 = run_audit(rows_orig, rows_plm, diffs, {d.key: "accept" for d in diffs})
    print(f"    审计 a_conserved={a2.a_conserved} b_conserved={a2.b_conserved} status={a2.status}")
    assert a2.a_conserved and a2.b_conserved, "提名后守恒被破坏！"

    # 3) 阈值：conf=0.5 < 0.8 → 不接受，回到基线
    low = run_diff(rows_orig, rows_plm, rules, fuzzy_proposer=_mock_proposer(0.5), fuzzy_threshold=0.8)
    print("\n[3] +mock proposer(conf=0.5, 阈值0.8):", _counts(low))
    assert not [d for d in low if d.pair_reason], "低置信提名不应被接受"
    assert _counts(low) == _counts(base), "低置信应等同基线"

    # 3.5) 拒绝配对(unpair) → 拆开保留，不丢行；守恒仍成立
    from compare_core.differ import resolve_effective_diffs
    paired = run_diff(rows_orig, rows_plm, rules, fuzzy_proposer=_mock_proposer(0.9))
    pair_diff = next(d for d in paired if d.pair_reason)
    dec_unpair = {d.key: "accept" for d in paired}
    dec_unpair[pair_diff.key] = "unpair"
    eff = resolve_effective_diffs(paired, dec_unpair)
    print("\n[3.5] 拒绝配对(unpair)拆开保留:")
    print(f"    配对前有效行={len([d for d in paired])}, unpair后有效行={len(eff)}")
    # unpair 把 1 个 CHANGED 拆成 2 行(ONLY_PLM+ONLY_ORIG)，总行 +1
    assert len(eff) == len(paired) + 1, "unpair 应拆成两行(总行+1)"
    split_types = {d.type.value for d in eff if d.key in (pair_diff.key + "-p", pair_diff.key + "-o")}
    print(f"    拆出类型={split_types}")
    assert split_types == {"only_plm", "only_orig"}, "应拆成 only_plm + only_orig"
    assert not any(d.key == pair_diff.key for d in eff), "原配对行应已被拆解"
    a35 = run_audit(rows_orig, rows_plm, paired, dec_unpair)
    print(f"    审计 a_conserved={a35.a_conserved} b_conserved={a35.b_conserved} 输出缺失={len(a35.missing_in_output)}")
    assert a35.a_conserved and a35.b_conserved

    # 3.6) 别名沉淀：接受配对写入反馈 → mine_aliases 挖出别名
    import os as _os, tempfile
    from compare_core import config as _cfgmod
    from compare_core.memory import mine_aliases, record_decisions
    _tmp = Path(tempfile.mkdtemp()) / "feedback.jsonl"
    _old = _cfgmod.config.FEEDBACK_FILE
    _cfgmod.config.FEEDBACK_FILE = _tmp
    try:
        record_decisions({d.key: d.model_dump() for d in paired},
                         {pair_diff.key: "accept"})
        aliases = mine_aliases()
        print("\n[3.6] 别名沉淀:", aliases)
        assert any(a["orig_name"] == "电线组件" for a in aliases), "应挖出电线组件别名"
    finally:
        _cfgmod.config.FEEDBACK_FILE = _old

    # 4) 可选：真 LLM 提名分析
    if os.getenv("RUN_REAL_LLM") == "1":
        print("\n[4] 真 LLM fuzzy 提名分析:")
        from compare_core.suggester.llm_suggester import LLMSuggester
        real = run_diff(rows_orig, rows_plm, rules,
                        fuzzy_proposer=LLMSuggester().propose_fuzzy_pairs)
        print("    结果:", _counts(real))
        rn = [d for d in real if d.pair_reason]
        print(f"    真LLM提名配对数={len(rn)}")
        for d in rn:
            print(f"      A『{d.orig.关键件名称[:16]}』-> B『{d.plm.关键件名称[:24]}』 conf={d.pair_confidence} | {d.pair_reason[:50]}")
        ar = run_audit(rows_orig, rows_plm, real, {d.key: "accept" for d in real})
        print(f"    审计 a_conserved={ar.a_conserved} b_conserved={ar.b_conserved}")
    else:
        print("\n[4] 跳过真 LLM（设 RUN_REAL_LLM=1 启用）")

    print("\nTEST_FUZZY_PROPOSE_DONE")


if __name__ == "__main__":
    main()
