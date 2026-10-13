"""端到端编排：解析 A/B → 核对 → 输出批注版报告 + 差异汇总。"""
from __future__ import annotations

from pathlib import Path

from .differ import verify
from .models import VerifyReport
from .parser import parse_report_draft, parse_source_list
from .writer import write_comments, write_summary


def run_verify(source_path: str, report_path: str, out_dir: str) -> dict:
    """核对主流程。

    source_path: 海信认证资料(A，.doc/.docx)
    report_path: 认证机构报告草稿(B，.docx)
    out_dir:     输出目录，产出 批注版报告草稿.docx + 差异汇总.docx
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    a_rows, _ = parse_source_list(source_path)
    b_rows, report_docx = parse_report_draft(report_path)

    report: VerifyReport = verify(a_rows, b_rows)

    commented_path = str(out / "批注版报告草稿.docx")
    summary_path = str(out / "差异汇总.docx")
    comment_stat = write_comments(report_docx, report.diffs, commented_path)
    write_summary(report, summary_path)

    return {
        "a_rows": report.a_rows,
        "b_rows": report.b_rows,
        "counts": report.counts(),
        "diffs": len(report.diffs),
        "commented": commented_path,
        "comment_stat": comment_stat,
        "summary": summary_path,
    }
