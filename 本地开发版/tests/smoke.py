"""非交互冒烟测试：core 引擎 + fixture + mock，自动接受全部建议。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compare_core.models import DiffType
from compare_core.pipeline import run_pipeline


def auto_accept(diffs, suggestions):
    return {d.key: "accept" for d in diffs}


def main():
    base = Path(__file__).resolve().parent.parent
    state = {
        "rows_orig_json": str(base / "fixtures" / "orig.json"),
        "rows_plm_json": str(base / "fixtures" / "plm.json"),
        "mode": "mock",
        "out_dir": str(base / "runs" / "smoke"),
    }
    state = run_pipeline(state, auto_accept)

    diffs = state["diffs"]
    counts = {}
    for d in diffs:
        counts[d.type.value] = counts.get(d.type.value, 0) + 1
    print("DIFF_COUNTS:", counts)
    print("CHANGES:", [c.变更项目 for c in state["changes"]])
    print("OUT_MERGED:", state["out_merged"])
    print("OUT_COMPARE:", state["out_compare"])

    # 断言：电线组件(仅波浪号差异)应归一化为 SAME；保险丝证书号不同应为 CHANGED
    assert counts.get(DiffType.SAME.value, 0) >= 1, "归一化后应有 SAME 项"
    assert counts.get(DiffType.CHANGED.value, 0) >= 1, "证书号差异应为 CHANGED"
    assert counts.get(DiffType.ONLY_PLM.value, 0) >= 1, "主板应为 ONLY_PLM"
    assert Path(state["out_merged"]).exists(), "整合清单未生成"
    assert Path(state["out_compare"]).exists(), "对照表未生成"
    print("SMOKE_OK")


if __name__ == "__main__":
    main()
