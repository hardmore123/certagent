"""主流水线端到端：--use-groups + --mode llm 跑东芝样例（真 DeepSeek V4）。

验证：pipeline（parse → judge → suggest_from_groups_via_LLM → apply → memory）端到端正常。
产物：`runs/e2e_groups_llm_2026-07-28/`
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))


def _load_env():
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_env()

from compare_core import nodes, trace  # noqa: E402
from compare_core.config import config  # noqa: E402
from compare_core.models import Row  # noqa: E402

from experiment_group_suggest import EXPECTED_TEMPLATE, match_expected  # noqa: E402

ORIG_JSON = ROOT / "runs" / "merge_folder" / "orig.json"
PLM_JSON = ROOT / "runs" / "merge_folder" / "plm.json"
OUT = ROOT / "runs" / "e2e_groups_llm_2026-07-28"


def _load(path: Path) -> list[Row]:
    return [Row.model_validate(x) for x in json.loads(path.read_text(encoding="utf-8"))]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    trace.new_run()

    print(f"[info] model={config.LLM_MODEL}, base_url={config.LLM_BASE_URL}", flush=True)
    if not config.LLM_BASE_URL or not config.LLM_API_KEY:
        print("[SKIP] LLM 环境未配置（.env 缺 LLM_BASE_URL/LLM_API_KEY），跳过。")
        return

    state = {
        "rows_orig": _load(ORIG_JSON),
        "rows_plm": _load(PLM_JSON),
        "mode": "llm",
        "suggest_source": "groups",
        "out_dir": str(OUT),
    }
    print("[step] judge_node...", flush=True)
    state.update(nodes.judge_node(state))
    print("[step] suggest_node (LLM, groups)...", flush=True)
    state.update(nodes.suggest_node(state))
    state["decisions"] = {d.key: "accept" for d in state["diffs"]}
    print("[step] apply_node...", flush=True)
    state.update(nodes.apply_node(state))
    state.update(nodes.memory_node(state))

    changes = state["changes"]
    match = match_expected(changes, EXPECTED_TEMPLATE)

    from collections import Counter
    group_status = Counter(g.status.value for g in state["group_diffs"])

    print(f"\n组级 diff 状态分布: {dict(group_status)}")
    print(f"changes 条目数: {len(changes)}")
    print(f"业务模板覆盖: {match['matched']}/{match['expected_total']}")
    for i, c in enumerate(changes, 1):
        print(f"  [{i}] {c.变更项目}")
        print(f"       变更后: {c.变更后[:100]}")
    print(f"\n整合清单: {state['out_merged']}")
    print(f"对照表:   {state['out_compare']}")

    # 保存结果 JSON
    result = {
        "model": config.LLM_MODEL,
        "changes_count": len(changes),
        "coverage": match,
        "changes": [c.model_dump() for c in changes],
        "group_status": dict(group_status),
    }
    (OUT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    if match["matched"] == 5:
        print("\nE2E_GROUPS_LLM_OK (5/5)")
    else:
        print(f"\nE2E_GROUPS_LLM WARN: {match['matched']}/{match['expected_total']}")


if __name__ == "__main__":
    main()
