"""核对比对：以 A(海信资料) 为基准，检查 B(报告草稿) 是否一致。

匹配键：优先型号(最具区分度)，退化到 关键件名称。
比对字段：制造商 / 生产企业 / 认证标准 / 证书号（可扩展）。
分类：MISSING_IN_REPORT / EXTRA_IN_REPORT / FIELD_MISMATCH / CONSISTENT。
"""
from __future__ import annotations

from ..models import Row, VerifyItem, VerifyReport, VerifyType
from .normalize import norm, norm_std

# 参与内容一致性判定的字段（字段名 -> 归一函数）
_VERIFY_FIELDS = {
    "制造商": norm,
    "生产企业": norm,
    "认证标准": norm_std,
    "证书号": norm,
}


def _match_key(row: Row) -> str:
    """行匹配键：block + 型号(优先) / 关键件名称。"""
    model = norm(row.型号)
    if model:
        return f"{row.block}|m|{model}"
    return f"{row.block}|n|{norm(row.关键件名称)}"


def _index(rows: list[Row]) -> dict[str, list[Row]]:
    index: dict[str, list[Row]] = {}
    for r in rows:
        index.setdefault(_match_key(r), []).append(r)
    return index


def _changed_fields(a: Row, b: Row) -> list[str]:
    changed = []
    for field, fn in _VERIFY_FIELDS.items():
        av, bv = getattr(a, field, ""), getattr(b, field, "")
        # 一侧为空不判为差异（信息缺省而非冲突），仅两侧都非空且归一后不同才算
        if av and bv and fn(av) != fn(bv):
            changed.append(field)
    return changed


def verify(a_rows: list[Row], b_rows: list[Row]) -> VerifyReport:
    """核对 A 与 B，产出差异报告。"""
    a_index = _index(a_rows)
    b_index = _index(b_rows)
    items: list[VerifyItem] = []
    seen_b: set[int] = set()

    for key, a_group in a_index.items():
        b_group = b_index.get(key, [])
        # 简化：同键取首行代表比对（初稿；多行同键的精细配对留待后续）
        a = a_group[0]
        if not b_group:
            items.append(VerifyItem(key=key, block=a.block,
                                    type=VerifyType.MISSING_IN_REPORT, a_row=a))
            continue
        b = b_group[0]
        seen_b.add(id(b))
        changed = _changed_fields(a, b)
        if changed:
            items.append(VerifyItem(key=key, block=a.block, type=VerifyType.FIELD_MISMATCH,
                                    a_row=a, b_row=b, changed_fields=changed))
        else:
            items.append(VerifyItem(key=key, block=a.block, type=VerifyType.CONSISTENT,
                                    a_row=a, b_row=b))

    # B 中未被 A 匹配到的行 = 报告草稿多出
    for key, b_group in b_index.items():
        if key in a_index:
            continue
        b = b_group[0]
        items.append(VerifyItem(key=key, block=b.block,
                                type=VerifyType.EXTRA_IN_REPORT, b_row=b))

    return VerifyReport(items=items, a_rows=len(a_rows), b_rows=len(b_rows))
