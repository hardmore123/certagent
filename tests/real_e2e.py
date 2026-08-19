"""用真实解析出的 fixture 跑完整 core 流程（自动接受），验证 diff+writer 在 475 行真实数据上可用。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compare_core.pipeline import run_pipeline

BASE = Path(__file__).resolve().parent.parent


def main():
    fx = BASE / "runs" / "parse_real"
    state = {
        "rows_orig_json": str(fx / "orig.json"),
        "rows_plm_json": str(fx / "plm.json"),
        "mode": "mock",
        "out_dir": str(BASE / "runs" / "real_out"),
    }
    state = run_pipeline(state, lambda diffs, sugg: {d.key: "accept" for d in diffs})
    counts = {}
    for d in state["diffs"]:
        counts[d.type.value] = counts.get(d.type.value, 0) + 1
    print("REAL_DIFF_COUNTS:", counts)
    print("REAL_CHANGES:", len(state["changes"]))
    print("OUT_MERGED:", state["out_merged"])
    print("OUT_COMPARE:", state["out_compare"])
    assert Path(state["out_merged"]).exists()
    assert Path(state["out_compare"]).exists()
    print("REAL_E2E_OK")


if __name__ == "__main__":
    main()
