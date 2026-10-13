"""认证资料 CERT 超集的目标子块定位器。"""
from __future__ import annotations

from .document_parser import parse_target_tables
from .models import LocatedBlock, UnrecognizedTable


def locate_cert_blocks(path: str) -> tuple[list[LocatedBlock], list[UnrecognizedTable]]:
    """定位安全、EMC、变更、产品描述四类 CERT 子块。"""
    return parse_target_tables(path, role="CERT")
