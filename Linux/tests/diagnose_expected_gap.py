"""逐行定位业务期望合成清单与 Demo 输出的行数差异。

本脚本不修改核心算法，只读取：
- 东芝两份输入的 JSON 解析缓存；
- 业务期望合成清单 .doc（Word COM）；
- 现有 diff 逻辑重新计算的理论输出。

结果使用 Counter 多重集，区分：
1. 期望行是否存在于 Demo 理论输出；
2. 不存在时是否能在 orig/plm 输入中找到；
3. 是严格字段差异、身份相同但内容不同，还是输入之外的行。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT.parent
FOLDER = BASE / "AI智能体-认证原始清单与新品清单合并"
EXPECTED = FOLDER / "输出--【合成后清单】85ZXSF(01)(东芝)_安全&EMC关键件清单.doc"
ORIG_JSON = ROOT / "runs" / "merge_folder" / "orig.json"
PLM_JSON = ROOT / "runs" / "merge_folder" / "plm.json"

sys.path.insert(0, str(ROOT))
from compare_core.differ.diff_engine import run_diff  # noqa: E402
from compare_core.models import DiffItem, Row  # noqa: E402
from compare_core.rules.loader import load_rules  # noqa: E402
from compare_core.parser import parse_document  # noqa: E402
from compare_core.differ.normalize import normalize  # noqa: E402

FIELDS = (
    "关键件名称", "型号", "位号", "规格材料", "制造商", "生产企业",
    "认证标准", "证书号", "本次使用", "备注",
)
IDENTITY_FIELDS = ("关键件名称", "型号", "位号", "规格材料", "证书号")
NAME_MODEL_FIELDS = ("关键件名称", "型号")


def load_rows(path: Path) -> list[Row]:
    return [Row.model_validate(x) for x in json.loads(path.read_text(encoding="utf-8"))]


def value(row: Row, field: str) -> str:
    return normalize(str(getattr(row, field, "") or ""))


def fingerprint(row: Row, fields: Iterable[str], include_table: bool = True) -> tuple[str, ...]:
    prefix = (str(row.table),) if include_table else ()
    return prefix + tuple(value(row, f) for f in fields)


def display(row: Row | None) -> dict:
    if row is None:
        return {}
    return {
        "table": row.table,
        "group": row.group,
        "row_index": row.row_index,
        **{f: getattr(row, f, "") for f in FIELDS},
    }


def multiset_missing(expected: list[Row], actual: list[Row], fields: tuple[str, ...]) -> list[Row]:
    """返回 expected 中 actual 未覆盖的行，按原顺序消费重复项。"""
    available = Counter(fingerprint(r, fields) for r in actual)
    missing: list[Row] = []
    for row in expected:
        fp = fingerprint(row, fields)
        if available[fp]:
            available[fp] -= 1
        else:
            missing.append(row)
    return missing


def classify_missing(row: Row, orig: list[Row], plm: list[Row], demo: list[Row]) -> dict:
    strict = fingerprint(row, FIELDS)
    identity = fingerprint(row, IDENTITY_FIELDS)
    nm = fingerprint(row, NAME_MODEL_FIELDS)

    def count(rows: list[Row], fp_fields: tuple[str, ...], target: tuple[str, ...]) -> int:
        return sum(fingerprint(x, fp_fields) == target for x in rows)

    return {
        "expected": display(row),
        "strict_count": {
            "orig": count(orig, FIELDS, strict),
            "plm": count(plm, FIELDS, strict),
            "demo": count(demo, FIELDS, strict),
        },
        "identity_count": {
            "orig": count(orig, IDENTITY_FIELDS, identity),
            "plm": count(plm, IDENTITY_FIELDS, identity),
            "demo": count(demo, IDENTITY_FIELDS, identity),
        },
        "name_model_count": {
            "orig": count(orig, NAME_MODEL_FIELDS, nm),
            "plm": count(plm, NAME_MODEL_FIELDS, nm),
            "demo": count(demo, NAME_MODEL_FIELDS, nm),
        },
    }


def load_actual_docx(path: Path) -> list[Row]:
    """读取 Demo DOCX 的两张输出表，仅保留数据行。"""
    from docx import Document

    doc = Document(str(path))
    out: list[Row] = []
    t1_fields = ("序号", "位号", "关键件名称", "型号", "规格材料", "制造商",
                 "生产企业", "认证标准", "证书号")
    t2_fields = ("序号", "位号", "关键件名称", "型号", "规格材料", "制造商",
                 "生产企业", "本次使用", "备注")
    for table_no, table in enumerate(doc.tables, 1):
        fields = t1_fields if table_no == 1 else t2_fields
        for physical_index, tr in enumerate(table.rows[1:], start=2):
            texts = [c.text.strip() for c in tr.cells]
            if texts and texts[0] and len(set(texts)) == 1:
                continue
            if not any(texts):
                continue
            data = {field: texts[i] if i < len(texts) else "" for i, field in enumerate(fields)}
            data["table"] = table_no
            data["row_index"] = physical_index
            out.append(Row(**data))
    return out


def summarize(rows: list[Row]) -> dict[str, int]:
    return {f"table_{t}": sum(r.table == t for r in rows) for t in (1, 2)} | {"total": len(rows)}


def diff_summary(diffs: list[DiffItem]) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for table in (1, 2):
        result[f"table_{table}"] = Counter(d.type.value for d in diffs if d.table == table)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default=str(ROOT / "runs" / "accuracy_gap_2026-07-27"))
    args = parser.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("解析业务期望清单（Word COM）...")
    expected = parse_document(str(EXPECTED))
    orig = load_rows(ORIG_JSON)
    plm = load_rows(PLM_JSON)
    diffs = run_diff(orig, plm, load_rules())
    demo = [d.plm or d.orig for d in diffs if d.plm or d.orig]

    result = {
        "expected_counts": summarize(expected),
        "orig_counts": summarize(orig),
        "plm_counts": summarize(plm),
        "diff_counts": diff_summary(diffs),
        "demo_theoretical_counts": summarize(demo),
        "missing_by_table": {},
    }
    print("计数：", json.dumps({k: v for k, v in result.items() if k.endswith("counts")}, ensure_ascii=False))

    all_missing: list[dict] = []
    for table in (1, 2):
        exp_t = [r for r in expected if r.table == table]
        demo_t = [r for r in demo if r.table == table]
        missing = multiset_missing(exp_t, demo_t, FIELDS)
        result["missing_by_table"][str(table)] = {
            "expected": len(exp_t),
            "demo": len(demo_t),
            "strict_missing": len(missing),
        }
        for row in missing:
            item = classify_missing(row, [r for r in orig if r.table == table],
                                    [r for r in plm if r.table == table], demo_t)
            item["table"] = table
            all_missing.append(item)

    result["strict_missing_total"] = len(all_missing)
    result["strict_missing_by_table"] = Counter(str(x["table"]) for x in all_missing)
    categories = Counter()
    for item in all_missing:
        s = item["strict_count"]
        i = item["identity_count"]
        n = item["name_model_count"]
        if i["demo"]:
            category = "demo_identity_only_content_diff"
        elif i["orig"] or i["plm"]:
            category = "input_identity_but_not_demo"
        elif n["orig"] or n["plm"]:
            category = "input_name_model_only"
        else:
            category = "not_in_input_identity"
        if s["orig"] or s["plm"]:
            category += "+strict_input_match"
        categories[category] += 1
    result["missing_categories"] = categories
    result["missing_rows"] = all_missing

    # 额外读取现有实际 DOCX，验证 theoretical -> actual 的数据行多重集。
    result_dir_candidates = sorted(BASE.glob("result_东芝85ZXSF_*"))
    if result_dir_candidates:
        merged_path = result_dir_candidates[-1] / "整合版关键件清单.docx"
        if merged_path.exists():
            actual = load_actual_docx(merged_path)
            result["actual_docx_counts"] = summarize(actual)
            result["actual_docx_strict_missing_vs_theoretical"] = len(
                multiset_missing(demo, actual, FIELDS)
            )
            result["theoretical_strict_missing_vs_actual_docx"] = len(
                multiset_missing(actual, demo, FIELDS)
            )

    json_path = out_dir / "diagnosis.json"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path = out_dir / "diagnosis.md"
    lines = [
        "# 东芝 85ZXSF 业务期望清单逐行差异诊断",
        "",
        "## 1. 计数",
        "",
        f"- 业务期望：{result['expected_counts']}",
        f"- 原始输入缓存：{result['orig_counts']}",
        f"- PLM 输入缓存：{result['plm_counts']}",
        f"- Demo 理论输出：{result['demo_theoretical_counts']}",
        f"- diff 分类：{result['diff_counts']}",
        f"- 业务期望严格指纹未被 Demo 覆盖：{result['strict_missing_total']} 条",
        "",
        "## 2. 未覆盖行分类",
        "",
    ]
    for key, count in categories.items():
        lines.append(f"- `{key}`：{count}")
    lines += ["", "## 3. 业务期望中未被 Demo 严格指纹覆盖的行", ""]
    for idx, item in enumerate(all_missing, 1):
        e = item["expected"]
        lines.append(
            f"{idx}. 表{e['table']} 期望物理行 `{e['row_index']}`；"
            f"名称=`{e['关键件名称']}`；型号=`{e['型号']}`；"
            f"规格=`{e['规格材料']}`；证书=`{e['证书号']}`；"
            f"严格命中 orig/plm/demo={item['strict_count']['orig']}/"
            f"{item['strict_count']['plm']}/{item['strict_count']['demo']}；"
            f"身份命中={item['identity_count']['orig']}/"
            f"{item['identity_count']['plm']}/{item['identity_count']['demo']}；"
            f"名称+型号命中={item['name_model_count']['orig']}/"
            f"{item['name_model_count']['plm']}/{item['name_model_count']['demo']}"
        )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("严格未覆盖：", result["strict_missing_total"])
    print("分类：", dict(categories))
    print("诊断 JSON：", json_path)
    print("诊断报告：", report_path)
    print("DIAGNOSE_EXPECTED_GAP_DONE")


if __name__ == "__main__":
    main()
