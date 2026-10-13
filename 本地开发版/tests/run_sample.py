"""用「样例」文件夹的两个输入跑完整流程，生成整合清单 + 对照表。非交互（自动接受）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import date

from compare_core.pipeline import run_pipeline

SAMPLE = Path(r"c:\Users\likunyuan\Desktop\项目\样例")
ORIG = SAMPLE / "75U66Q(01)_原报告清单--输入.doc"
PLM = SAMPLE / "75U66Q(01)_PLM导出清单-输入.doc"
# 输出到项目根目录下带日期的 result 文件夹
PROJECT_ROOT = Path(r"c:\Users\likunyuan\Desktop\项目")
OUT = PROJECT_ROOT / f"result_{date.today().isoformat()}"


FX = Path(__file__).resolve().parent.parent / "runs" / "parse_real"


def main():
    print("原报告输入:", ORIG.exists(), ORIG.name)
    print("PLM输入   :", PLM.exists(), PLM.name)
    # Word COM 实时解析不稳定，使用这两份样例的已解析缓存(runs/parse_real)，内容一致。
    print("使用样例的已解析缓存(runs/parse_real)运行流程 → result 目录")
    state = {
        "rows_orig_json": str(FX / "orig.json"),
        "rows_plm_json": str(FX / "plm.json"),
        "mode": "mock",
        "out_dir": str(OUT),
    }
    state = run_pipeline(state, lambda diffs, sugg: {d.key: "accept" for d in diffs})
    counts = {}
    for d in state["diffs"]:
        counts[d.type.value] = counts.get(d.type.value, 0) + 1
    print("差异分类:", counts)
    print("对照表变更项数:", len(state["changes"]))
    print("输出-整合清单:", state["out_merged"])
    print("输出-对照表  :", state["out_compare"])
    print("RUN_SAMPLE_DONE")


if __name__ == "__main__":
    main()
