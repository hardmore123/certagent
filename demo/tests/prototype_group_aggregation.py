"""关键件组聚合只读原型：验证 IR 分层对我们的匹配有没有价值。

思路：
- 当前 differ 按物理行（`table+名称+型号+位号+规格+证书号`）对齐；
- 业务实际上是按 `(表, 分组, 关键件名称)` 这一"关键件组"操作的：整组新增 / 组内加减一款
  选型 / 组内替换供应商，物理行差异不代表业务差异。
- 本脚本按关键件组聚合，输出每个组在 orig / plm 里的选型集合差异，然后把上一轮诊断中的
  `input_name_model_only` 行映射到组上，看组级视角能覆盖多少条。

只读：读 `runs/merge_folder/*.json`、`runs/accuracy_gap_2026-07-27/diagnosis.json`，输出
`runs/group_prototype_2026-07-28/`，不改任何 core 代码。
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from compare_core.differ.normalize import normalize  # noqa: E402
from compare_core.models import Row  # noqa: E402

ORIG_JSON = ROOT / "runs" / "merge_folder" / "orig.json"
PLM_JSON = ROOT / "runs" / "merge_folder" / "plm.json"
DIAG_JSON = ROOT / "runs" / "accuracy_gap_2026-07-27" / "diagnosis.json"
OUT_DIR = ROOT / "runs" / "group_prototype_2026-07-28"


def load_rows(path: Path) -> list[Row]:
    return [Row.model_validate(x) for x in json.loads(path.read_text(encoding="utf-8"))]


def group_key(row: Row) -> tuple[int, str, str]:
    """关键件组的自然键：`(表号, 分组标题, 关键件名称)`。"""
    return (row.table, normalize(row.group, drop_space=False), normalize(row.关键件名称))


def selection_key(row: Row) -> tuple[str, str, str, str]:
    """组内一款选型的身份指纹（选型 = 型号 + 位号 + 规格 + 证书号）。"""
    return (
        normalize(row.型号),
        normalize(row.位号),
        normalize(row.规格材料),
        normalize(row.证书号),
    )


def _category(item: dict) -> str:
    s, i, n = item["strict_count"], item["identity_count"], item["name_model_count"]
    if i["demo"]:
        cat = "demo_identity_only_content_diff"
    elif i["orig"] or i["plm"]:
        cat = "input_identity_but_not_demo"
    elif n["orig"] or n["plm"]:
        cat = "input_name_model_only"
    else:
        cat = "not_in_input_identity"
    if s["orig"] or s["plm"]:
        cat += "+strict_input_match"
    return cat


def aggregate(rows: list[Row]) -> dict[tuple, list[Row]]:
    g: dict[tuple, list[Row]] = defaultdict(list)
    for r in rows:
        g[group_key(r)].append(r)
    return g


def group_status(orig_sel: Counter, plm_sel: Counter) -> str:
    if not orig_sel:
        return "ONLY_PLM_GROUP"
    if not plm_sel:
        return "ONLY_ORIG_GROUP"
    only_o = sum((orig_sel - plm_sel).values())
    only_p = sum((plm_sel - orig_sel).values())
    if only_o == 0 and only_p == 0:
        return "SAME_GROUP"
    if only_o == 0:
        return "EXTENDED_BY_PLM"
    if only_p == 0:
        return "SHRUNK_BY_PLM"
    return "REPLACED_GROUP"


def build_group_summary(orig: list[Row], plm: list[Row]) -> list[dict]:
    g_orig = aggregate(orig)
    g_plm = aggregate(plm)
    all_keys = sorted(set(g_orig) | set(g_plm))
    summary: list[dict] = []
    for key in all_keys:
        table, group_name, name = key
        oset = g_orig.get(key, [])
        pset = g_plm.get(key, [])
        o_sel = Counter(selection_key(r) for r in oset)
        p_sel = Counter(selection_key(r) for r in pset)
        summary.append({
            "key": list(key),
            "table": table,
            "group": group_name,
            "name": name,
            "orig_rows": len(oset),
            "plm_rows": len(pset),
            "orig_selections": len(o_sel),
            "plm_selections": len(p_sel),
            "common_selections": sum((o_sel & p_sel).values()),
            "only_orig_selections": sum((o_sel - p_sel).values()),
            "only_plm_selections": sum((p_sel - o_sel).values()),
            "status": group_status(o_sel, p_sel),
        })
    return summary


def index_groups(summary: list[dict]) -> dict[tuple[int, str], list[dict]]:
    idx: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for gs in summary:
        idx[(gs["table"], gs["name"])].append(gs)
    return idx


def map_missing_to_groups(missing_rows: list[dict], name_index: dict) -> list[dict]:
    out = []
    for m in missing_rows:
        e = m["expected"]
        key = (e["table"], normalize(e["关键件名称"]))
        groups = name_index.get(key, [])
        out.append({
            "category": _category(m),
            "expected": {
                "table": e["table"],
                "row_index": e["row_index"],
                "关键件名称": e["关键件名称"],
                "型号": e["型号"],
                "证书号": e["证书号"],
            },
            "matched_groups": [
                {"group": g["group"], "status": g["status"],
                 "orig_rows": g["orig_rows"], "plm_rows": g["plm_rows"]}
                for g in groups
            ],
        })
    return out


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    orig = load_rows(ORIG_JSON)
    plm = load_rows(PLM_JSON)
    diag = json.loads(DIAG_JSON.read_text(encoding="utf-8"))
    missing_rows = diag.get("missing_rows", [])

    summary = build_group_summary(orig, plm)
    idx = index_groups(summary)
    mapped = map_missing_to_groups(missing_rows, idx)

    status_counter = Counter(gs["status"] for gs in summary)
    cat_counter = Counter(m["category"] for m in mapped)

    # 覆盖率：某类未覆盖行是否落在"非 SAME_GROUP"上（即组级视角能识别为业务动作）
    per_cat_coverage: dict[str, dict] = {}
    for cat in cat_counter:
        subset = [m for m in mapped if m["category"] == cat]
        total = len(subset)
        covered = sum(
            1 for m in subset
            if m["matched_groups"] and any(g["status"] != "SAME_GROUP" for g in m["matched_groups"])
        )
        no_group = sum(1 for m in subset if not m["matched_groups"])
        per_cat_coverage[cat] = {
            "total": total,
            "covered_by_non_same_group": covered,
            "no_group_hit": no_group,
        }

    result = {
        "group_status_distribution": status_counter,
        "missing_category_distribution": cat_counter,
        "coverage_by_category": per_cat_coverage,
        "group_summary": summary,
        "missing_mapped": mapped,
    }

    (OUT_DIR / "group_prototype.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        "# 关键件组聚合原型报告（只读）",
        "",
        "> 输入：`runs/merge_folder/orig.json` + `plm.json`；参照：诊断 JSON。",
        "> 组键：`(表号, 分组标题, 关键件名称)`。选型键：`(型号, 位号, 规格材料, 证书号)`。",
        "",
        "## 1. 组级差异分布",
        "",
        "| 状态 | 组数 |",
        "|---|---:|",
    ]
    for status, count in status_counter.most_common():
        lines.append(f"| {status} | {count} |")

    lines += [
        "",
        "## 2. 未覆盖行按类别 → 组级视角覆盖率",
        "",
        "命中口径：该未覆盖行的 `(表, 关键件名称)` 能落到至少一个非 `SAME_GROUP` 的组，说明"
        "组级视角识别为业务操作。",
        "",
        "| 类别 | 未覆盖行 | 落在非 SAME_GROUP | 未映射到任何组 |",
        "|---|---:|---:|---:|",
    ]
    for cat, info in sorted(per_cat_coverage.items(), key=lambda x: -x[1]["total"]):
        lines.append(
            f"| {cat} | {info['total']} | {info['covered_by_non_same_group']} |"
            f" {info['no_group_hit']} |"
        )

    lines += ["", "## 3. `input_name_model_only` 落到的组", ""]
    for m in mapped:
        if m["category"] != "input_name_model_only":
            continue
        e = m["expected"]
        if m["matched_groups"]:
            group_line = "; ".join(
                f"[{g['status']}] {g['group'] or '(无分组)'} orig={g['orig_rows']} plm={g['plm_rows']}"
                for g in m["matched_groups"]
            )
        else:
            group_line = "无组命中"
        lines.append(
            f"- 表{e['table']} 行{e['row_index']} `{e['关键件名称']}` / `{e['型号'][:40]}` → {group_line}"
        )

    lines += ["", "## 4. 非 SAME_GROUP 组一览（前 20）", "",
              "| 表 | 分组 | 关键件名称 | 状态 | orig 行 | plm 行 | 共同选型 | 仅 orig | 仅 plm |",
              "|---|---|---|---|---:|---:|---:|---:|---:|"]
    non_same = [g for g in summary if g["status"] != "SAME_GROUP"]
    for g in non_same[:20]:
        lines.append(
            f"| {g['table']} | {(g['group'] or '(无)')[:20]} | {g['name'][:24]} | {g['status']} |"
            f" {g['orig_rows']} | {g['plm_rows']} | {g['common_selections']} |"
            f" {g['only_orig_selections']} | {g['only_plm_selections']} |"
        )

    (OUT_DIR / "group_prototype.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("组级状态分布:", dict(status_counter))
    print("未覆盖类别分布:", dict(cat_counter))
    print("按类别的组级覆盖:")
    for cat, info in per_cat_coverage.items():
        print(f"  {cat}: {info}")
    print("产物:", OUT_DIR)
    print("GROUP_PROTOTYPE_DONE")


if __name__ == "__main__":
    main()
