"""顺序编排（核心，无 LangGraph 依赖）：供 CLI 与测试使用。

review_fn: 人在环回调，签名 (diffs, suggestions) -> decisions(dict: key->verdict)。
"""
from __future__ import annotations

from typing import Callable

from . import trace
from .nodes import (
    apply_node,
    audit_node,
    judge_node,
    memory_node,
    parse_node,
    repair_node,
    suggest_node,
)

ReviewFn = Callable[[list, list], dict]


def run_pipeline(state: dict, review_fn: ReviewFn) -> dict:
    trace.new_run()
    state.update(parse_node(state))
    state.update(judge_node(state))
    state.update(suggest_node(state))
    # 人在环：判断 -> 建议 -> [人确认] -> 修改
    state["decisions"] = review_fn(state["diffs"], state["suggestions"])
    trace.dump("decisions", state["decisions"])
    state.update(apply_node(state))
    # 数据守恒审计 + 补录（与 LangGraph 图一致）
    state.update(audit_node(state))
    if state.get("audit_report") and state["audit_report"].status == "critical":
        state.update(repair_node(state))
    state.update(memory_node(state))
    return state
