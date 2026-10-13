"""用「AI智能体-认证原始清单与新品清单合并」文件夹的两个输入运行本项目。

原始清单(人工已整理) = 变更前基准(orig)
PLM导出清单-新品      = 变更后来源(plm)
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compare_core.parser import parse_document
from compare_core.pipeline import run_pipeline

FOLDER = Path(r"c:\Users\likunyuan\Desktop\项目\AI智能体-认证原始清单与新品清单合并")
ORIG = FOLDER / "输入--【原始清单，人工已整理】4720467-85Z970QF(东芝)_安全&EMC关键件清单.doc"
PLM = FOLDER / "输入--【PLM导出清单-新品】85ZXSF(01)(东芝)_安全&EMC关键件清单 - 副本.doc"

OUT = Path(r"c:\Users\likunyuan\Desktop\项目") / f"result_东芝85ZXSF_{date.today().isoformat()}"
FX = Path(__file__).resolve().parent.parent / "runs" / "merge_folder"


def main():
    print("原始清单(orig)存在:", ORIG.exists())
    print("PLM新品(plm)存在:", PLM.exists())
    FX.mkdir(parents=True, exist_ok=True)

    print("解析原始清单...")
    rows_orig = parse_document(str(ORIG))
    print(f"  原始清单 {len(rows_orig)} 行")
    print("解析PLM新品清单...")
    rows_plm = parse_document(str(PLM))
    print(f"  PLM新品 {len(rows_plm)} 行")

    # 缓存解析结果，便于复跑
    import json
    (FX / "orig.json").write_text(json.dumps([r.model_dump() for r in rows_orig], ensure_ascii=False), encoding="utf-8")
    (FX / "plm.json").write_text(json.dumps([r.model_dump() for r in rows_plm], ensure_ascii=False), encoding="utf-8")

    state = {"rows_orig": rows_orig, "rows_plm": rows_plm, "mode": "mock", "out_dir": str(OUT)}
    # 直接注入 rows，绕过 parse_node 的路径读取
    from compare_core import nodes, trace
    trace.new_run()
    state.update(nodes.judge_node(state))
    state.update(nodes.suggest_node(state))
    state["decisions"] = {d.key: "accept" for d in state["diffs"]}
    state.update(nodes.apply_node(state))
    state.update(nodes.memory_node(state))

    counts = {}
    for d in state["diffs"]:
        counts[d.type.value] = counts.get(d.type.value, 0) + 1
    print("\n差异分类:", counts)
    print("对照表变更项数:", len(state["changes"]))
    for c in state["changes"][:10]:
        print("   -", c.变更项目)
    print("输出-整合清单:", state["out_merged"])
    print("输出-对照表  :", state["out_compare"])
    print("RUN_MERGE_DONE")


if __name__ == "__main__":
    main()
