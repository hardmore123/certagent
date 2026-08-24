"""CLI 入口：变更-开发 清单整合 Demo。

示例：
  # 用 doc 文件、mock、核心引擎跑通
  python cli.py --orig 原报告清单.doc --plm PLM导出清单.doc --out runs/out
  # 用真 LLM 归纳对照表
  python cli.py --orig a.doc --plm b.doc --out runs/out --mode llm
  # 用 LangGraph 编排 + fixture
  python cli.py --orig-json orig.json --plm-json plm.json --out runs/out --engine graph
"""
from __future__ import annotations

import argparse

from compare_core.models import Confidence, DiffType

_AUTO_ACCEPT = {DiffType.SAME}  # 只有 SAME 自动接受；ONLY_ORIG/ONLY_PLM/CHANGED 都需人工确认


def _fmt_row(d) -> str:
    row = d.get("plm") or d.get("orig") or {}
    return f"{row.get('关键件名称','')} | {row.get('型号','')} | {row.get('规格材料','')[:40]}"


def cli_review(diffs, suggestions) -> dict:
    """人在环：新增/差异项逐个问 y/n；其余自动接受。diffs/suggestions 为 dict 列表或对象。"""
    def as_dict(x):
        return x if isinstance(x, dict) else x.model_dump()

    diffs = [as_dict(d) for d in diffs]
    sugg_by_key = {as_dict(s)["diff_key"]: as_dict(s) for s in suggestions}
    decisions: dict[str, str] = {}

    review_items = [d for d in diffs if d["type"] not in {t.value for t in _AUTO_ACCEPT}]
    print(f"\n=== 差异确认：共 {len(diffs)} 项，需人工确认 {len(review_items)} 项（新增/差异）===")
    for d in diffs:
        if d["type"] in {t.value for t in _AUTO_ACCEPT}:
            decisions[d["key"]] = "accept"
    for i, d in enumerate(review_items, 1):
        s = sugg_by_key.get(d["key"], {})
        print(f"\n[{i}/{len(review_items)}] 类型={d['type']} 置信度={d.get('confidence')}")
        print(f"  内容: {_fmt_row(d)}")
        print(f"  AI建议: {s.get('action')} — {s.get('reason')}  (规则:{s.get('rule_id')})")
        ans = input("  接受该建议？[Y/n]: ").strip().lower()
        decisions[d["key"]] = "reject" if ans == "n" else "accept"
    return decisions


def run_core(args):
    from compare_core.pipeline import run_pipeline

    state = _init_state(args)
    state = run_pipeline(state, cli_review)
    _report(state)


def run_graph(args):
    from langgraph.types import Command

    from graph.build import build_graph

    app = build_graph()
    cfg = {"configurable": {"thread_id": "demo-1"}}
    state = _init_state(args)
    result = app.invoke(state, cfg)
    # 命中 interrupt 则收集决策并恢复
    intr = result.get("__interrupt__")
    if intr:
        payload = intr[0].value
        decisions = cli_review(payload["diffs"], payload["suggestions"])
        result = app.invoke(Command(resume=decisions), cfg)
    _report(result)


def _init_state(args) -> dict:
    return {
        "file_orig": args.orig, "file_plm": args.plm,
        "rows_orig_json": args.orig_json, "rows_plm_json": args.plm_json,
        "mode": args.mode, "out_dir": args.out,
        "suggest_source": "groups" if args.use_groups else "rows",
    }


def _report(state: dict):
    print("\n=== 完成 ===")
    print(f"整合清单: {state.get('out_merged')}")
    print(f"对照表:   {state.get('out_compare')}")


def main():
    p = argparse.ArgumentParser(description="变更-开发 清单整合 Demo")
    p.add_argument("--orig", help="原报告清单 .doc/.docx")
    p.add_argument("--plm", help="PLM导出清单 .doc/.docx")
    p.add_argument("--orig-json", dest="orig_json", help="原报告清单 fixture(json)")
    p.add_argument("--plm-json", dest="plm_json", help="PLM导出清单 fixture(json)")
    p.add_argument("--out", default="runs/out", help="输出目录")
    p.add_argument("--mode", choices=["mock", "llm"], default="mock", help="suggester 模式")
    p.add_argument("--engine", choices=["core", "graph"], default="core", help="核心顺序编排 or LangGraph")
    p.add_argument("--use-groups", action="store_true",
                   help="对照表用组级 diff 归纳（业务模板对齐 5/5）；默认行级归纳")
    args = p.parse_args()

    if args.engine == "graph":
        run_graph(args)
    else:
        run_core(args)


if __name__ == "__main__":
    main()
