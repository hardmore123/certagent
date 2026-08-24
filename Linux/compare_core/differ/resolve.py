"""把用户决策(decisions)解析为"有效输出 diff 列表"。

统一 writer 与 audit 的口径，保证两者对"决策后应输出什么"完全一致。

决策载荷（向后兼容）：
- 旧格式：decisions = {diff_key: "accept"|"reject"|...}
- 新格式：decisions = {diff_key: {"verdict": ..., "target_key": ..., "reason": ...}}
  target_key 供"手动匹配"指向另一侧的目标行。

拒绝策略纠正动作（verdict）：
  通用
    - accept / (缺省)         → 原样保留
    - reject                  → 丢弃（普通行）；配对行(pair_reason)则拆开保留（兼容旧 unpair）
    - ignore                  → 同 reject（多来自记忆反哺预置）
  独有项(ONLY_PLM/ONLY_ORIG) 的拒绝——"其实另一侧有对应"
    - reject_dup   (一①)      → 与 target 合并为 SAME（去重保留一份），需 target_key
    - reject_pair  (一②)      → 与 target 手动配对为 CHANGED，需 target_key
  差异项(CHANGED) 的拒绝——"配对判定不对"
    - reject_same  (二①)      → 视为 SAME（合并一份）
    - reject_split (二②/unpair)→ 拆成 ONLY_ORIG + ONLY_PLM 两个独有项
"""
from __future__ import annotations

from ..models import Confidence, DiffItem, DiffType

# 丢弃类
_DROP = {"reject", "ignore"}
# 差异→相同
_TO_SAME = {"reject_same"}
# 差异→拆两独有（含旧 unpair 语义）
_TO_SPLIT = {"reject_split", "unpair"}
# 独有→手动匹配（需 target_key）
_MANUAL = {"reject_dup", "reject_pair"}


def parse_decision(entry) -> tuple[str, str, str]:
    """归一化单条决策为 (verdict, target_key, reason)。兼容 str / dict。"""
    if isinstance(entry, dict):
        return (
            str(entry.get("verdict", "accept") or "accept"),
            str(entry.get("target_key", "") or ""),
            str(entry.get("reason", "") or ""),
        )
    return (str(entry or "accept"), "", "")


def verdict_of(decisions: dict, key: str) -> str:
    """取某 diff 的 verdict 字符串（兼容两种载荷）。"""
    return parse_decision((decisions or {}).get(key))[0]


def _split(d: DiffItem) -> list[DiffItem]:
    """CHANGED / 配对行 → 拆成两个独有项（不丢信息）。"""
    out: list[DiffItem] = []
    if d.plm is not None:
        out.append(DiffItem(key=d.key + "-p", table=d.table, type=DiffType.ONLY_PLM,
                            confidence=Confidence.MEDIUM, plm=d.plm))
    if d.orig is not None:
        out.append(DiffItem(key=d.key + "-o", table=d.table, type=DiffType.ONLY_ORIG,
                            confidence=Confidence.MEDIUM, orig=d.orig))
    return out


def _as_same(d: DiffItem) -> DiffItem:
    """CHANGED → SAME（两侧其实一致，合并保留一份）。"""
    return DiffItem(key=d.key, table=d.table, type=DiffType.SAME,
                    confidence=Confidence.HIGH, orig=d.orig, plm=d.plm, changed_fields=[])


def _pairable(a: DiffItem, b: DiffItem) -> bool:
    """两个独有项是否可手动配对：同表、且一个 ONLY_ORIG 一个 ONLY_PLM。"""
    if a.table != b.table:
        return False
    if a.type not in (DiffType.ONLY_ORIG, DiffType.ONLY_PLM):
        return False
    if b.type not in (DiffType.ONLY_ORIG, DiffType.ONLY_PLM):
        return False
    return {a.type, b.type} == {DiffType.ONLY_ORIG, DiffType.ONLY_PLM}


def _manual_merge(src: DiffItem, tgt: DiffItem, *, as_same: bool) -> DiffItem:
    """把两个独有项合并为一个 SAME(as_same) 或 CHANGED（手动配对）。"""
    orig = src.orig or tgt.orig
    plm = src.plm or tgt.plm
    if as_same:
        return DiffItem(key=src.key, table=src.table, type=DiffType.SAME,
                        confidence=Confidence.HIGH, orig=orig, plm=plm, changed_fields=[])
    # 手动配对为 CHANGED：复用 diff_engine 的字段比对。
    # 手动配对的两行往往型号/名称都不同（正常流程型号是匹配键、必然相同，故 _VERIFY_FIELDS 不含），
    # 这里额外纳入 关键件名称/型号，确保它们的差异也进 changed_fields → 输出文档正确高亮。
    changed: list[str] = ["(整体)"]
    if orig is not None and plm is not None:
        from .diff_engine import _VERIFY_FIELDS, _compare_fields
        fields = ["关键件名称", "型号", *_VERIFY_FIELDS]
        changed = _compare_fields(orig, plm, fields) or ["(整体)"]
    return DiffItem(key=src.key, table=src.table, type=DiffType.CHANGED,
                    confidence=Confidence.MEDIUM, orig=orig, plm=plm,
                    changed_fields=changed, pair_reason="手动匹配")


def resolve_effective_diffs(diffs: list[DiffItem], decisions: dict) -> list[DiffItem]:
    decisions = decisions or {}
    by_key = {d.key: d for d in diffs}

    # ── 预扫描：收集有效的"手动匹配"，登记被合并的目标行（consumed）。
    # merge_plan[src_key] = (target_key, as_same)
    merge_plan: dict[str, tuple[str, bool]] = {}
    consumed: set[str] = set()
    for d in diffs:
        verdict, target_key, _reason = parse_decision(decisions.get(d.key))
        if verdict not in _MANUAL:
            continue
        tgt = by_key.get(target_key)
        # 目标非法（不存在/已被占用/不可配对）→ 忽略该手动匹配（后续原样保留 src）
        if tgt is None or target_key in consumed or d.key in consumed or not _pairable(d, tgt):
            continue
        merge_plan[d.key] = (target_key, verdict == "reject_dup")
        consumed.add(target_key)

    # ── 主遍历：按原序产出有效行。
    out: list[DiffItem] = []
    for d in diffs:
        if d.key in consumed:
            continue  # 已作为某手动匹配的目标被合并
        verdict, _target, _reason = parse_decision(decisions.get(d.key))

        # 手动匹配源：合并 src + target
        if d.key in merge_plan:
            target_key, as_same = merge_plan[d.key]
            out.append(_manual_merge(d, by_key[target_key], as_same=as_same))
            continue

        # 配对行（LLM 提名或手动）被拒 → 拆开保留
        if d.pair_reason and verdict in _DROP | _TO_SPLIT:
            out.extend(_split(d))
            continue
        # 差异②：显式拆两独有
        if verdict in _TO_SPLIT:
            out.extend(_split(d))
            continue
        # 差异①：差异其实相同
        if verdict in _TO_SAME:
            out.append(_as_same(d))
            continue
        # 普通行丢弃
        if verdict in _DROP:
            continue

        out.append(d)
    return out
