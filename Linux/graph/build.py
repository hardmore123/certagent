"""用 LangGraph 把 compare_core 的节点串成状态图，human_review 用 interrupt 实现人在环。

流程：parse -> judge -> suggest -> human_review(interrupt) -> apply -> audit
      -> [条件边] critical? -> repair -> memory / 否则直接 -> memory
CLI 侧捕获中断、收集用户决策、通过 Command(resume=...) 恢复。

audit（数据守恒审计）在 apply 之后校验输入 A/B 每一行是否被保留或按决策处理；
若判定 critical（引擎丢行/物理少行）则走 repair 补录分支，否则直接进 memory。
"""
from __future__ import annotations

from typing import Any, TypedDict

from compare_core.nodes import (
    apply_node,
    audit_node,
    judge_node,
    memory_node,
    parse_node,
    repair_node,
    suggest_node,
)


class GraphState(TypedDict, total=False):
    file_orig: str
    file_plm: str
    rows_orig_json: str
    rows_plm_json: str
    mode: str
    out_dir: str
    rows_orig: Any
    rows_plm: Any
    diffs: Any
    suggestions: Any
    changes: Any
    rules: Any
    decisions: dict
    out_merged: str
    out_compare: str
    audit_report: Any
    audit_repaired: bool


def _human_review(state: GraphState) -> dict:
    from langgraph.types import interrupt

    # 把差异与建议抛给外部（CLI），等待用户决策 dict: key -> verdict
    decisions = interrupt({
        "diffs": [d.model_dump() for d in state["diffs"]],
        "suggestions": [s.model_dump() for s in state["suggestions"]],
    })
    return {"decisions": decisions or {}}


def _route_after_audit(state: GraphState) -> str:
    """审计后路由：critical（引擎丢行/物理少行）→ repair 补录；否则直接 → memory。"""
    report = state.get("audit_report")
    if report is not None and getattr(report, "status", "ok") == "critical":
        return "repair"
    return "memory"


def build_graph():
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, START, StateGraph

    g = StateGraph(GraphState)
    g.add_node("parse", parse_node)
    g.add_node("judge", judge_node)
    g.add_node("suggest", suggest_node)
    g.add_node("human_review", _human_review)
    g.add_node("apply", apply_node)
    g.add_node("audit", audit_node)
    g.add_node("repair", repair_node)
    g.add_node("memory", memory_node)

    g.add_edge(START, "parse")
    g.add_edge("parse", "judge")
    g.add_edge("judge", "suggest")
    g.add_edge("suggest", "human_review")
    g.add_edge("human_review", "apply")
    g.add_edge("apply", "audit")
    # 条件边：审计发现 critical 丢失 → repair 补录 → memory；否则直接 → memory
    g.add_conditional_edges("audit", _route_after_audit, {"repair": "repair", "memory": "memory"})
    g.add_edge("repair", "memory")
    g.add_edge("memory", END)

    return g.compile(checkpointer=MemorySaver())
