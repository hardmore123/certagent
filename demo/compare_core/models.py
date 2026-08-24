"""贯穿全流程的数据模型（Pydantic）。"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class Row(BaseModel):
    """一条结构化清单行。字段尽量对齐样例表头，raw 保留原始整行做兜底。"""

    table: int = 1                 # 1=关键件主清单, 2=备选件表
    group: str = ""                # 分组标题行文本（如"以下部分适用于整机结构1..."）
    序号: str = ""
    位号: str = ""
    关键件名称: str = ""           # 表2 对应"名称"
    型号: str = ""
    规格材料: str = ""
    制造商: str = ""
    生产企业: str = ""
    认证标准: str = ""
    证书号: str = ""               # 表1 的"备注"列实际存证书号
    本次使用: str = ""             # 表2 的"本次使用/备用"
    备注: str = ""
    source: str = ""               # orig / plm，整合后标来源
    row_index: int = -1            # 源表行号，用于写回定位
    raw: dict[str, Any] = Field(default_factory=dict)


class DiffType(str, Enum):
    SAME = "same"                  # 重复
    ONLY_ORIG = "only_orig"        # 仅原报告
    ONLY_PLM = "only_plm"          # 仅 PLM（新增）
    CHANGED = "changed"            # 两侧都有但内容不同


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class DiffItem(BaseModel):
    key: str
    table: int = 1
    type: DiffType
    confidence: Confidence = Confidence.MEDIUM
    orig: Optional[Row] = None
    plm: Optional[Row] = None
    changed_fields: list[str] = Field(default_factory=list)
    # LLM fuzzy 候选提名（仅当由 LLM 提名配对时非空）：pair_reason 非空即"待确认配对"。
    # 不改变确定性 diff 的守恒性——每行仍被唯一 diff 引用，只是该 CHANGED 由 LLM 提名、待人工确认。
    pair_confidence: float = 0.0
    pair_reason: str = ""


class GroupStatus(str, Enum):
    """关键件组的差异状态（比 DiffType 高一级，代表业务动作）。"""

    SAME_GROUP = "same_group"                 # 两侧选型完全一致
    REPLACED_GROUP = "replaced_group"         # 两侧都有，含替换（有 only_orig 也有 only_plm）
    EXTENDED_BY_PLM = "extended_by_plm"       # plm 是 orig 的超集
    SHRUNK_BY_PLM = "shrunk_by_plm"           # plm 是 orig 的子集
    ONLY_ORIG_GROUP = "only_orig_group"       # 仅原报告有该组
    ONLY_PLM_GROUP = "only_plm_group"         # 仅 PLM 有该组


class GroupDiff(BaseModel):
    """业务视角的"关键件组"级差异。

    组键 = (表号, 分组标题, 关键件名称)。组内选型多重集比对得到 status。
    该结构直接对应业务合并操作单元，比行级 DiffItem 更贴近对照表归纳粒度。
    """

    key: str                                  # 全局唯一：`{table}|{group}|{name}`
    table: int
    group: str = ""                           # 分组标题；空串代表顶层组
    关键件名称: str = ""
    status: GroupStatus
    orig_rows: int = 0                        # 原报告中该组的物理行数
    plm_rows: int = 0                         # PLM 中该组的物理行数
    orig_selections: int = 0                  # 原报告中该组的唯一选型数
    plm_selections: int = 0                   # PLM 中该组的唯一选型数
    common_selections: int = 0                # 两侧选型多重集的交集数
    only_orig_selections: int = 0             # 仅原报告独有的选型数
    only_plm_selections: int = 0              # 仅 PLM 独有的选型数
    diff_keys: list[str] = Field(default_factory=list)  # 该组包含的行级 DiffItem key 列表（可选，用于回溯）


class MemoryHint(BaseModel):
    """长期记忆对某条差异"身份指纹"的历史决策聚合，用于反哺建议。"""

    signature: str = ""
    accepts: int = 0
    rejects: int = 0
    total: int = 0
    dominant: str = ""             # accept / reject / ""（无强信号）
    last_verdict: str = ""
    last_reason: str = ""


class Suggestion(BaseModel):
    diff_key: str
    action: str                    # merge / mark_new / mark_diff / ignore
    reason: str = ""
    rule_id: Optional[str] = None
    confidence: Confidence = Confidence.MEDIUM
    # 记忆反哺留痕：本条建议是否被历史决策调整过 + 命中的指纹统计
    memory_applied: bool = False
    memory_hint: Optional[MemoryHint] = None


class ChangeEntry(BaseModel):
    """变更前后对照表的一行。"""

    变更项目: str
    变更前: str = "见原报告"
    变更后: str = ""


class Decision(BaseModel):
    diff_key: str
    verdict: str = "accept"        # accept / reject / modify
    note: str = ""


class AuditReport(BaseModel):
    """数据守恒审计报告（apply 之后产出）。

    校验输入 A/B 的每一行是否在整合结果中被保留或按用户决策处理，检测意外丢失。
    """

    status: str = "ok"                 # ok / warning / critical
    input_orig_rows: int = 0           # 输入 A（原始清单/旧版本）行数
    input_plm_rows: int = 0            # 输入 B（PLM导出/新版本）行数
    diff_count: int = 0
    type_counts: dict = Field(default_factory=dict)   # 各差异类型计数 same/changed/only_plm/only_orig
    a_conserved: bool = True           # A 守恒：input_orig == same+changed+only_orig
    b_conserved: bool = True           # B 守恒：input_plm  == same+changed+only_plm
    kept_count: int = 0                # 用户决策后保留的 diff 数（= 预期输出行数）
    output_rows: int = -1              # 回读整合 docx 的实际数据行数（-1=未校验）
    output_mismatch: int = 0           # 预期保留 - 实际输出（>0 少行, <0 多行）
    lost_orig: list[dict] = Field(default_factory=list)   # A 中未被任何 diff 引用（引擎丢行）
    lost_plm: list[dict] = Field(default_factory=list)    # B 中未被任何 diff 引用（引擎丢行）
    missing_in_output: list[dict] = Field(default_factory=list)  # 保留但输出 docx 里缺失（writer 丢行，按指纹定位）
    rejected_rows: int = 0             # 因用户 reject 而移除的物理行数
    same_changed_rejected: int = 0     # 被拒的 SAME/CHANGED 数（会丢双侧信息）
    repaired: bool = False             # 是否触发过补录
    recommendations: list[str] = Field(default_factory=list)
    details: list[str] = Field(default_factory=list)
