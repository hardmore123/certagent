"""候选编排器的单元测试（任务 2.1）。

这些测试只使用本地 loopback-only 传输 stub，不开 socket、不访问真实 provider、
不读取/复制/打印真实 API key 或 user key。占位凭据仅用于装配请求，不是任何真实
密钥。所有 CERT/DRAFT 文本均为占位内容。

覆盖：
- 成功候选（同逻辑子块同组、方向固定 CERT->DRAFT）；
- 同 block_type 但物理表号不同（CERT/DRAFT 独立编号）的候选被接受；
- 阈值过滤（低于阈值的候选被拒绝并回退为 invalid，不改 diffs）；
- 跨子块（block_type 不同）/ 跨组候选被本地 validator 拒绝（即使模型返回了它们）；
- 一对一守恒（重复 cert/draft 索引被拒绝）；
- 失败回退（provider 错误 / schema 非法 / 策略拒绝）不改变 result.diffs。
"""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from report_verify.llm.client import LLMClient, LLMClientError, ERROR_HTTP_ERROR
from report_verify.llm.config import LLMSettings
from report_verify.llm.orchestrator import (
    STATUS_DISABLED,
    STATUS_FALLBACK,
    STATUS_INVALID,
    STATUS_SKIPPED_POLICY,
    STATUS_SUCCESS,
    run_candidate_orchestrator,
)
from report_verify.models import (
    Anchor,
    DocumentRow,
    LocatedBlock,
    VerifyDiff,
    VerifyResult,
)

sys.path.insert(0, str(Path(__file__).parent))
from llm_contract_stub import StubResponse  # noqa: E402

_PLACEHOLDER_API_KEY = "PLACEHOLDER-API-KEY-DO-NOT-USE"
_PLACEHOLDER_USER_KEY = "PLACEHOLDER-USER-KEY-DO-NOT-USE"
_SCHEMA = "reportverify-llm-v1"
_BLOCK = "safety_list"


# ---------------------------------------------------------------------------
# 传输 stub（loopback-only）
# ---------------------------------------------------------------------------


class _RecordingTransport:
    """匹配 LLMClient(url, *, headers, params, json, timeout, stream) 的 stub。"""

    def __init__(self, response: StubResponse) -> None:
        self.response = response
        self.calls: list[dict] = []

    def __call__(self, url, *, headers, params, json, timeout, stream):
        parsed = urlsplit(url)
        if parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise AssertionError(f"stub 拒绝非 loopback URL: {url}")
        self.calls.append({"url": url, "json": json})
        return self.response


class _RaisingTransport:
    """模拟连接错误的传输 stub。"""

    def __call__(self, url, *, headers, params, json, timeout, stream):
        raise ConnectionError("stubbed connection failure")


def _sse_response(pairs_json: dict) -> StubResponse:
    """把一个 candidate 响应对象包成单行非流式 JSON stub 响应。"""

    content = json.dumps(pairs_json, ensure_ascii=False)
    body = {"choices": [{"message": {"content": content}}]}
    return StubResponse((json.dumps(body, ensure_ascii=False),))


def _fenced_sse_response(pairs_json: dict) -> StubResponse:
    """把 candidate 响应包在 ```json 围栏里，走 SSE data: 行，验证 repair。"""

    fenced = "```json\n" + json.dumps(pairs_json, ensure_ascii=False) + "\n```"
    lines = []
    for piece in (fenced,):
        delta = {"choices": [{"delta": {"content": piece}}]}
        lines.append("data: " + json.dumps(delta, ensure_ascii=False))
    lines.append("data: [DONE]")
    return StubResponse(tuple(lines))


# ---------------------------------------------------------------------------
# 配置 / client 构造
# ---------------------------------------------------------------------------


def _settings(**overrides) -> LLMSettings:
    env = {
        "REPORT_VERIFY_LLM_MODE": "candidate",
        "REPORT_VERIFY_LLM_BASE_URL": "http://127.0.0.1:8765/v1",
        "REPORT_VERIFY_LLM_MODEL": "stub-model",
        "REPORT_VERIFY_LLM_API_KEY": _PLACEHOLDER_API_KEY,
        "REPORT_VERIFY_LLM_USER_KEY": _PLACEHOLDER_USER_KEY,
        # Local loopback stub only; production defaults remain TLS-only.
        "REPORT_VERIFY_LLM_ALLOW_PLAINTEXT": "true",
        "REPORT_VERIFY_LLM_ALLOWED_HOSTS": "127.0.0.1",
    }
    env.update(overrides)
    return LLMSettings.from_env(env)


def _client(transport) -> LLMClient:
    return LLMClient(_settings(), transport=transport)


# ---------------------------------------------------------------------------
# 构造带残余池的 VerifyResult
# ---------------------------------------------------------------------------


