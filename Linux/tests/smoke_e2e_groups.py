"""端到端 smoke：--use-groups 模式跑东芝样例（mock），验证 pipeline 产出 5/5 对照表。

链路：`orig.json + plm.json → parse → judge(rows+groups) → suggest(groups) → apply → memory`
断言：changes 数 = 5，业务模板 5/5 命中。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from compare_core import nodes, trace  # noqa: E402
from compare_core.models import Row  # noqa: E402

from experiment_group_suggest import EXPECTED_TEMPLATE, match_expected  # noqa: E402

ORIG_JSON = ROOT / "runs" / "merge_folder" / "orig.json"
PLM_JSON = ROOT / "runs" / "merge_folder" / "plm.json"
OUT = ROOT / "runs" / "smoke_e2e_groups"


def _load(path: Path) -> list[Row]:
    return [Row.model_validate(x) for x in json.loads(path.read_text(encoding="utf-8"))]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    trace.new_run()

    state = {
        "rows_orig": _load(ORIG_JSON),
        "rows_plm": _load(PLM_JSON),
        "mode": "mock",
        "suggest_source": "groups",
        "out_dir": str(OUT),
    }
    state.update(nodes.judge_node(state))
    state.update(nodes.suggest_node(state))
    state["decisions"] = {d.key: "accept" for d in state["diffs"]}
    state.update(nodes.apply_node(state))
    state.update(nodes.memory_node(state))

    changes = state["changes"]
    match = match_expected(changes, EXPECTED_TEMPLATE)

    from collections import Counter
    diff_counts = Counter(d.type.value for d in state["diffs"])
    group_status = Counter(g.status.value for g in state["group_diffs"])

    print(f"行级 diff 分类: {dict(diff_counts)}")
    print(f"组级 diff 状态分布: {dict(group_status)}")
    print(f"changes 条目数: {len(changes)}")
    print(f"业务模板覆盖: {match['matched']}/{match['expected_total']}")
    for i, c in enumerate(changes, 1):
        print(f"  [{i}] {c.变更项目}")
    print(f"整合清单: {state['out_merged']}")
    print(f"对照表:   {state['out_compare']}")

    assert len(changes) == 5, f"changes 应为 5 条，实际 {len(changes)}"
    assert match["matched"] == 5, f"业务模板覆盖不完整：{match}"
    print("SMOKE_E2E_GROUPS_OK")


if __name__ == "__main__":
    main()
