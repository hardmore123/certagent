"""验证 core 版 `run_group_diff` 与 tests 原型输出一致（东芝样例）。

- 读取 `runs/merge_folder/orig.json` / `plm.json`
- 分别用 tests 原型 `build_group_summary()` 和 core 版 `run_group_diff()` 各算一遍
- 逐组比对 status / 各计数字段
- 顺带比较 SAME/非 SAME 数量分布
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from compare_core.differ import run_group_diff  # noqa: E402
from compare_core.differ.normalize import normalize  # noqa: E402
from compare_core.models import GroupStatus, Row  # noqa: E402

from prototype_group_aggregation import build_group_summary  # noqa: E402

ORIG_JSON = ROOT / "runs" / "merge_folder" / "orig.json"
PLM_JSON = ROOT / "runs" / "merge_folder" / "plm.json"


def _load(path: Path) -> list[Row]:
    return [Row.model_validate(x) for x in json.loads(path.read_text(encoding="utf-8"))]


def main() -> None:
    orig = _load(ORIG_JSON)
    plm = _load(PLM_JSON)

    # 原型（tests）
    proto = build_group_summary(orig, plm)
    proto_by_key = {(g["table"], g["group"], g["name"]): g for g in proto}

    # core 版
    core_result = run_group_diff(orig, plm)
    # 用同样的 (table, normalized_group, normalized_name) 作为对齐键
    core_by_key = {
        (g.table, normalize(g.group, drop_space=False), normalize(g.关键件名称)): g
        for g in core_result
    }

    # 逐组比对
    keys = sorted(set(proto_by_key) | set(core_by_key))
    mismatches: list[str] = []
    for key in keys:
        p = proto_by_key.get(key)
        c = core_by_key.get(key)
        if p is None:
            mismatches.append(f"core 独有: {key}")
            continue
        if c is None:
            mismatches.append(f"proto 独有: {key}")
            continue
        # status 名映射：原型是大写字符串（"REPLACED_GROUP"），core 是 enum
        if p["status"] != c.status.value.upper():
            mismatches.append(f"status 不一致 {key}: proto={p['status']}, core={c.status.value.upper()}")
        for field in ("orig_rows", "plm_rows", "orig_selections", "plm_selections",
                      "common_selections", "only_orig_selections", "only_plm_selections"):
            if p[field] != getattr(c, field):
                mismatches.append(f"{field} 不一致 {key}: proto={p[field]}, core={getattr(c, field)}")

    from collections import Counter
    core_status = Counter(g.status.value for g in core_result)
    proto_status = Counter(g["status"].lower() for g in proto)

    print(f"proto 组数: {len(proto)}, core 组数: {len(core_result)}")
    print(f"proto 状态分布: {dict(proto_status)}")
    print(f"core  状态分布: {dict(core_status)}")
    if not mismatches:
        print("✅ core 与 proto 每组每字段完全一致")
    else:
        print("❌ 发现不一致：")
        for m in mismatches[:20]:
            print("  -", m)
        if len(mismatches) > 20:
            print(f"  ...省略 {len(mismatches) - 20} 条")

    # 非 SAME 组数应等于三.11 记录：43 组，SAME 6，非 SAME 37
    non_same = sum(1 for g in core_result if g.status != GroupStatus.SAME_GROUP)
    print(f"非 SAME 组数（core）: {non_same}")
    print("SMOKE_GROUP_DIFF_DONE")


if __name__ == "__main__":
    main()
