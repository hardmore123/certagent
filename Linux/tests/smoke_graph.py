"""非交互冒烟测试：LangGraph 编排 + interrupt/resume，自动接受。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph.types import Command

from graph.build import build_graph


def main():
    base = Path(__file__).resolve().parent.parent
    app = build_graph()
    cfg = {"configurable": {"thread_id": "smoke-graph"}}
    state = {
        "rows_orig_json": str(base / "fixtures" / "orig.json"),
        "rows_plm_json": str(base / "fixtures" / "plm.json"),
        "mode": "mock",
        "out_dir": str(base / "runs" / "smoke_graph"),
    }
    result = app.invoke(state, cfg)
    intr = result.get("__interrupt__")
    assert intr, "应在 human_review 处中断"
    payload = intr[0].value
    print("INTERRUPT_DIFFS:", len(payload["diffs"]))
    decisions = {d["key"]: "accept" for d in payload["diffs"]}
    result = app.invoke(Command(resume=decisions), cfg)
    print("OUT_MERGED:", result.get("out_merged"))
    print("OUT_COMPARE:", result.get("out_compare"))
    assert Path(result["out_merged"]).exists()
    assert Path(result["out_compare"]).exists()
    print("SMOKE_GRAPH_OK")


if __name__ == "__main__":
    main()
