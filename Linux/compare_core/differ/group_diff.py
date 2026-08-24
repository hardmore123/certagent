"""关键件组级差异聚合。

组键：`(表号, 分组标题, 关键件名称)`。
组内选型键：`(型号, 位号, 规格材料, 证书号)`。

从行级 `Row` 或 `DiffItem` 聚合成 `GroupDiff`，作为 `differ` 的第二层输出：
- 行级 diff 用于清单整合的物理行输出（`write_merged_list`）
- 组级 diff 用于对照表业务归纳（`suggest` LLM 归纳）

设计原则：**不改** `run_diff()` 与现有主流水线，只提供并行 API。
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable

from ..models import DiffItem, DiffType, GroupDiff, GroupStatus, Row
from .normalize import normalize


def _group_key(row: Row) -> tuple[int, str, str]:
    return (row.table, normalize(row.group, drop_space=False), normalize(row.关键件名称))


def _selection_key(row: Row) -> tuple[str, str, str, str]:
    return (
        normalize(row.型号),
        normalize(row.位号),
        normalize(row.规格材料),
        normalize(row.证书号),
    )


def _display_group_key(rows: Iterable[Row]) -> tuple[str, str]:
    """从原始 Row 里挑一条非空的分组标题和关键件名称作为展示用。"""
    group = ""
    name = ""
    for r in rows:
        if not group and r.group:
            group = r.group
        if not name and r.关键件名称:
            name = r.关键件名称
        if group and name:
            break
    return group, name


def _status_of(orig_sel: Counter, plm_sel: Counter) -> GroupStatus:
    if not orig_sel:
        return GroupStatus.ONLY_PLM_GROUP
    if not plm_sel:
        return GroupStatus.ONLY_ORIG_GROUP
    only_orig = sum((orig_sel - plm_sel).values())
    only_plm = sum((plm_sel - orig_sel).values())
    if only_orig == 0 and only_plm == 0:
        return GroupStatus.SAME_GROUP
    if only_orig == 0:
        return GroupStatus.EXTENDED_BY_PLM
    if only_plm == 0:
        return GroupStatus.SHRUNK_BY_PLM
    return GroupStatus.REPLACED_GROUP


def _group_rows(rows: list[Row]) -> dict[tuple[int, str, str], list[Row]]:
    out: dict[tuple[int, str, str], list[Row]] = defaultdict(list)
    for r in rows:
        out[_group_key(r)].append(r)
    return out


def run_group_diff(
    rows_orig: list[Row],
    rows_plm: list[Row],
    diffs: list[DiffItem] | None = None,
) -> list[GroupDiff]:
    """从两份行级 Row 聚合出关键件组级差异。

    参数：
    - rows_orig / rows_plm：原报告 / PLM 的行级解析结果
    - diffs（可选）：现有 `run_diff()` 结果。若传入，会把 DiffItem.key 挂到对应 GroupDiff.diff_keys 里，
      方便"从对照表条目回溯到具体物理行"。不传则 diff_keys 为空。

    返回按 (table, group, name) 排序的 GroupDiff 列表。
    """
    g_orig = _group_rows(rows_orig)
    g_plm = _group_rows(rows_plm)

    # 建立 DiffItem 反查索引：group_key -> [diff_key]
    diff_keys_by_group: dict[tuple[int, str, str], list[str]] = defaultdict(list)
    if diffs:
        for d in diffs:
            row = d.plm or d.orig
            if row is None:
                continue
            diff_keys_by_group[_group_key(row)].append(d.key)

    all_keys = sorted(set(g_orig) | set(g_plm))
    result: list[GroupDiff] = []
    for key in all_keys:
        table, _, _ = key
        oset = g_orig.get(key, [])
        pset = g_plm.get(key, [])
        display_group, display_name = _display_group_key(oset + pset)

        o_sel = Counter(_selection_key(r) for r in oset)
        p_sel = Counter(_selection_key(r) for r in pset)
        status = _status_of(o_sel, p_sel)

        gd = GroupDiff(
            key=f"{table}|{display_group}|{display_name}",
            table=table,
            group=display_group,
            关键件名称=display_name,
            status=status,
            orig_rows=len(oset),
            plm_rows=len(pset),
            orig_selections=len(o_sel),
            plm_selections=len(p_sel),
            common_selections=sum((o_sel & p_sel).values()),
            only_orig_selections=sum((o_sel - p_sel).values()),
            only_plm_selections=sum((p_sel - o_sel).values()),
            diff_keys=diff_keys_by_group.get(key, []),
        )
        result.append(gd)
    return result


def to_llm_payload(group_diffs: list[GroupDiff], drop_same: bool = True) -> list[dict]:
    """把组级 diff 序列化成给 LLM 归纳用的最小 payload。

    默认丢弃 SAME_GROUP，减少 prompt 长度；如需完整数据可 `drop_same=False`。
    """
    out = []
    for g in group_diffs:
        if drop_same and g.status == GroupStatus.SAME_GROUP:
            continue
        out.append({
            "table": g.table,
            "group": g.group,
            "name": g.关键件名称,
            "status": g.status.value.upper(),  # 与三.11/三.12 prompt 里使用的字面量一致
            "orig_selections": g.orig_selections,
            "plm_selections": g.plm_selections,
            "common": g.common_selections,
            "only_orig": g.only_orig_selections,
            "only_plm": g.only_plm_selections,
        })
    return out
