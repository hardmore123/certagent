"""验证 writer 关键件组排序：电线组件的 B 独有行是否紧跟配对锚点聚在一起。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from compare_core import nodes, trace
from compare_core.models import DiffType
from compare_core.parser.docx_parser import parse_docx

FOLDER = ROOT.parent / "AI智能体-认证原始清单与新品清单合并"
ORIG = FOLDER / "输入--【原始清单，人工已整理docx】4720467-85Z970QF(东芝)_安全&EMC关键件清单.docx"
PLM = FOLDER / "输入--【PLM导出清单-新品docx】85ZXSF(01)(东芝)_安全&EMC关键件清单 - 副本.docx"


def main():
    trace.new_run()
    state = {"rows_orig": parse_docx(str(ORIG)), "rows_plm": parse_docx(str(PLM))}
    state.update(nodes.judge_node(state))

    diffs = state["diffs"]
    decisions = {d.key: "accept" for d in diffs}

    # 复现 writer 的排序逻辑
    from compare_core.writer.docx_writer import write_merged_list
    import inspect

    # 直接调 _reorder_by_group（通过内部）——改为跑一次 write 然后回读 docx
    out = ROOT / "runs" / "writer_order_test"
    out.mkdir(parents=True, exist_ok=True)
    write_merged_list(diffs, decisions, str(out / "整合版关键件清单.docx"))

    # 回读 docx 表1，打印电线组件相关行的顺序和来源
    from docx import Document
    doc = Document(str(out / "整合版关键件清单.docx"))
    t1 = doc.tables[0]
    print("=== 表1 前 20 数据行（关键件名称 | 型号前20 | 来源列）===")
    count = 0
    for r in t1.rows[1:]:
        texts = [c.text for c in r.cells]
        if texts[0] and len(set(texts)) == 1:  # 分组标题行
            continue
        name = texts[2] if len(texts) > 2 else ""
        model = texts[3][:20] if len(texts) > 3 else ""
        source = texts[-1] if texts else ""
        count += 1
        if count <= 20:
            print(f"  [{count}] {name[:24]:<26} | {model:<22} | {source}")
    print(f"  ...（表1 共 {count} 数据行）")

    # 检查电线组件相关行是否连续
    print("\n=== 电线组件相关行位置 ===")
    positions = []
    idx = 0
    for r in t1.rows[1:]:
        texts = [c.text for c in r.cells]
        if texts[0] and len(set(texts)) == 1:
            continue
        idx += 1
        name = texts[2] if len(texts) > 2 else ""
        if "电线组件" in name:
            positions.append((idx, name[:20], texts[-1]))
    for p in positions:
        print(f"  行{p[0]}: {p[1]} [{p[2]}]")
    if positions:
        rng = [p[0] for p in positions]
        contiguous = (max(rng) - min(rng) + 1) == len(rng)
        print(f"  电线组件行范围 {min(rng)}~{max(rng)}, 共 {len(rng)} 行, 连续={contiguous}")

    print("\nTEST_WRITER_ORDER_DONE")


if __name__ == "__main__":
    main()
