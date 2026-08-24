"""请求/响应 Pydantic 模型。"""
from __future__ import annotations

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    user: dict


class JobSummary(BaseModel):
    job_id: str
    status: str  # queued / running / review / done / failed
    stage: str = ""
    progress: float = 0.0
    created_at: str = ""
    file_orig: str = ""
    file_plm: str = ""
    diff_count: int = 0
    error: str = ""


class DiffItemResponse(BaseModel):
    key: str
    type: str
    table: int
    confidence: str
    关键件名称: str = ""
    型号: str = ""
    规格材料: str = ""
    制造商: str = ""
    生产企业: str = ""
    认证标准: str = ""
    证书号: str = ""
    changed_fields: list[str] = []
    source_label: str = ""
    # 建议
    action: str = ""
    reason: str = ""


from typing import Union


class DecisionDetail(BaseModel):
    """单条决策的完整载荷（支持手动匹配）。

    verdict:
      accept / reject / ignore
      reject_dup   独有→与目标合并为相同（需 target_key）
      reject_pair  独有→与目标手动配对为差异（需 target_key）
      reject_same  差异→其实相同
      reject_split 差异→拆成两个独有项
    target_key: 手动匹配时指向另一侧目标行的 diff_key。
    reason:     决策理由（尤其拒绝理由），落盘进长期记忆。
    """

    verdict: str = "accept"
    target_key: str | None = None
    reason: str | None = None


class DecisionRequest(BaseModel):
    # 每个 diff_key 的决策：兼容旧格式(字符串)与新格式(DecisionDetail)。
    decisions: dict[str, Union[str, DecisionDetail]]
    # 可选：每条决策的理由（与 DecisionDetail.reason 二选一或叠加）。
    reasons: dict[str, str] = {}


class ResultResponse(BaseModel):
    job_id: str
    merged_path: str = ""
    compare_path: str = ""
    changes: list[dict] = []
    diff_summary: dict = {}
