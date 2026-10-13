"""输出顺序：把 diff 列表排成"最终文档里的行顺序"。

单一事实源——writer（生成 docx）与 webapi（差异确认页）共用本模块，
保证"确认页看到的顺序"就是"最终文档的顺序"，不会两边漂移。

顺序规则：
1. 先按 decisions 解析出有效行（普通 reject 丢弃；配对 reject/unpair 拆开保留）
2. 表一在前、表二在后（与 writer 输出的两张表一致）
3. 每张表内：PLM(新版本) 行保持原序作骨架；
   旧版本独有行(ONLY_ORIG) 按关键件组插入到对应组末尾，
   并通过名称前缀关系归到骨架组（旧"电线组件" → 新"电线组件(0.5平方毫米...)"）
"""
from __future__ import annotations

from collections import defaultdict

from ..models import DiffItem, DiffType
from .normalize import normalize as _norm
from .resolve import resolve_effective_diffs


def _group_key(d: DiffItem) -> tuple[str, str]:
    """归组键 = (归一化分组标题, 归一化关键件名称)。

    ONLY_ORIG(旧版本独有) 用 orig 侧名称，其他用 PLM 侧名称（新版本骨架）。
    """
    if d.type == DiffType.ONLY_ORIG:
        row = d.orig or d.plm
    else:
        row = d.plm or d.orig
    g = _norm(row.group if row else "", drop_space=False)
    name = _norm(row.关键件名称 if row else "")
    return (g, name)


def display_row(d: DiffItem):
    """与 writer 一致的展示行取值：ONLY_ORIG 取 orig 侧，其余取 PLM 侧。"""
    if d.type == DiffType.ONLY_ORIG:
        return d.orig or d.plm
    return d.plm or d.orig


def reorder_by_group(items: list[DiffItem]) -> list[DiffItem]:
    """把旧版本独有行(ONLY_ORIG)按关键件组插入到对应组末尾，同组聚在一起。

    关键点：
    - 分组键 = (归一化 group, 归一化 关键件名称)，比单纯 group 更细
    - ONLY_ORIG 通过名称前缀关系重映射到骨架组，使旧物料与对应新版本组聚拢
    """
    # PLM(新版本)侧行（SAME/CHANGED/ONLY_PLM）保持原序作骨架
    skeleton = [d for d in items if d.type != DiffType.ONLY_ORIG]
    skeleton_keys: list[tuple[str, str]] = []
    seen_sk: set[tuple[str, str]] = set()
    for d in skeleton:
        k = _group_key(d)
        if k not in seen_sk:
            seen_sk.add(k)
            skeleton_keys.append(k)

    def _remap_old_key(orig_key: tuple[str, str]) -> tuple[str, str]:
        """把旧版本独有行的 key 通过前缀关系重映射到骨架 key。"""
        if orig_key in seen_sk:
            return orig_key
        og, oname = orig_key
        if len(oname) < 3:
            return orig_key
        for sk in skeleton_keys:
            sg, sname = sk
            if sg != og:  # group 必须相同
                continue
            short, long = (oname, sname) if len(oname) <= len(sname) else (sname, oname)
            if short != long and long.startswith(short):
                return sk
        return orig_key

    old_by_key: dict[tuple[str, str], list[DiffItem]] = defaultdict(list)
    for d in items:
        if d.type == DiffType.ONLY_ORIG:
            old_by_key[_remap_old_key(_group_key(d))].append(d)

    # 遍历骨架，在每个关键件组的最后一行之后插入该组的旧版本独有行
    result: list[DiffItem] = []
    emitted_keys: set[tuple[str, str]] = set()
    for i, d in enumerate(skeleton):
        result.append(d)
        key = _group_key(d)
        next_key = _group_key(skeleton[i + 1]) if i + 1 < len(skeleton) else None
        if key != next_key and key not in emitted_keys:
            emitted_keys.add(key)
            result.extend(old_by_key.get(key, []))

    # 骨架里完全没有对应关键件组的旧版本独有行 → 按原序追加，同组聚在一起
    for key, old_items in old_by_key.items():
        if key not in emitted_keys:
            result.extend(old_items)
    return result


def split_tables(diffs: list[DiffItem], decisions: dict[str, str] | None = None
                 ) -> tuple[list[DiffItem], list[DiffItem]]:
    """按决策解析有效行后，分别返回排好序的 表一 / 表二 行列表（writer 用）。"""
    kept = resolve_effective_diffs(diffs, decisions or {})
    t1 = reorder_by_group([d for d in kept if d.table == 1])
    t2 = reorder_by_group([d for d in kept if d.table == 2])
    return t1, t2


def order_for_output(diffs: list[DiffItem], decisions: dict[str, str] | None = None) -> list[DiffItem]:
    """返回单一列表：表一行（按输出序）后接表二行（按输出序）。

    差异确认页用它排序；decisions 为空即"全部接受"假设（决策前的预期顺序）。
    """
    t1, t2 = split_tables(diffs, decisions)
    return t1 + t2
