"""Run the three parser routes on one manifest and emit comparable results."""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
CODE_ROOT = WORKSPACE_ROOT / "list-merge-demo"
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

from compare_core.models import Row  # noqa: E402
from compare_core.parser import parse_document  # noqa: E402
from parsers.docx_route import run_docx_route  # noqa: E402
from parsers.visual_route import run_visual_route  # noqa: E402

T1_FIELDS = ["关键件名称", "型号", "规格材料", "制造商", "生产企业", "认证标准", "证书号"]
T2_FIELDS = [
    "序号", "位号", "关键件名称", "型号", "规格材料", "制造商", "生产企业", "本次使用", "备注"
]
FINGERPRINT_FIELDS = [
    "table", "group", "关键件名称", "型号", "规格材料", "制造商", "生产企业",
    "认证标准", "证书号", "本次使用", "备注",
]


def _rows(value: list[dict[str, Any]]) -> list[Row]:
    return [Row(**item) for item in value]


def _ratio(rows: list[Row], field: str) -> dict[str, Any]:
    count = sum(bool(str(getattr(row, field, "")).strip()) for row in rows)
    return {"filled": count, "total": len(rows), "percent": round(count * 100 / len(rows), 2) if rows else 0}


def metrics(rows: list[Row], metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    by_table = {1: [row for row in rows if row.table == 1], 2: [row for row in rows if row.table == 2]}
    table_metrics: dict[str, Any] = {}
    for table_no, table_rows in by_table.items():
        fields = T1_FIELDS if table_no == 1 else T2_FIELDS
        table_metrics[str(table_no)] = {
            "rows": len(table_rows),
            "field_fill": {field: _ratio(table_rows, field) for field in fields},
            "groups_unique": len({row.group for row in table_rows if row.group.strip()}),
            "model_without_name": sum(bool(row.型号.strip()) and not row.关键件名称.strip() for row in table_rows),
            "spec_equals_manufacturer": sum(
                bool(row.规格材料.strip()) and row.规格材料.strip() == row.制造商.strip()
                for row in table_rows
            ),
        }
    result = {"total": len(rows), "table_1": table_metrics["1"]["rows"], "table_2": table_metrics["2"]["rows"], "by_table": table_metrics}
    if metadata and "group_event_count" in metadata:
        result["group_event_count"] = metadata["group_event_count"]
    return result


def fingerprint(row: Row) -> tuple[str, ...]:
    return tuple(str(getattr(row, field, "")).strip() for field in FINGERPRINT_FIELDS)


def compare_multiset(baseline: list[Row], candidate: list[Row]) -> dict[str, Any]:
    base = Counter(fingerprint(row) for row in baseline)
    current = Counter(fingerprint(row) for row in candidate)
    common = sum((base & current).values())
    missing = sum((base - current).values())
    extra = sum((current - base).values())
    return {
        "baseline_rows": len(baseline),
        "candidate_rows": len(candidate),
        "exact_fingerprint_matches": common,
        "missing_from_candidate": missing,
        "extra_in_candidate": extra,
        "match_percent_of_baseline": round(common * 100 / len(baseline), 2) if baseline else 0,
    }


def invoke(method: str, source: Path, work_dir: Path) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        if method == "com":
            rows = parse_document(str(source))
            payload = {
                "status": "success",
                "rows": [row.model_dump(mode="json") for row in rows],
                "metadata": {"source": str(source), "group_event_count": None},
            }
        elif method == "docx":
            payload = run_docx_route(str(source), str(work_dir))
        elif method == "visual":
            payload = run_visual_route(str(source), str(work_dir))
        else:
            raise ValueError(f"未知方法: {method}")
    except Exception as exc:  # keep one failed route from hiding other results
        payload = {"status": "failed", "rows": [], "metadata": {}, "error": f"{type(exc).__name__}: {exc}"}
    payload["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
    rows = _rows(payload.get("rows", []))
    payload["metrics"] = metrics(rows, payload.get("metadata")) if rows else {"total": 0, "table_1": 0, "table_2": 0, "by_table": {}}
    return payload


def load_manifest() -> dict[str, Any]:
    return json.loads((Path(__file__).parent / "manifest.json").read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="认证清单 parser 三路线对比")
    parser.add_argument("--methods", default="com,docx,visual", help="逗号分隔: com,docx,visual")
    parser.add_argument("--cases", default="u66q,toshiba", help="逗号分隔: u66q,toshiba")
    parser.add_argument("--output", default="", help="可选结果目录；默认 results/run_时间戳")
    parser.add_argument(
        "--enable-remote-vision", action="store_true",
        help="兼容旧命令参数；本脚本仍不会向外部服务发送文档或图片",
    )
    args = parser.parse_args()
    methods = [item.strip() for item in args.methods.split(",") if item.strip()]
    cases = [item.strip() for item in args.cases.split(",") if item.strip()]
    unknown_methods = set(methods) - {"com", "docx", "visual"}
    if unknown_methods:
        parser.error(f"未知方法: {sorted(unknown_methods)}")

    manifest = load_manifest()
    run_dir = Path(args.output) if args.output else Path(__file__).parent / "results" / (
        "run_" + datetime.now().strftime("%Y-%m-%d_%H%M%S")
    )
    run_dir = run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    all_results: list[dict[str, Any]] = []

    for case_id in cases:
        case = manifest["cases"].get(case_id)
        if not case:
            print(f"[跳过] manifest 没有样例: {case_id}")
            continue
        case_dir = run_dir / case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        for file_info in case["files"]:
            source = WORKSPACE_ROOT / file_info["path"]
            if not source.exists() or source.name.startswith("~$"):
                print(f"[跳过] 输入不存在或为临时锁文件: {source}")
                continue
            file_results: dict[str, dict[str, Any]] = {}
            for method in methods:
                print(f"[{case_id}/{file_info['id']}] {method}: {source.name}")
                method_dir = case_dir / file_info["id"] / method
                result = invoke(method, source, method_dir)
                file_results[method] = result
                output = {
                    "case": case_id,
                    "file_id": file_info["id"],
                    "source": str(source),
                    "method": method,
                    "expected": file_info.get("expected", {}),
                    **result,
                }
                result_path = method_dir / "result.json"
                result_path.parent.mkdir(parents=True, exist_ok=True)
                result_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"  status={result['status']} elapsed={result['elapsed_ms']}ms metrics={result['metrics']}")

            baseline = file_results.get("com")
            if baseline and baseline.get("status") == "success":
                base_rows = _rows(baseline.get("rows", []))
                for method, result in file_results.items():
                    if method != "com" and result.get("status") == "success":
                        result["com_multiset_compare"] = compare_multiset(base_rows, _rows(result.get("rows", [])))
                        result_path = case_dir / file_info["id"] / method / "result.json"
                        output = json.loads(result_path.read_text(encoding="utf-8"))
                        output["com_multiset_compare"] = result["com_multiset_compare"]
                        result_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

            for method, result in file_results.items():
                row = {
                    "case": case_id,
                    "file_id": file_info["id"],
                    "method": method,
                    "status": result["status"],
                    "elapsed_ms": result["elapsed_ms"],
                    "total": result["metrics"].get("total", 0),
                    "table_1": result["metrics"].get("table_1", 0),
                    "table_2": result["metrics"].get("table_2", 0),
                    "expected_total": file_info.get("expected", {}).get("total", ""),
                    "expected_table_1": file_info.get("expected", {}).get("table_1", ""),
                    "expected_table_2": file_info.get("expected", {}).get("table_2", ""),
                    "com_match_percent": "",
                    "error": result.get("error", ""),
                }
                if "com_multiset_compare" in result:
                    row["com_match_percent"] = result["com_multiset_compare"]["match_percent_of_baseline"]
                all_results.append(row)

    csv_path = run_dir / "summary.csv"
    if all_results:
        with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(all_results[0]))
            writer.writeheader()
            writer.writerows(all_results)

    md_lines = [
        "# Parser Test 0727 运行汇总",
        "",
        f"- 运行目录：`{run_dir}`",
        "- `com` 是本次输入的结构化基线；`docx` 的多重集对比只在 COM 成功时计算。",
        "- `blocked_missing_config` / `blocked_parser_invocation` 不是解析成功率，不纳入准确率结论。",
        "",
        "|样例|文件|方法|状态|耗时(ms)|总行|表1|表2|COM指纹匹配|错误|",
        "|---|---|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for item in all_results:
        md_lines.append(
            f"|{item['case']}|{item['file_id']}|{item['method']}|{item['status']}|"
            f"{item['elapsed_ms']}|{item['total']}|{item['table_1']}|{item['table_2']}|"
            f"{item.get('com_match_percent', '')}|{item['error']}|"
        )
    (run_dir / "summary.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    print(f"\nBENCHMARK_DONE: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
