"""节点函数：判断/建议/修改/记忆。单一事实源，pipeline 与 LangGraph 图共用。

每个函数接收 state(dict)，返回要合并进 state 的局部更新(dict)。
"""
from __future__ import annotations

from pathlib import Path

from . import trace
from .differ import run_audit, run_diff, run_group_diff
from .memory import record_decisions
from .models import DiffItem
from .parser import load_rows_json, parse_document
from .rules import load_rules
from .suggester import get_suggester, rule_suggest
from .writer import append_audit_supplement, write_compare_table, write_merged_list


def parse_node(state: dict) -> dict:
    def _load(path_key: str, json_key: str):
        if state.get(json_key):
            return load_rows_json(state[json_key])
        return parse_document(state[path_key])

    rows_orig = _load("file_orig", "rows_orig_json")
    rows_plm = _load("file_plm", "rows_plm_json")
    trace.dump("parse_orig", rows_orig)
    trace.dump("parse_plm", rows_plm)

    # 解析出 PLM(新版本=输出骨架) 的 .docx 路径，供 apply 阶段作格式模板。
    # fixture(json) 无模板；.doc 复用解析时已转换的 .docx，失败则不设模板（回退默认排版）。
    out: dict = {"rows_orig": rows_orig, "rows_plm": rows_plm}
    plm_path = state.get("file_plm")
    if plm_path and not state.get("rows_plm_json"):
        from pathlib import Path as _P
        try:
            if _P(plm_path).suffix.lower() == ".docx":
                out["template_docx"] = plm_path
            else:
                from .parser.converter import ensure_docx
                out["template_docx"] = ensure_docx(plm_path)
        except Exception:  # noqa: BLE001 - 无模板不影响生成
            pass
    return out


def judge_node(state: dict) -> dict:
    rules = load_rules()
    # 可选：LLM fuzzy 候选提名（state["fuzzy_llm"]=True 时启用；默认纯确定性）。
    # 与对照表归纳的 mode 解耦：即使 summarizer 用 mock，fuzzy 也可单独用 LLM 提名。
    # LLM 未配置时 propose_fuzzy_pairs 返回 []，不影响主流程。
    fuzzy_proposer = None
    if state.get("fuzzy_llm"):
        from .suggester.llm_suggester import LLMSuggester
        fuzzy_proposer = LLMSuggester().propose_fuzzy_pairs
    threshold = float(state.get("fuzzy_threshold", 0.8))
    diffs = run_diff(state["rows_orig"], state["rows_plm"], rules,
                     fuzzy_proposer=fuzzy_proposer, fuzzy_threshold=threshold)
    trace.dump("diff", diffs)
    # 顺带产出组级 diff，放进 state 供下游按需消费（不影响现有 writer/suggester 路径）
    group_diffs = run_group_diff(state["rows_orig"], state["rows_plm"], diffs)
    trace.dump("group_diffs", group_diffs)
    return {"diffs": diffs, "group_diffs": group_diffs, "rules": rules}


def suggest_node(state: dict) -> dict:
    diffs: list[DiffItem] = state["diffs"]
    rules = state.get("rules") or load_rules()
    suggestions = rule_suggest(diffs)
    suggester = get_suggester(state.get("mode", "mock"))
    # 分派：`suggest_source="groups"` 时用组级归纳（三.12 验证 5/5），否则走老路径
    if state.get("suggest_source", "rows") == "groups" and state.get("group_diffs"):
        changes = suggester.summarize_from_groups(state["group_diffs"], rules)
    else:
        changes = suggester.summarize_changes(diffs, rules)
    trace.dump("suggestions", suggestions)
    trace.dump("changes", changes)
    return {"suggestions": suggestions, "changes": changes}


def apply_node(state: dict) -> dict:
    out_dir = Path(state.get("out_dir", "."))
    out_dir.mkdir(parents=True, exist_ok=True)
    decisions: dict[str, str] = state.get("decisions", {})
    merged = write_merged_list(state["diffs"], decisions, str(out_dir / "整合版关键件清单.docx"),
                               template_docx=state.get("template_docx"))
    compare = write_compare_table(state["changes"], str(out_dir / "变更前后对照表.docx"))
    return {"out_merged": merged, "out_compare": compare}


def audit_node(state: dict) -> dict:
    """数据守恒审计：校验 A/B 每行是否在整合结果中保留或按决策处理（apply 之后）。"""
    report = run_audit(
        state["rows_orig"], state["rows_plm"], state["diffs"],
        state.get("decisions", {}), state.get("out_merged"),
    )
    trace.dump("audit", report)
    return {"audit_report": report}


def repair_node(state: dict) -> dict:
    """补录：把审计判定为引擎丢行的 A/B 行追加到整合文档末尾附录，保证零物理丢失。

    仅处理"未被任何 diff 引用"的引擎丢行（可精确定位）。物理层 writer 丢行无法逐行定位，
    由审计报告的建议交人工复核。
    """
    report = state.get("audit_report")
    out_merged = state.get("out_merged")
    if not report or report.status != "critical" or not out_merged:
        return {}
    # 引擎丢行（未被任何 diff 引用）+ writer 丢行（保留但输出缺失，按指纹定位）
    lost = list(report.lost_orig) + list(report.lost_plm) + list(report.missing_in_output)
    if not lost:
        return {}
    append_audit_supplement(out_merged, lost)
    n_lost = len(lost)

    # 补录后重新审计：让报告反映补录**之后**的真实状态，
    # 否则报告仍是补录前快照（missing 数字未清零、status 仍 critical），容易误读。
    # state 不完整时（如仅传 audit_report+out_merged 的最小调用）优雅降级：只标记不重审。
    rows_orig, rows_plm, diffs = state.get("rows_orig"), state.get("rows_plm"), state.get("diffs")
    if rows_orig is not None and rows_plm is not None and diffs is not None:
        report = run_audit(rows_orig, rows_plm, diffs, state.get("decisions", {}), out_merged)
        report.details.append(
            f"[补录] 已将 {n_lost} 行疑似丢失行追加到整合文档末尾附录（本报告为补录后重审结果）。")
        if report.status == "ok":
            report.recommendations.insert(
                0, f"已自动补录 {n_lost} 行疑似丢失行到文档末尾附录，补录后复审通过：信息零丢失，请人工核对附录内容。")
    else:
        report.details.append(f"[补录] 已将 {n_lost} 行疑似丢失行追加到整合文档末尾附录（未重审：state 不完整）。")
    report.repaired = True
    trace.dump("audit_repaired", report)
    return {"audit_report": report, "audit_repaired": True}


def memory_node(state: dict) -> dict:
    from .differ.resolve import parse_decision

    diffs_by_key = {d.key: d.model_dump() for d in state["diffs"]}
    # 决策载荷可能是 str 或 {verdict,target_key,reason}：归一化为 verdict 串 + 合并理由后落盘。
    raw = state.get("decisions", {}) or {}
    ext_reasons = dict(state.get("reasons", {}) or {})
    verdicts: dict[str, str] = {}
    for key, entry in raw.items():
        verdict, _target, reason = parse_decision(entry)
        verdicts[key] = verdict
        if reason and key not in ext_reasons:
            ext_reasons[key] = reason
    # reasons: {diff_key: 拒绝/接受理由}，随决策一并落盘，供记忆反哺与拒绝挖掘。
    record_decisions(diffs_by_key, verdicts, ext_reasons)
    return {}
