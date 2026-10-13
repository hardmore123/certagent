"""报告草稿准确性核对 CLI。"""
from __future__ import annotations

import argparse
import json

from report_verify.env_bootstrap import load_project_env
from report_verify.pipeline import run_verification


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="核对 CERT 认证资料与 DRAFT 报告草稿")
    parser.add_argument("--cert", required=True, help="认证资料超集 docx/doc")
    parser.add_argument("--draft", required=True, help="报告草稿 docx/doc")
    parser.add_argument("--out", required=True, help="输出目录")
    parser.add_argument("--rules", default=None, help="严格归一化规则 JSON")
    parser.add_argument("--author", default="ReportVerify", help="Word 批注作者")
    parser.add_argument("--initials", default="RV", help="Word 批注缩写")
    return parser


def main() -> int:
    # Keep both startup paths consistent: load project-root .env before any
    # LLM configuration is read.  Real environment variables always win.
    load_project_env()
    args = build_parser().parse_args()
    trace = run_verification(
        args.cert, args.draft, args.out,
        rules_path=args.rules, author=args.author, initials=args.initials,
    )
    result = trace["result"]
    print(json.dumps({
        "diff_count": len(result["diffs"]),
        "warnings": result["warnings"],
        "outputs": trace["outputs"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
