"""端到端：python-docx 解析真实 docx → diff → group_diff → suggest → 生成 Word。

完全不依赖 Word COM。
"""
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from compare_core import nodes, trace
from compare_core.parser.docx_parser import parse_docx

FOLDER = ROOT.parent / "AI智能体-认证原始清单与新品清单合并"
ORIG = FOLDER / "输入--【原始清单，人工已整理docx】4720467-85Z970QF(东芝)_安全&EMC关键件清单.docx"
PLM = FOLDER / "输入--【PLM导出清单-新品docx】85ZXSF(01)(东芝)_安全&EMC关键件清单 - 副本.docx"
OUT = ROOT / "runs" / "docx_e2e_2026-07-28"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    trace.new_run()

    print("[1] 解析（python-docx，无 COM）...")
    rows_orig = parse_docx(str(ORIG))
    rows_plm = parse_docx(str(PLM))
    print(f"    orig={len(rows_orig)} 行, plm={len(rows_plm)} 行")

    state = {
        "rows_orig": rows_orig,
        "rows_plm": rows_plm,
        "mode": "mock",
        "suggest_source": "groups",
        "out_dir": str(OUT),
    }

    print("[2] judge（行级 diff + 组级 diff）...")
    state.update(nodes.judge_node(state))
    diff_counts = Counter(d.type.value for d in state["diffs"])
    group_counts = Counter(g.status.value for g in state["group_diffs"])
    print(f"    行级 diff: {dict(diff_counts)}")
    print(f"    组级 diff: {dict(group_counts)}")

    print("[3] suggest（组级归纳，mock）...")
    state.update(nodes.suggest_node(state))
    print(f"    对照表条目: {len(state['changes'])}")
    for c in state["changes"]:
        print(f"      - {c.变更项目}")

    print("[4] apply（全部接受，生成 Word）...")
    state["decisions"] = {d.key: "accept" for d in state["diffs"]}
    state.update(nodes.apply_node(state))
    print(f"    整合清单: {state['out_merged']}")
    print(f"    对照表:   {state['out_compare']}")

    print("\nTEST_DOCX_E2E_OK")


if __name__ == "__main__":
    main()
