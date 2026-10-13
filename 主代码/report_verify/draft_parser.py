"""报告草稿 DRAFT 解析器，所有锚点都属于 DRAFT。"""
from __future__ import annotations

from .document_parser import parse_target_tables
from .models import LocatedBlock, UnrecognizedTable


def parse_draft_blocks(path: str) -> tuple[list[LocatedBlock], list[UnrecognizedTable]]:
    """解析规整报告草稿中的目标块，并保留表格/行/列锚点。"""
    return parse_target_tables(path, role="DRAFT")
