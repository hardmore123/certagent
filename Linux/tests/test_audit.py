"""验证数据守恒审计节点：
1) 正常流程（真实东芝 docx）审计应为 ok，无丢失。
2) 注入一条引擎丢行（伪造 diff 不引用某 orig 行）→ critical + repair 补录到附录。
3) 拒绝一条 SAME → warning。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from compare_core import nodes, trace
from compare_core.differ import run_audit
from compare_core.models import DiffType
from compare_core.parser.docx_parser import parse_docx

FOLDER = ROOT.parent / "AI智能体-认证原始清单与新品清单合并"
ORIG = FOLDER / "输入--【原始清单，人工已整理docx】4720467-85Z970QF(东芝)_安全&EMC关键件清单.docx"
PLM = FOLDER / "输入--【PLM导出清单-新品docx】85ZXSF(01)(东芝)_安全&EMC关键件清单 - 副本.docx"


def main():
    trace.new_run()
    out = ROOT / "runs" / "audit_test"
    out.mkdir(parents=True, exist_ok=True)

    state = {"rows_orig": parse_docx(str(ORIG)), "rows_plm": parse_docx(str(PLM)),
             "out_dir": str(out), "mode": "mock", "suggest_source": "groups"}
    state.update(nodes.judge_node(state))
    state.update(nodes.suggest_node(state))

    diffs = state["diffs"]
    print(f"输入 A={len(state['rows_orig'])} 行, B={len(state['rows_plm'])} 行, diffs={len(diffs)}")

    # === 场景 1：全部接受，正常流程 ===
    state["decisions"] = {d.key: "accept" for d in diffs}
    state.update(nodes.apply_node(state))
    state.update(nodes.audit_node(state))
    r1 = state["audit_report"]
    print("\n[场景1 全部接受]")
    print(f"  status={r1.status} 预期保留={r1.kept_count} 实际输出={r1.output_rows} mismatch={r1.output_mismatch}")
    print(f"  lost_orig={len(r1.lost_orig)} lost_plm={len(r1.lost_plm)}")
    print("  建议:", r1.recommendations[0] if r1.recommendations else "")
    assert r1.status == "ok", f"正常流程应为 ok，实得 {r1.status}"
    assert not r1.lost_orig and not r1.lost_plm
    assert r1.output_mismatch == 0

    # === 场景 2：注入引擎丢行（伪造：从 diffs 里剔除引用某 orig 行的 diff）===
    # 找一个 ONLY_ORIG 或 SAME，删掉它 → 该 orig 行不再被任何 diff 引用
    victim = next((d for d in diffs if d.orig is not None), None)
    broken = [d for d in diffs if d is not victim]
    r2 = run_audit(state["rows_orig"], state["rows_plm"], broken,
                   {d.key: "accept" for d in broken}, state.get("out_merged"))
    print("\n[场景2 注入引擎丢行]")
    print(f"  status={r2.status} lost_orig={len(r2.lost_orig)} lost_plm={len(r2.lost_plm)}")
    print("  建议:", r2.recommendations[0] if r2.recommendations else "")
    assert r2.status == "critical", f"引擎丢行应为 critical，实得 {r2.status}"
    assert len(r2.lost_orig) + len(r2.lost_plm) >= 1

    # 触发 repair 补录（用副本，避免污染场景1的干净输出）
    import shutil
    copy2 = str(out / "整合版关键件清单_engine_lost.docx")
    shutil.copyfile(state["out_merged"], copy2)
    st2 = {"audit_report": r2, "out_merged": copy2}
    upd = nodes.repair_node(st2)
    print(f"  repair 后 repaired={upd.get('audit_repaired')}, report.repaired={r2.repaired}")
    assert r2.repaired is True

    # === 场景 2b：模拟 writer 丢行（物理层按指纹定位）===
    # 生成一份"被删掉一行"的整合 docx，审计应按指纹定位到缺失行并 critical。
    from docx import Document
    good = state["out_merged"]
    broken_docx = str(out / "整合版关键件清单_broken.docx")
    doc = Document(good)
    # 删掉表1第一张表里第一条数据行（跳过表头行 idx0 与可能的分组标题行）
    t = doc.tables[0]
    removed_desc = None
    for i, row in enumerate(t.rows):
        if i == 0:
            continue
        texts = [c.text for c in row.cells]
        if texts and texts[0] and len(set(texts)) == 1:
            continue  # 分组标题行
        removed_desc = f"{texts[2] if len(texts) > 2 else ''} | {texts[3] if len(texts) > 3 else ''}"
        row._element.getparent().remove(row._element)
        break
    doc.save(broken_docx)
    r2b = run_audit(state["rows_orig"], state["rows_plm"], diffs,
                    {d.key: "accept" for d in diffs}, broken_docx)
    print("\n[场景2b 模拟 writer 丢行]")
    print(f"  删除的行: {removed_desc}")
    print(f"  status={r2b.status} output_rows={r2b.output_rows} missing_in_output={len(r2b.missing_in_output)}")
    print("  建议:", [x for x in r2b.recommendations if "缺失" in x or "丢行" in x])
    assert r2b.status == "critical", f"writer 丢行应为 critical，实得 {r2b.status}"
    assert len(r2b.missing_in_output) >= 1, "应按指纹定位到至少 1 行缺失"
    # repair 补录
    upd2b = nodes.repair_node({"audit_report": r2b, "out_merged": broken_docx})
    print(f"  repair 后 repaired={r2b.repaired}")
    assert r2b.repaired is True
    # 补录后重新审计应恢复 ok（缺失行已回到附录表）
    r2b_after = run_audit(state["rows_orig"], state["rows_plm"], diffs,
                          {d.key: "accept" for d in diffs}, broken_docx)
    print(f"  补录后重审: status={r2b_after.status} missing_in_output={len(r2b_after.missing_in_output)}")
    assert not r2b_after.missing_in_output, "补录后不应再有指纹缺失"

    # === 场景 3：拒绝一条 SAME → warning ===
    same = next((d for d in diffs if d.type == DiffType.SAME), None)
    if same is not None:
        dec = {d.key: "accept" for d in diffs}
        dec[same.key] = "reject"
        r3 = run_audit(state["rows_orig"], state["rows_plm"], diffs, dec, None)
        print("\n[场景3 拒绝一条 SAME]")
        print(f"  status={r3.status} same_changed_rejected={r3.same_changed_rejected}")
        print("  建议:", [x for x in r3.recommendations if "拒绝" in x])
        assert r3.same_changed_rejected == 1
        assert r3.status == "warning"

    print("\nTEST_AUDIT_DONE")


if __name__ == "__main__":
    main()
