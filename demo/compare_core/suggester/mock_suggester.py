"""Mock suggester：不调 LLM 的两条归纳路径。

- summarize_changes：老路径，按关键件名称朴素归纳（每条 diff 一个动作）
- summarize_from_groups：新路径，按业务 5 类模板从组级 diff 归纳（三.12 实验验证 5/5 覆盖）
"""
from __future__ import annotations

from ..models import ChangeEntry, DiffItem, DiffType, GroupDiff, GroupStatus

_BOARD_KEYS = ("主板", "pcb", "调谐", "天线", "网卡", "显示屏")
_POWER_HINT = "电源单元"


def _fmt_selections(g: GroupDiff) -> str:
    return f"{g.orig_selections}→{g.plm_selections}"


class MockSuggester:
    def summarize_changes(self, diffs: list[DiffItem], rules: dict) -> list[ChangeEntry]:
        buckets: dict[str, list[str]] = {}
        for d in diffs:
            if d.type not in (DiffType.ONLY_PLM, DiffType.CHANGED):
                continue
            row = d.plm or d.orig
            name = (row.关键件名称 if row else "") or "其它"
            desc = f"型号:{row.型号} 规格:{row.规格材料}".strip() if row else ""
            buckets.setdefault(name, []).append(desc)
        entries: list[ChangeEntry] = []
        for name, items in buckets.items():
            joined = "；".join(x for x in items if x)
            entries.append(ChangeEntry(变更项目=f"增加/变更：{name}", 变更前="见原报告",
                                       变更后=f"见原报告 增加：{joined}"))
        return entries

    def summarize_from_groups(self, group_diffs: list[GroupDiff], rules: dict) -> list[ChangeEntry]:
        """按业务 5 类模板归纳（三.12 实验验证 5/5 覆盖东芝样例）。

        规则按"表号 → 分组标题 → 关键件名称"三层级联，分类边界严格：
        - 表 2 的非 SAME 组 → 类别 1（产品型号规格）
        - 表 1 分组含"电源单元"的 ONLY_PLM_GROUP → 类别 2（电源单元备选件）
        - 表 1 顶层组名含 主板/PCB/调谐/天线/网卡/显示屏 → 类别 3
        - 其他 REPLACED_GROUP 且行数相同、少量替换 → 类别 4（供应商）
        - 类别 5 照片始终输出 [外部输入] 占位
        """
        entries: list[ChangeEntry] = []
        active = [g for g in group_diffs if g.status != GroupStatus.SAME_GROUP]

        # 类别 1：表 2 主项变更
        t2_active = [g for g in active if g.table == 2]
        if t2_active:
            details = "、".join(
                f"{g.关键件名称}({g.status.value.upper()} 选型 {_fmt_selections(g)})" for g in t2_active
            )
            entries.append(ChangeEntry(
                变更项目="增加产品型号规格",
                变更前="见原报告",
                变更后=f"表2 机型主项变更：{details}",
            ))

        # 类别 2：机内电源单元备选件
        t1_active = [g for g in active if g.table == 1]
        power_new = [g for g in t1_active if _POWER_HINT in g.group and g.status == GroupStatus.ONLY_PLM_GROUP]
        power_old_group = next(
            (g.group for g in t1_active if _POWER_HINT in g.group and g.status == GroupStatus.ONLY_ORIG_GROUP),
            "",
        )
        new_power_group = next((g.group for g in power_new), "")
        if power_new:
            details = "、".join(f"{g.关键件名称}({g.plm_selections} 款)" for g in power_new)
            note = f"（原 {power_old_group} 换型为 {new_power_group}）" if power_old_group else ""
            entries.append(ChangeEntry(
                变更项目="增加机内电源单元备选件",
                变更前="见原报告",
                变更后=f"新增子件：{details}{note}",
            ))

        # 类别 3：主板类备选件
        board_groups = [
            g for g in t1_active
            if not g.group and any(k in g.关键件名称 for k in _BOARD_KEYS)
        ]
        if board_groups:
            details = "、".join(
                f"{g.关键件名称}({g.status.value.upper()} 选型 {_fmt_selections(g)})"
                for g in board_groups
            )
            entries.append(ChangeEntry(
                变更项目="增加主板（含网卡、调谐单元、天线隔离器）备选件",
                变更前="见原报告",
                变更后=f"变更子项：{details}",
            ))

        # 类别 4：供应商替换（排除主板 + 电源单元分组）
        board_names = {g.关键件名称 for g in board_groups}
        supplier = [
            g for g in t1_active
            if g.status == GroupStatus.REPLACED_GROUP
            and g.orig_selections == g.plm_selections
            and 1 <= g.only_orig_selections <= 3
            and g.关键件名称 not in board_names
            and _POWER_HINT not in g.group
        ]
        if supplier:
            details = "、".join(f"{g.关键件名称}(替换 {g.only_orig_selections} 家)" for g in supplier)
            entries.append(ChangeEntry(
                变更项目="补充/更新供应商信息",
                变更前="见原报告",
                变更后=f"供应商替换：{details}",
            ))

        # 类别 5：照片始终占位
        entries.append(ChangeEntry(
            变更项目="增加整机外观、内部结构、主板、电源板等照片",
            变更前="见原报告",
            变更后="[外部输入] 需业务提供照片，本次合并的关键件清单无法推导",
        ))

        return entries
