from .doc_parser import parse_document as _parse_via_com
from .doc_parser import load_rows_json
from .docx_parser import parse_docx


def parse_document(path: str, auto_convert: bool = True):
    """智能分派解析：
    - .docx → 纯 python-docx（无 COM，线程安全，优先）
    - .doc  → 先自动转 .docx（LibreOffice/Word 子进程），再用 python-docx；
              auto_convert=False 时回退到直接 Word COM 解析（老路径）
    """
    from pathlib import Path
    suffix = Path(path).suffix.lower()
    if suffix == ".docx":
        return parse_docx(path)
    # .doc
    if auto_convert:
        from .converter import ensure_docx
        try:
            docx_path = ensure_docx(path)
            return parse_docx(docx_path)
        except Exception:
            # 转换失败，回退到直接 COM 解析
            return _parse_via_com(path)
    return _parse_via_com(path)


__all__ = ["parse_document", "parse_docx", "load_rows_json"]