def _row(
    name: str,
    model: str,
    *,
    table: int,
    row_idx: int,
    group: str = "",
    block_type: str = _BLOCK,
) -> DocumentRow:
    return DocumentRow(
        block_type=block_type,
        row_idx=row_idx,
        values={"关键件名称": name, "型号规格": model},
        source_table=table,
        group=group,
    )


def _display_value(row: DocumentRow) -> str:
    payload = {
        str(k): str(v or "")
        for k, v in row.values.items()
        if not k.endswith("__2")
    }
    if row.group and "分组" not in payload:
        payload["分组"] = row.group
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _residual_result(
    cert_rows: list[DocumentRow], draft_rows: list[DocumentRow]
) -> VerifyResult:
    """构造只含残余行的确定性结果。

    残余 CERT 行 -> missing_in_draft 差异；残余 DRAFT 行 -> extra_in_draft 差异。
    这些差异是编排器用来重建候选池的唯一输入，编排器绝不修改它们。

    CERT 与 DRAFT 是两个独立文档，物理表号各自独立编号；行按 block_type 归入各自
    的 LocatedBlock。
    """

    def _blocks(rows: list[DocumentRow]) -> list[LocatedBlock]:
        blocks: list[LocatedBlock] = []
        for row in rows:
            for block in blocks:
                if block.block_type == row.block_type:
                    block.rows.append(row)
                    break
            else:
                blocks.append(LocatedBlock(
                    block_type=row.block_type,
                    table_idx=row.source_table,
                    rows=[row],
                ))
        return blocks or [LocatedBlock(block_type=_BLOCK, table_idx=1, rows=[])]

    diffs: list[VerifyDiff] = []
    for r in cert_rows:
        diffs.append(VerifyDiff(
            key=f"cert-{r.source_table}-{r.row_idx}",
            block_type=r.block_type,
            item_name=r.item_name,
            diff_type="missing_in_draft",
            field="整行",
            cert_value=_display_value(r),
            cert_location=f"表{r.source_table}第{r.row_idx}行",
            match_status="unmatched",
        ))
    for r in draft_rows:
        diffs.append(VerifyDiff(
            key=f"draft-{r.source_table}-{r.row_idx}",
            block_type=r.block_type,
            item_name=r.item_name,
            diff_type="extra_in_draft",
            field="整行",
            draft_value=_display_value(r),
            draft_anchor=Anchor(table_idx=r.source_table, row_idx=r.row_idx, cell_idx=1),
            match_status="unmatched",
        ))
    return VerifyResult(
        cert_blocks=_blocks(list(cert_rows)),
        draft_blocks=_blocks(list(draft_rows)),
        diffs=diffs,
    )


class CandidateSuccessTests(unittest.TestCase):
    def test_success_produces_pending_candidate_with_fixed_direction(self):
        cert = [_row("电容C1", "AAA-100", table=1, row_idx=2, group="G1")]
        draft = [_row("电容C1改", "AAA-100", table=1, row_idx=5, group="G1")]
        result = _residual_result(cert, draft)
        before = copy.deepcopy(result.diffs)

        transport = _RecordingTransport(_sse_response({
            "schema_version": _SCHEMA,
            "pairs": [
                {"cert_index": 0, "draft_index": 0, "confidence": 0.9, "reason": "同型号"},
            ],
        }))
        out = run_candidate_orchestrator(
            result, _client(transport), _settings(), threshold=0.6,
        )

        self.assertEqual(out.status, STATUS_SUCCESS)
        self.assertEqual(len(out.candidates), 1)
        cand = out.candidates[0]
        self.assertEqual(cand.status, "pending")
        self.assertEqual(cand.source, "llm")
        # 方向固定：cert_ref 指向 CERT 行，draft_ref 指向 DRAFT 行。
        self.assertEqual(cand.cert_ref["row_idx"], 2)
        self.assertEqual(cand.draft_ref["row_idx"], 5)
        self.assertAlmostEqual(cand.confidence, 0.9)
        # 不改 diffs。
        self.assertEqual(result.diffs, before)

    def test_success_via_fenced_sse_json_repair(self):
        cert = [_row("电阻R1", "BBB-200", table=1, row_idx=3, group="G2")]
        draft = [_row("电阻R1新", "BBB-200", table=1, row_idx=7, group="G2")]
        result = _residual_result(cert, draft)

        transport = _RecordingTransport(_fenced_sse_response({
            "schema_version": _SCHEMA,
            "pairs": [
                {"cert_index": 0, "draft_index": 0, "confidence": 0.75, "reason": "型号一致"},
            ],
        }))
        out = run_candidate_orchestrator(
            result, _client(transport), _settings(), threshold=0.6,
        )
        self.assertEqual(out.status, STATUS_SUCCESS)
        self.assertEqual(len(out.candidates), 1)


