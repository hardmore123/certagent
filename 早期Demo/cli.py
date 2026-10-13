"""命令行入口：核对报告草稿准确性。

用法：
    python cli.py --source 海信关键件清单.doc --report 报告草稿.docx --out runs/out
"""
from __future__ import annotations

import argparse
import json
import sys

from verify_core import run_verify


def main() -> int:
    parser = argparse.ArgumentParser(description="报告草稿准确性核对")
    parser.add_argument("--source", required=True, help="海信认证资料(A)：关键件清单 .doc/.docx")
    parser.add_argument("--report", required=True, help="认证机构报告草稿(B)：.docx")
    parser.add_argument("--out", default="runs/out", help="输出目录")
    args = parser.parse_args()

    result = run_verify(args.source, args.report, args.out)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n✅ 批注版报告：{result['commented']}")
    print(f"✅ 差异汇总：{result['summary']}")
    print(f"   差异 {result['diffs']} 项，批注锚定 {result['comment_stat']['anchored']} 处，"
          f"未锚定 {result['comment_stat']['unanchored']} 处（见汇总文档）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
