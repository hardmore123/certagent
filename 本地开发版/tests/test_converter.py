"""测试 .doc → .docx 自动转换 + 解析。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from compare_core.parser.converter import _find_libreoffice, ensure_docx
from compare_core.parser import parse_document

FOLDER = ROOT.parent / "AI智能体-认证原始清单与新品清单合并"
# 用真实的老 .doc 文件测试
DOC = FOLDER / "输入--【PLM导出清单-新品】85ZXSF(01)(东芝)_安全&EMC关键件清单 - 副本.doc"


def main():
    print("[1] 检测转换器可用性...")
    soffice = _find_libreoffice()
    print(f"    LibreOffice: {soffice or '未安装'}")
    import os
    print(f"    Word COM 子进程: {'可用(Windows)' if os.name == 'nt' else '不可用'}")

    if not DOC.exists():
        print(f"    测试文件不存在: {DOC}")
        return

    print(f"\n[2] 转换 .doc → .docx: {DOC.name}")
    try:
        docx_path = ensure_docx(str(DOC), work_dir=str(ROOT / "runs" / "converter_test"))
        print(f"    转换成功: {docx_path}")
    except Exception as e:
        print(f"    转换失败: {e}")
        return

    print(f"\n[3] 解析转换后的 docx...")
    rows = parse_document(str(DOC))  # parse_document 内部会自动转换
    print(f"    解析成功: {len(rows)} 行")
    from collections import Counter
    print(f"    表分布: {dict(Counter(r.table for r in rows))}")

    print("\nTEST_CONVERTER_OK")


if __name__ == "__main__":
    main()