class ThresholdTests(unittest.TestCase):
    def test_below_threshold_candidate_is_rejected(self):
        cert = [_row("电容C1", "AAA-100", table=1, row_idx=2, group="G1")]
        draft = [_row("电容C1改", "AAA-100", table=1, row_idx=5, group="G1")]
        result = _residual_result(cert, draft)
        before = copy.deepcopy(result.diffs)

        transport = _RecordingTransport(_sse_response({
            "schema_version": _SCHEMA,
            "pairs": [
                {"cert_index": 0, "draft_index": 0, "confidence": 0.3, "reason": "弱匹配"},
            ],
        }))
        out = run_candidate_orchestrator(
            result, _client(transport), _settings(), threshold=0.6,
        )
        self.assertEqual(out.status, STATUS_INVALID)
        self.assertEqual(len(out.candidates), 0)
        self.assertEqual(result.diffs, before)


class GuardrailTests(unittest.TestCase):
    def test_same_block_type_across_independent_table_numbering_accepted(self):
        # 跨文档回归：CERT 的 safety_list 在第 7 张表，DRAFT 的 safety_list 在第 1
        # 张表。两个文档独立编号，同 block_type 的候选必须被接受。
        cert = [_row("件A", "AAA-100", table=7, row_idx=2, group="G1")]
        draft = [_row("件A2", "AAA-100", table=1, row_idx=5, group="G1")]
        result = _residual_result(cert, draft)
        before = copy.deepcopy(result.diffs)

        transport = _RecordingTransport(_sse_response({
            "schema_version": _SCHEMA,
            "pairs": [
                {"cert_index": 0, "draft_index": 0, "confidence": 0.9,
                 "reason": "同 safety_list 子块"},
            ],
        }))
        out = run_candidate_orchestrator(
            result, _client(transport), _settings(), threshold=0.6,
        )
        self.assertEqual(out.status, STATUS_SUCCESS, out.error_message)
        self.assertEqual(len(out.candidates), 1)
        self.assertEqual(out.candidates[0].cert_ref["table_idx"], 7)
        self.assertEqual(out.candidates[0].draft_ref["table_idx"], 1)
        self.assertEqual(result.diffs, before)

    def test_cross_block_type_candidate_rejected(self):
        # safety_list ↔ emc_list 仍必须被本地 validator 拒绝。
        cert = [_row("件A", "AAA-100", table=7, row_idx=2, group="G1",
                     block_type="safety_list")]
        draft = [_row("件A2", "AAA-100", table=3, row_idx=5, group="G1",
                      block_type="emc_list")]
        result = _residual_result(cert, draft)
        before = copy.deepcopy(result.diffs)

        transport = _RecordingTransport(_sse_response({
            "schema_version": _SCHEMA,
            "pairs": [
                {"cert_index": 0, "draft_index": 0, "confidence": 0.9, "reason": "跨子块"},
            ],
        }))
        out = run_candidate_orchestrator(
            result, _client(transport), _settings(), threshold=0.6,
        )
        self.assertEqual(out.status, STATUS_INVALID)
        self.assertEqual(out.error_code, "llm_safety_rejected")
        self.assertEqual(len(out.candidates), 0)
        self.assertEqual(result.diffs, before)

    def test_cross_group_candidate_rejected(self):
        cert = [_row("件A", "AAA-100", table=1, row_idx=2, group="G1")]
        draft = [_row("件A2", "AAA-100", table=1, row_idx=5, group="G9")]
        result = _residual_result(cert, draft)

        transport = _RecordingTransport(_sse_response({
            "schema_version": _SCHEMA,
            "pairs": [
                {"cert_index": 0, "draft_index": 0, "confidence": 0.9, "reason": "跨组"},
            ],
        }))
        out = run_candidate_orchestrator(
            result, _client(transport), _settings(), threshold=0.6,
        )
        self.assertEqual(out.status, STATUS_INVALID)
        self.assertEqual(len(out.candidates), 0)

    def test_one_to_one_conservation_duplicate_index_rejected(self):
        cert = [
            _row("件A", "AAA-100", table=1, row_idx=2, group="G1"),
            _row("件B", "BBB-200", table=1, row_idx=3, group="G1"),
        ]
        draft = [
            _row("件A2", "AAA-100", table=1, row_idx=5, group="G1"),
            _row("件B2", "BBB-200", table=1, row_idx=6, group="G1"),
        ]
        result = _residual_result(cert, draft)

        # 模型违规：draft_index=0 被两个 cert 引用（破坏一对一）。
        transport = _RecordingTransport(_sse_response({
            "schema_version": _SCHEMA,
            "pairs": [
                {"cert_index": 0, "draft_index": 0, "confidence": 0.9, "reason": "x"},
                {"cert_index": 1, "draft_index": 0, "confidence": 0.9, "reason": "y"},
            ],
        }))
        out = run_candidate_orchestrator(
            result, _client(transport), _settings(), threshold=0.6,
        )
        self.assertEqual(out.status, STATUS_INVALID)
        self.assertEqual(len(out.candidates), 0)

    def test_valid_one_to_one_two_pairs_accepted(self):
        cert = [
            _row("件A", "AAA-100", table=1, row_idx=2, group="G1"),
            _row("件B", "BBB-200", table=1, row_idx=3, group="G1"),
        ]
        draft = [
            _row("件A2", "AAA-100", table=1, row_idx=5, group="G1"),
            _row("件B2", "BBB-200", table=1, row_idx=6, group="G1"),
        ]
        result = _residual_result(cert, draft)

        transport = _RecordingTransport(_sse_response({
            "schema_version": _SCHEMA,
            "pairs": [
                {"cert_index": 0, "draft_index": 0, "confidence": 0.9, "reason": "x"},
                {"cert_index": 1, "draft_index": 1, "confidence": 0.8, "reason": "y"},
            ],
        }))
        out = run_candidate_orchestrator(
            result, _client(transport), _settings(), threshold=0.6,
        )
        self.assertEqual(out.status, STATUS_SUCCESS)
        self.assertEqual(len(out.candidates), 2)
        # 每个 CERT/DRAFT 行至多引用一次。
        cert_refs = {c.cert_ref["row_idx"] for c in out.candidates}
        draft_refs = {c.draft_ref["row_idx"] for c in out.candidates}
        self.assertEqual(len(cert_refs), 2)
        self.assertEqual(len(draft_refs), 2)


