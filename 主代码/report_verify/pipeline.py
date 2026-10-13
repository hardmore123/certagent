"""ReportVerify 离线端到端流水线。"""
from __future__ import annotations

import json
from pathlib import Path

from .cert_locator import locate_cert_blocks
from .comment_writer import write_comments
from .converter import ensure_docx
from .draft_parser import parse_draft_blocks
from .models import RowDiff, VerifyResult, to_dict
from .rules import load_rules
from .summary_writer import write_summary
from .validation import validate_outputs
from .verify_differ import compare_blocks


def run_verification(
    cert_path: str,
    draft_path: str,
    out_dir: str,
    *,
    rules_path: str | None = None,
    author: str = "ReportVerify",
    initials: str = "RV",
) -> dict:
    """执行定位、逐字段核对、DRAFT 批注和差异汇总。"""
    output = Path(out_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    converted = output / "converted"
    cert_docx = ensure_docx(cert_path, str(converted))
    draft_docx = ensure_docx(draft_path, str(converted))
    rules = load_rules(rules_path)

    cert_blocks, unrecognized = locate_cert_blocks(cert_docx)
    draft_blocks, draft_unrecognized = parse_draft_blocks(draft_docx)
    row_diffs: list[RowDiff] = []
    diffs = compare_blocks(cert_blocks, draft_blocks, rules, row_diffs=row_diffs)
    warnings: list[str] = []
    if unrecognized:
        warnings.append(
            f"CERT 有 {len(unrecognized)} 张表未命中目标子块指纹，已保留元数据，需人工复核。"
        )
    if draft_unrecognized:
        warnings.append(
            f"DRAFT 有 {len(draft_unrecognized)} 张表未命中目标子块指纹，未参与字段核对。"
        )
    cert_types = {block.block_type for block in cert_blocks}
    draft_types = {block.block_type for block in draft_blocks}
    for missing_type in sorted(cert_types - draft_types):
        warnings.append(f"DRAFT 缺少 CERT 子块：{missing_type}；相关差异仅能进入汇总，无法写入批注。")

    result = VerifyResult(
        cert_blocks=cert_blocks,
        draft_blocks=draft_blocks,
        unrecognized_cert_tables=unrecognized,
        diffs=diffs,
        row_diffs=row_diffs,
        warnings=warnings,
        rule_version=rules.get("version", "strict-v1"),
    )
    annotated_path = output / "批注版报告草稿.docx"
    comment_report = write_comments(
        draft_docx, result.diffs, str(annotated_path), author=author, initials=initials
    )
    consistency = validate_outputs(result.diffs, draft_docx)
    summary_path = output / "差异汇总.docx"
    write_summary(
        result.diffs,
        str(summary_path),
        cert_name=Path(cert_path).name,
        draft_name=Path(draft_path).name,
        warnings=warnings,
    )
    trace = {
        "cert_path": str(Path(cert_path).resolve()),
        "draft_path": str(Path(draft_path).resolve()),
        "cert_docx": cert_docx,
        "draft_docx": draft_docx,
        "rules": rules,
        "result": to_dict(result),
        "comment_report": comment_report,
        "consistency": consistency,
        "outputs": {
            "annotated_draft": str(annotated_path),
            "summary": str(summary_path),
        },
    }
    (output / "verification.json").write_text(
        json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return trace
