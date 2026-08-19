"""Suggester 抽象 + 工厂 + 共享的规则化建议生成。

分工：
- 每个 diff 的"建议动作"是确定性的 -> rule_suggest（mock/llm 共用）。
- 对照表"变更项归纳"是语义活 -> 各 Suggester 提供两条通路：
  · summarize_changes(diffs, rules)：行级差异归纳（老路径，向后兼容）
  · summarize_from_groups(group_diffs, rules)：组级差异归纳（新路径，与业务模板对齐）
"""
from __future__ import annotations

from typing import Optional, Protocol

from ..config import config
from ..models import ChangeEntry, Confidence, DiffItem, DiffType, GroupDiff, MemoryHint, Suggestion


def _base_suggest(d: DiffItem) -> Suggestion:
    """基于 diff 类型的确定性建议动作（未叠加记忆）。"""
    if d.type == DiffType.SAME:
        return Suggestion(diff_key=d.key, action="merge", reason="两侧一致，合并保留一份",
                          confidence=d.confidence)
    if d.type == DiffType.ONLY_PLM:
        return Suggestion(diff_key=d.key, action="mark_new", reason="仅 PLM 导出，新增项，标红加粗+备注来源",
                          rule_id="annotate.only_plm", confidence=d.confidence)
    if d.type == DiffType.CHANGED:
        return Suggestion(diff_key=d.key, action="mark_diff",
                          reason=f"内容差异字段：{', '.join(d.changed_fields)}",
                          rule_id="annotate.changed", confidence=d.confidence)
    # ONLY_ORIG
    return Suggestion(diff_key=d.key, action="merge", reason="仅原报告，保留，备注来源",
                      rule_id="annotate.only_orig", confidence=d.confidence)


def _apply_memory(sugg: Suggestion, hint: MemoryHint) -> Suggestion:
    """把历史决策叠加到建议上：强否→预置 ignore/降置信；强认→升置信。

    记忆是"建议"非"强制"——仅改动作/理由/置信度，最终仍由人工在确认页决策。
    """
    if hint.dominant == "reject":
        # 历史上这个"件+差异类型"被反复否决：默认预置为忽略，提醒人工复核。
        sugg.action = "ignore"
        note = f"记忆：该项历史被否决 {hint.rejects} 次"
        if hint.last_reason:
            note += f"（近因：{hint.last_reason}）"
        sugg.reason = f"{note}；已预置忽略，请确认。原建议：{sugg.reason}"
        sugg.confidence = Confidence.LOW
        sugg.rule_id = "memory.reject"
        sugg.memory_applied = True
    elif hint.dominant == "accept":
        # 历史上反复被确认：提升置信度，减少重复确认成本。
        sugg.reason = f"{sugg.reason}（记忆：历史确认 {hint.accepts} 次，一致）"
        sugg.confidence = Confidence.HIGH
        sugg.rule_id = (sugg.rule_id or "") + "+memory.accept"
        sugg.memory_applied = True
    sugg.memory_hint = hint
    return sugg


def rule_suggest(
    diffs: list[DiffItem],
    hints: Optional[dict[str, MemoryHint]] = None,
) -> list[Suggestion]:
    """基于 diff 类型给出确定性建议动作，并叠加长期记忆反哺。

    hints: {diff_key: MemoryHint}。为 None 且 config.MEMORY_ENABLED 时内部按需构建，
    使 suggest_node 与 webapi.get_diffs 等各调用点无需改动即可享受记忆反哺。
    """
    if hints is None and config.MEMORY_ENABLED:
        try:
            from ..memory import build_hints
            hints = build_hints(diffs)
        except Exception:  # noqa: BLE001 - 记忆不可用不阻断主流程
            hints = {}
    hints = hints or {}

    out: list[Suggestion] = []
    for d in diffs:
        sugg = _base_suggest(d)
        hint = hints.get(d.key)
        if hint is not None and hint.dominant:
            sugg = _apply_memory(sugg, hint)
        out.append(sugg)
    return out


class Suggester(Protocol):
    def summarize_changes(self, diffs: list[DiffItem], rules: dict) -> list[ChangeEntry]:
        ...

    def summarize_from_groups(self, group_diffs: list[GroupDiff], rules: dict) -> list[ChangeEntry]:
        ...


def get_suggester(mode: str) -> "Suggester":
    if mode == "llm":
        from .llm_suggester import LLMSuggester

        return LLMSuggester()
    from .mock_suggester import MockSuggester

    return MockSuggester()