class FallbackTests(unittest.TestCase):
    def test_provider_failure_falls_back_without_changing_diffs(self):
        cert = [_row("件A", "AAA-100", table=1, row_idx=2, group="G1")]
        draft = [_row("件A2", "AAA-100", table=1, row_idx=5, group="G1")]
        result = _residual_result(cert, draft)
        before = copy.deepcopy(result.diffs)

        client = LLMClient(
            _settings(REPORT_VERIFY_LLM_MAX_RETRY="0"),
            transport=_RaisingTransport(),
        )
        out = run_candidate_orchestrator(result, client, _settings(), threshold=0.6)
        self.assertEqual(out.status, STATUS_FALLBACK)
        self.assertEqual(out.error_code, ERROR_HTTP_ERROR)
        self.assertEqual(len(out.candidates), 0)
        self.assertEqual(result.diffs, before)

    def test_schema_invalid_falls_back_without_changing_diffs(self):
        cert = [_row("件A", "AAA-100", table=1, row_idx=2, group="G1")]
        draft = [_row("件A2", "AAA-100", table=1, row_idx=5, group="G1")]
        result = _residual_result(cert, draft)
        before = copy.deepcopy(result.diffs)

        transport = _RecordingTransport(_sse_response({
            "schema_version": "wrong-version",
            "pairs": [],
        }))
        out = run_candidate_orchestrator(
            result, _client(transport), _settings(), threshold=0.6,
        )
        self.assertEqual(out.status, STATUS_INVALID)
        self.assertEqual(result.diffs, before)

    def test_mode_off_is_disabled_and_no_provider_call(self):
        cert = [_row("件A", "AAA-100", table=1, row_idx=2, group="G1")]
        draft = [_row("件A2", "AAA-100", table=1, row_idx=5, group="G1")]
        result = _residual_result(cert, draft)

        transport = _RecordingTransport(_sse_response({"schema_version": _SCHEMA, "pairs": []}))
        off_settings = _settings(REPORT_VERIFY_LLM_MODE="off")
        out = run_candidate_orchestrator(
            result, LLMClient(off_settings, transport=transport), off_settings,
        )
        self.assertEqual(out.status, STATUS_DISABLED)
        self.assertEqual(len(transport.calls), 0)

    def test_no_residual_pool_skips_provider(self):
        # 只有 CERT 残余，没有 DRAFT 残余：无法配对，跳过 provider。
        cert = [_row("件A", "AAA-100", table=1, row_idx=2, group="G1")]
        result = _residual_result(cert, [])

        transport = _RecordingTransport(_sse_response({"schema_version": _SCHEMA, "pairs": []}))
        out = run_candidate_orchestrator(
            result, _client(transport), _settings(), threshold=0.6,
        )
        self.assertEqual(out.status, STATUS_SKIPPED_POLICY)
        self.assertEqual(len(transport.calls), 0)


if __name__ == "__main__":
    unittest.main()
