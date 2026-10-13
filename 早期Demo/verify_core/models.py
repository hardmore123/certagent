"""报告草稿核对 — 数据模型（Pydantic）。

区别于 list-merge-demo：这里 A=海信认证资料(基准)，B=认证机构报告草稿(被核对)。
Row 额外记录 doc_table_index/row_index，用于把差异**批注回 B 文档原位**。
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class Row(BaseModel):
    """一条结构化清单行。字段对齐关键件清单表头，raw 保留原始整行兜底。"""

    side: str = ""                 # A=海信资料 / B=报告草稿
    block: str = "safety"          # safety=安全关键件清单 / emc=EMC关键件清单
    doc_table_index: int = -1      # 该行所在 docx 表格的物理序号(1-based)，供批注定位
    row_index: int = -1            # 该行在表格内的物理行号(1-based，表头=1)
    anchor_col: int = -1           # 批注锚点列(物理列号)，默认落在关键件名称/型号列

    group: str = ""                # 分组标题行文本
    序号: str = ""
    位号: str = ""
    关键件名称: str = ""
    型号: str = ""
    规格材料: str = ""
    制造商: str = ""
    生产企业: str = ""
    认证标准: str = ""
    证书号: str = ""
    本次使用: str = ""
    备注: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)


class VerifyType(str, Enum):
    CONSISTENT = "consistent"          # A/B 一致
    MISSING_IN_REPORT = "missing"      # A 有、报告草稿(B) 无
    EXTRA_IN_REPORT = "extra"          # 报告草稿(B) 有、A 无
    FIELD_MISMATCH = "mismatch"        # 两侧都有但字段不一致


class VerifyItem(BaseModel):
    """一条核对差异项。"""

    key: str
    block: str = "safety"
    type: VerifyType
    a_row: Optional[Row] = None
    b_row: Optional[Row] = None
    changed_fields: list[str] = Field(default_factory=list)  # FIELD_MISMATCH 的差异字段
    note: str = ""

    def describe(self) -> str:
        """人类可读的差异描述（用于批注与汇总）。"""
        name = ""
        if self.a_row:
            name = self.a_row.关键件名称 or self.a_row.型号
        elif self.b_row:
            name = self.b_row.关键件名称 or self.b_row.型号
        if self.type == VerifyType.MISSING_IN_REPORT:
            return f"【报告草稿缺失】海信资料中的「{name}」在报告草稿中未找到，请核实是否漏录。"
        if self.type == VerifyType.EXTRA_IN_REPORT:
            return f"【报告草稿多出】报告草稿中的「{name}」在海信资料中不存在，请核实来源。"
        if self.type == VerifyType.FIELD_MISMATCH:
            parts = []
            for f in self.changed_fields:
                av = getattr(self.a_row, f, "") if self.a_row else ""
                bv = getattr(self.b_row, f, "") if self.b_row else ""
                parts.append(f"{f}: 海信资料=「{av}」/ 报告草稿=「{bv}」")
            return f"【内容不一致】「{name}」存在字段差异 —— " + "；".join(parts)
        return f"「{name}」一致"


class VerifyReport(BaseModel):
    """整次核对结果汇总。"""

    items: list[VerifyItem] = Field(default_factory=list)
    a_rows: int = 0
    b_rows: int = 0

    @property
    def diffs(self) -> list[VerifyItem]:
        return [i for i in self.items if i.type != VerifyType.CONSISTENT]

    def counts(self) -> dict[str, int]:
        from collections import Counter
        return dict(Counter(i.type.value for i in self.items))
