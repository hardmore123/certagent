"""实验 1：组级 diff → 对照表归纳（Mock 版本）。

只读实验，不改主流程：
- 复用 `prototype_group_aggregation.build_group_summary()`；
- 用规则映射把非 SAME_GROUP 组归纳成"业务期望的 5 类模板"；
- 与业务期望模板 5 条做覆盖率对比；
- 同时跑一遍现有 `MockSuggester`（行级 Mock）作为基线。

产物：`runs/exp_group_suggest_2026-07-28/`。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))  # 让 prototype_group_aggregation 可导入

from compare_core.differ.diff_engine import run_diff  # noqa: E402
from compare_core.models import ChangeEntry  # noqa: E402
from compare_core.rules.loader import load_rules  # noqa: E402
from compare_core.suggester.mock_suggester import MockSuggester  # noqa: E402

from prototype_group_aggregation import (  # noqa: E402
    ORIG_JSON, PLM_JSON, build_group_summary, load_rows,
)

OUT_DIR = ROOT / "runs" / "exp_group_suggest_2026-07-28"

# 业务期望的 5 类模板（来自 85ZXSF 期望对照表实际归纳的项目）
EXPECTED_TEMPLATE = [
    "增加产品型号规格",
    "增加机内电源单元备选件",
    "增加主板（含网卡、调谐单元、天线隔离器）备选件",
    "补充/更新供应商信息",
    "增加整机外观、内部结构、主板、电源板等照片",
]

BOARD_KEYS = ("主板", "pcb", "调谐", "天线", "网卡", "显示屏")
POWER_HINT = "电源单元"


def _fmt_selections(g: dict) -> str:
    return f"{g['orig_selections']}→{g['plm_selections']}"


def group_summarize_mock(summary: list[dict]) -> list[ChangeEntry]:
    """基于关键件组差异按业务模板归纳。规则按"表号 → 分组标题 → 关键件名称"优先级级联。"""
    entries: list[ChangeEntry] = []
    active = [g for g in summary if g["status"] != "SAME_GROUP"]

    # 类别 1：表 2（本次机型主项）任何非 SAME 组 → 增加产品型号规格
    t2_active = [g for g in active if g["table"] == 2]
    if t2_active:
        details = "、".join(
            f"{g['name']}({g['status']} 选型 {_fmt_selections(g)})" for g in t2_active
        )
        entries.append(ChangeEntry(
            变更项目="增加产品型号规格",
            变更前="见原报告",
            变更后=f"表2 机型主项变更：{details}",
        ))

    # 类别 2：表 1 分组标题含"电源单元" 的 ONLY_PLM_GROUP → 增加机内电源单元备选件
    t1_active = [g for g in active if g["table"] == 1]
    power_new = [g for g in t1_active if POWER_HINT in g["group"] and g["status"] == "ONLY_PLM_GROUP"]
    power_old_group = next(
        (g["group"] for g in t1_active if POWER_HINT in g["group"] and g["status"] == "ONLY_ORIG_GROUP"),
        "",
    )
    new_power_group = next((g["group"] for g in power_new), "")
    if power_new:
        details = "、".join(f"{g['name']}({g['plm_selections']} 款)" for g in power_new)
        note = f"（原 {power_old_group} 换型为 {new_power_group}）" if power_old_group else ""
        entries.append(ChangeEntry(
            变更项目="增加机内电源单元备选件",
            变更前="见原报告",
            变更后=f"新增子件：{details}{note}",
        ))

    # 类别 3：表 1 顶层组（无 group）名字含主板关键词，非 SAME → 增加主板备选件
    board_groups = [
        g for g in t1_active
        if not g["group"] and any(k in g["name"] for k in BOARD_KEYS)
    ]
    if board_groups:
        details = "、".join(
            f"{g['name']}({g['status']} 选型 {_fmt_selections(g)})"
            for g in board_groups
        )
        entries.append(ChangeEntry(
            变更项目="增加主板（含网卡、调谐单元、天线隔离器）备选件",
            变更前="见原报告",
            变更后=f"变更子项：{details}",
        ))

    # 类别 4：其他 REPLACED_GROUP 且行数不变的组 → 供应商替换（排除主板类）
    board_names = {g["name"] for g in board_groups}
    supplier = [
        g for g in t1_active
        if g["status"] == "REPLACED_GROUP"
        and g["orig_selections"] == g["plm_selections"]
        and g["only_orig_selections"] >= 1
        and g["only_orig_selections"] <= 3
        and g["name"] not in board_names
        and POWER_HINT not in g["group"]
    ]
    if supplier:
        details = "、".join(
            f"{g['name']}(替换 {g['only_orig_selections']} 家)" for g in supplier
        )
        entries.append(ChangeEntry(
            变更项目="补充/更新供应商信息",
            变更前="见原报告",
            变更后=f"供应商替换：{details}",
        ))

    # 类别 5：照片类，本清单不可推导，明确标注外部输入
    entries.append(ChangeEntry(
        变更项目="增加整机外观、内部结构、主板、电源板等照片",
        变更前="见原报告",
        变更后="[外部输入] 需业务提供照片，本次合并的关键件清单无法推导",
    ))

    return entries


CORE_KEYWORDS = {
    "增加产品型号规格": ["产品型号规格"],
    "增加机内电源单元备选件": ["电源单元"],
    "增加主板（含网卡、调谐单元、天线隔离器）备选件": ["主板"],
    "补充/更新供应商信息": ["供应商"],
    "增加整机外观、内部结构、主板、电源板等照片": ["照片"],
}


def _keywords_hit(expected: str, entry: str) -> bool:
    for kw in CORE_KEYWORDS.get(expected, []):
        if kw in entry:
            return True
    return False


def match_expected(entries: list[ChangeEntry], expected: list[str]) -> dict:
    matches = []
    for exp in expected:
        hit = next((e.变更项目 for e in entries if _keywords_hit(exp, e.变更项目)), None)
        matches.append({"expected": exp, "matched_entry": hit})
    return {
        "expected_total": len(expected),
        "matched": sum(1 for m in matches if m["matched_entry"]),
        "detail": matches,
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    orig = load_rows(ORIG_JSON)
    plm = load_rows(PLM_JSON)
    summary = build_group_summary(orig, plm)

    entries = group_summarize_mock(summary)
    match = match_expected(entries, EXPECTED_TEMPLATE)

    # 基线：现有行级 Mock
    diffs = run_diff(orig, plm, load_rules())
    old_entries = MockSuggester().summarize_changes(diffs, load_rules())
    old_match = match_expected(old_entries, EXPECTED_TEMPLATE)

    result = {
        "expected_template": EXPECTED_TEMPLATE,
        "group_based_mock": {
            "count": len(entries),
            "entries": [e.model_dump() for e in entries],
            "coverage": match,
        },
        "row_based_mock": {
            "count": len(old_entries),
            "coverage": old_match,
            "entries": [e.model_dump() for e in old_entries],
        },
    }
    (OUT_DIR / "experiment.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        "# 实验 1：组级 diff → 对照表归纳（Mock 只读）",
        "",
        "> 输入：`runs/merge_folder/orig.json` + `plm.json`。",
        "> 目标：验证组级视角能否直接对齐业务期望的 5 类模板归纳。",
        "",
        "## 概览",
        "",
        f"- 老（行级 Mock，`MockSuggester`）：{len(old_entries)} 条，覆盖业务模板 "
        f"{old_match['matched']}/{old_match['expected_total']}",
        f"- 新（组级 Mock）：{len(entries)} 条，覆盖业务模板 "
        f"{match['matched']}/{match['expected_total']}",
        "",
        "## 组级 Mock 归纳出的条目",
        "",
    ]
    for i, e in enumerate(entries, 1):
        lines += [
            f"### {i}. {e.变更项目}",
            "",
            f"- 变更前：{e.变更前}",
            f"- 变更后：{e.变更后}",
            "",
        ]

    lines += [
        "## 业务期望模板 5 条覆盖情况（组级 Mock）",
        "",
    ]
    for m in match["detail"]:
        icon = "✓" if m["matched_entry"] else "✗"
        lines.append(f"- {icon} `{m['expected']}` → `{m['matched_entry']}`")

    lines += [
        "",
        "## 业务期望模板 5 条覆盖情况（老 · 行级 Mock 作基线）",
        "",
    ]
    for m in old_match["detail"]:
        icon = "✓" if m["matched_entry"] else "✗"
        lines.append(f"- {icon} `{m['expected']}` → `{m['matched_entry']}`")

    lines += [
        "",
        "## 老（行级 Mock）示例（共 {} 条）".format(len(old_entries)),
        "",
    ]
    for e in old_entries[:8]:
        lines.append(f"- {e.变更项目} → {e.变更后[:80]}")
    if len(old_entries) > 8:
        lines.append(f"- ...（省略后续 {len(old_entries) - 8} 条）")

    (OUT_DIR / "experiment.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("组级 Mock 归纳:", len(entries), "条")
    print("组级 Mock 覆盖业务模板:", f"{match['matched']}/{match['expected_total']}")
    print("老 Mock 覆盖业务模板:", f"{old_match['matched']}/{old_match['expected_total']}")
    print("产物:", OUT_DIR)
    print("EXP_GROUP_SUGGEST_DONE")


if __name__ == "__main__":
    main()
