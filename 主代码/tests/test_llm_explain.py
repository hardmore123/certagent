"""差异解释生成入口的单元测试（任务 2.2）。

这些测试只构造本地对象与字符串 stub（caller stub）；不访问真实 provider、不读取/
复制/打印真实 API key 或 user key，也不发起任何网络请求。占位凭据仅用于装配启用
配置，不是任何真实密钥；所有 CERT/DRAFT 文本均为占位内容。

生成入口只读取既有 ``VerifyDiff`` 及其引用的 CERT/DRAFT 字段原文（经 policy 白名单/
截断/脱敏），产出待展示解释，绝不创建新字段值、不产出自动 verdict、不改变
``result.diffs``。

覆盖：
- 成功产出解释（source=llm、status=pending，且不改 diffs）；
- 未知 diff key 被拒 -> invalid，不改 diffs；
- 重复 diff key 被拒 -> invalid；
- provider 失败回退 -> fallback，不改 diffs，保留原有 review note；
- mode 未启用 -> disabled，不调用 provider；
- 自动决策字段被拒 -> invalid；
- 服务器策略关闭原文时，CERT/DRAFT 原文不进入 payload。
"""
from __future__ import annotations

import copy
import json
import unittest

from report_verify.llm.client import ERROR_HTTP_ERROR, LLMCallMetadata, LLMRawResult
from report_verify.llm.config import LLMSettings
from report_verify.llm.explain import (
    EXPLANATION_SOURCE_LLM,
    EXPLANATION_STATUS_PENDING,
    STATUS_DISABLED,
    STATUS_FALLBACK,
    STATUS_INVALID,
    STATUS_SKIPPED_POLICY,
    STATUS_SUCCESS,
    generate_diff_explanations,
)
from report_verify.llm.policy import ServerLLMPolicy
from report_verify.models import VerifyDiff, VerifyResult

_SCHEMA = "reportverify-llm-v1"

# 占位凭据值，仅用于构造启用配置；不是任何真实密钥。
_PLACEHOLDER_API_KEY = "PLACEHOLDER-API-KEY-DO-NOT-USE"


def _enabled_settings(mode: str = "explain", **overrides) -> LLMSettings:
    env = {
        "REPORT_VERIFY_LLM_MODE": mode,
        "REPORT_VERIFY_LLM_BASE_URL": "https://approved.example/v1",
        "REPORT_VERIFY_LLM_MODEL": "configured-model",
        "REPORT_VERIFY_LLM_API_KEY": _PLACEHOLDER_API_KEY,
        "REPORT_VERIFY_LLM_ALLOWED_HOSTS": "approved.example",
    }
    env.update(overrides)
    return LLMSettings.from_env(env)


def _result_with_diffs() -> VerifyResult:
    diffs = [
        VerifyDiff(
            key="k-safety-1",
            block_type="安全关键件清单",
            item_name="电源",
            diff_type="field_mismatch",
            field="型号",
            cert_value="AAA-100",
            draft_value="AAA-200",
            review_note="人工原有备注-保留",
        ),
        VerifyDiff(
            key="k-emc-1",
            block_type="EMC关键件清单",
            item_name="滤波器",
            diff_type="missing_in_draft",
            field="厂商",
            cert_value="厂A",
        ),
    ]
    return VerifyResult(diffs=diffs)


def _explain_json(explanations) -> str:
    return json.dumps(
        {"schema_version": _SCHEMA, "explanations": explanations},
        ensure_ascii=False,
    )


class ExplainSuccessTest(unittest.TestCase):
    """成功产出解释，标 source=llm/status=pending，且不改 diffs。"""

    def test_success_produces_pending_explanations_without_touching_diffs(self):
        result = _result_with_diffs()
        before = copy.deepcopy(result.diffs)

        seen_payload = {}

        def caller(payload):
            # payload 是受 policy 约束的最小结构；只含白名单字段与已存在原文。
            seen_payload["capability"] = payload["capability"]
            seen_payload["rows"] = payload["rows"]
            return _explain_json([
                {
                    "diff_key": "k-safety-1",
                    "explanation": "型号由 AAA-100 变为 AAA-200",
                    "risk": "需确认是否为等效替代",
                },
                {
                    "diff_key": "k-emc-1",
                    "explanation": "草稿缺少滤波器厂商",
                    "risk": "可能遗漏关键件",
                },
            ])

        out = generate_diff_explanations(
            result, _enabled_settings(), caller=caller,
        )

        self.assertEqual(out.status, STATUS_SUCCESS)
        self.assertEqual(len(out.explanations), 2)
        for exp in out.explanations:
            self.assertEqual(exp.source, EXPLANATION_SOURCE_LLM)
            self.assertEqual(exp.status, EXPLANATION_STATUS_PENDING)
            self.assertIn(exp.diff_key, {"k-safety-1", "k-emc-1"})

        # 不改 diffs，保留原有 review note。
        self.assertTrue(out.diffs_unchanged)
        self.assertEqual(result.diffs, before)
        self.assertEqual(result.diffs[0].review_note, "人工原有备注-保留")

        # payload 只走 explain 能力，且行内只含 diff_key 与既有原文。
        self.assertEqual(seen_payload["capability"], "explain")
        keys = {k for row in seen_payload["rows"] for k in row}
        self.assertIn("diff_key", keys)
        self.assertIn("cert_value", keys)

        # 元数据脱敏：CERT/DRAFT 字段原文不写入 metadata。
        self.assertNotIn("AAA-100", json.dumps(out.metadata, ensure_ascii=False))
        self.assertNotIn("AAA-200", json.dumps(out.metadata, ensure_ascii=False))

    def test_empty_explanations_still_success(self):
        result = _result_with_diffs()
        out = generate_diff_explanations(
            result, _enabled_settings(),
            caller=lambda payload: _explain_json([]),
        )
        self.assertEqual(out.status, STATUS_SUCCESS)
        self.assertEqual(out.explanations, ())


class ExplainClientInjectionTest(unittest.TestCase):
    """可注入 client 时复用 repair/调用摘要，仍不触碰确定性差异。"""

    def test_client_stub_response_is_repaired_and_summarized(self):
        result = _result_with_diffs()
        before = copy.deepcopy(result.diffs)

        class StubClient:
            def __init__(self):
                self.calls = []

            def complete_raw(self, messages, *, schema_version, request_id):
                self.calls.append({
                    "messages": messages,
                    "schema_version": schema_version,
                    "request_id": request_id,
                })
                response = _explain_json([{
                    "diff_key": "k-safety-1",
                    "explanation": "型号存在差异",
                    "risk": "需人工核对",
                }])
                return LLMRawResult(
                    content=f"```json\\n{response}\\n```",
                    metadata=LLMCallMetadata(
                        provider_host="stub.local",
                        model="stub-model",
                        schema_version=schema_version,
                        attempts=1,
                        elapsed_ms=2,
                        transport="sse",
                        status="success",
                        request_sha256="request-hash",
                        response_sha256="response-hash",
                    ),
                )

        client = StubClient()
        out = generate_diff_explanations(
            result,
            _enabled_settings(),
            client=client,
            trace_id="trace-local",
        )

        self.assertEqual(out.status, STATUS_SUCCESS)
        self.assertEqual(len(out.explanations), 1)
        self.assertEqual(out.explanations[0].source, EXPLANATION_SOURCE_LLM)
        self.assertEqual(out.explanations[0].status, EXPLANATION_STATUS_PENDING)
        self.assertEqual(result.diffs, before)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(out.metadata["call"]["provider_host"], "stub.local")
        self.assertNotIn("型号存在差异", json.dumps(out.metadata, ensure_ascii=False))


class ExplainUnknownDiffKeyTest(unittest.TestCase):
    """未知 diff key 被拒，回退为 invalid，不改 diffs。"""

    def test_unknown_diff_key_is_rejected(self):
        result = _result_with_diffs()
        before = copy.deepcopy(result.diffs)

        out = generate_diff_explanations(
            result, _enabled_settings(),
            caller=lambda payload: _explain_json([
                {
                    "diff_key": "does-not-exist",
                    "explanation": "凭空创造的差异",
                    "risk": "x",
                }
            ]),
        )
        self.assertEqual(out.status, STATUS_INVALID)
        self.assertEqual(out.explanations, ())
        self.assertEqual(result.diffs, before)


class ExplainDuplicateDiffKeyTest(unittest.TestCase):
    """同一 diff key 重复解释被拒，回退为 invalid。"""

    def test_duplicate_diff_key_is_rejected(self):
        result = _result_with_diffs()
        before = copy.deepcopy(result.diffs)

        out = generate_diff_explanations(
            result, _enabled_settings(),
            caller=lambda payload: _explain_json([
                {"diff_key": "k-safety-1", "explanation": "a", "risk": "x"},
                {"diff_key": "k-safety-1", "explanation": "b", "risk": "y"},
            ]),
        )
        self.assertEqual(out.status, STATUS_INVALID)
        self.assertEqual(out.explanations, ())
        self.assertEqual(result.diffs, before)


class ExplainAutoVerdictRejectedTest(unittest.TestCase):
    """输出中出现自动决策字段被拒。"""

    def test_auto_verdict_field_is_rejected(self):
        result = _result_with_diffs()
        payload = json.dumps({
            "schema_version": _SCHEMA,
            "explanations": [{
                "diff_key": "k-safety-1",
                "explanation": "带越权字段",
                "risk": "x",
                "verdict": "accept",
            }],
        }, ensure_ascii=False)
        out = generate_diff_explanations(
            result, _enabled_settings(),
            caller=lambda p: payload,
        )
        self.assertEqual(out.status, STATUS_INVALID)


class ExplainFallbackTest(unittest.TestCase):
    """provider 调用异常回退 fallback，不改 diffs，保留 review note。"""

    def test_provider_exception_is_fallback(self):
        result = _result_with_diffs()
        before = copy.deepcopy(result.diffs)

        def caller(payload):
            raise RuntimeError("simulated provider failure")

        out = generate_diff_explanations(
            result, _enabled_settings(), caller=caller,
        )
        self.assertEqual(out.status, STATUS_FALLBACK)
        self.assertEqual(out.error_code, ERROR_HTTP_ERROR)
        self.assertEqual(out.explanations, ())
        self.assertTrue(out.diffs_unchanged)
        self.assertEqual(result.diffs, before)
        self.assertEqual(result.diffs[0].review_note, "人工原有备注-保留")
        # 失败元数据不泄露正文。
        self.assertNotIn("simulated provider failure",
                         json.dumps(out.to_dict(), ensure_ascii=False))

    def test_schema_invalid_falls_back(self):
        result = _result_with_diffs()
        out = generate_diff_explanations(
            result, _enabled_settings(),
            caller=lambda payload: _explain_json_wrong_version(),
        )
        self.assertEqual(out.status, STATUS_INVALID)


def _explain_json_wrong_version() -> str:
    return json.dumps(
        {"schema_version": "wrong-version", "explanations": []},
        ensure_ascii=False,
    )


class ExplainDisabledTest(unittest.TestCase):
    """mode 未启用 explain 能力时 disabled，且不调用 provider。"""

    def test_mode_off_is_disabled(self):
        result = _result_with_diffs()
        called = {"hit": False}

        def caller(payload):  # pragma: no cover - 不应被调用
            called["hit"] = True
            return _explain_json([])

        out = generate_diff_explanations(
            result, _enabled_settings(mode="off"), caller=caller,
        )
        self.assertEqual(out.status, STATUS_DISABLED)
        self.assertFalse(called["hit"])

    def test_candidate_only_mode_is_disabled_for_explain(self):
        result = _result_with_diffs()
        out = generate_diff_explanations(
            result, _enabled_settings(mode="candidate"),
            caller=lambda payload: _explain_json([]),
        )
        self.assertEqual(out.status, STATUS_DISABLED)

    def test_candidate_explain_mode_enables_explain(self):
        result = _result_with_diffs()
        out = generate_diff_explanations(
            result, _enabled_settings(mode="candidate_explain"),
            caller=lambda payload: _explain_json([
                {"diff_key": "k-safety-1", "explanation": "ok", "risk": "x"},
            ]),
        )
        self.assertEqual(out.status, STATUS_SUCCESS)


class ExplainSkippedPolicyTest(unittest.TestCase):
    """无差异 / 未接入 client 时 skipped_policy，不改 diffs。"""

    def test_no_diffs_is_skipped_policy(self):
        result = VerifyResult(diffs=[])
        called = {"hit": False}

        def caller(payload):  # pragma: no cover
            called["hit"] = True
            return _explain_json([])

        out = generate_diff_explanations(
            result, _enabled_settings(), caller=caller,
        )
        self.assertEqual(out.status, STATUS_SKIPPED_POLICY)
        self.assertFalse(called["hit"])

    def test_no_caller_is_skipped_policy(self):
        result = _result_with_diffs()
        out = generate_diff_explanations(
            result, _enabled_settings(), caller=None,
        )
        self.assertEqual(out.status, STATUS_SKIPPED_POLICY)
        self.assertEqual(out.explanations, ())


class ExplainOriginalTextPolicyTest(unittest.TestCase):
    """服务器策略关闭原文时，CERT/DRAFT 原文不进入 payload。"""

    def test_original_text_disabled_strips_cert_draft_values(self):
        result = _result_with_diffs()
        seen = {}

        def caller(payload):
            seen["rows"] = payload["rows"]
            seen["allow_original_text"] = payload["metadata"]["allow_original_text"]
            return _explain_json([
                {"diff_key": "k-safety-1", "explanation": "ok", "risk": "x"},
            ])

        settings = _enabled_settings(
            REPORT_VERIFY_LLM_ALLOW_ORIGINAL_TEXT="false",
        )
        out = generate_diff_explanations(result, settings, caller=caller)

        self.assertEqual(out.status, STATUS_SUCCESS)
        self.assertFalse(seen["allow_original_text"])
        # 原文字段被 policy 丢弃，任何行都不含 cert_value/draft_value。
        for row in seen["rows"]:
            self.assertNotIn("cert_value", row)
            self.assertNotIn("draft_value", row)
        # diff_key 仍在，解释仍可产出。
        keys = {k for row in seen["rows"] for k in row}
        self.assertIn("diff_key", keys)


class ExplainSerializationTest(unittest.TestCase):
    """to_dict 输出脱敏，不含 prompt/response 原文或凭据。"""

    def test_explanation_set_to_dict_shape(self):
        result = _result_with_diffs()
        out = generate_diff_explanations(
            result, _enabled_settings(),
            caller=lambda payload: _explain_json([{
                "diff_key": "k-safety-1",
                "explanation": "ok",
                "risk": "x",
            }]),
        )
        data = out.to_dict()
        self.assertEqual(data["status"], STATUS_SUCCESS)
        self.assertTrue(data["diffs_unchanged"])
        self.assertEqual(len(data["explanations"]), 1)
        exp = data["explanations"][0]
        self.assertEqual(exp["source"], EXPLANATION_SOURCE_LLM)
        self.assertEqual(exp["status"], EXPLANATION_STATUS_PENDING)
        self.assertNotIn("prompt", json.dumps(data, ensure_ascii=False))


def _make_diffs(n: int) -> VerifyResult:
    """构造 n 条 diff_key 唯一的占位差异（k0..k{n-1}）。所有文本均为占位内容。"""

    diffs = [
        VerifyDiff(
            key=f"k{i}",
            block_type="安全关键件清单",
            item_name=f"item{i}",
            diff_type="field_mismatch",
            field="型号",
            cert_value=f"C{i}",
            draft_value=f"D{i}",
        )
        for i in range(n)
    ]
    return VerifyResult(diffs=diffs)


class ExplainBatchingTest(unittest.TestCase):
    """差异数 > max_rows 时按策略上限分批，每批一次调用，解释合并。"""

    def test_diffs_over_max_rows_split_into_batches_and_merged(self):
        result = _make_diffs(5)
        before = copy.deepcopy(result.diffs)
        # 直接传 ServerLLMPolicy 以设置小的 max_rows；5 条 + max_rows=2 -> 3 批。
        policy = ServerLLMPolicy(mode="explain", max_rows=2)

        calls: list[list[str]] = []

        def caller(payload):
            rows = payload["rows"]
            calls.append([r["diff_key"] for r in rows])
            # 每批仅对本批 payload 中出现的 diff_key 产出解释。
            return _explain_json([
                {"diff_key": r["diff_key"], "explanation": "e", "risk": "x"}
                for r in rows
            ])

        # max_workers=1：串行执行，调用顺序即批次顺序，便于断言批大小序列。
        out = generate_diff_explanations(
            result, policy, caller=caller, max_workers=1,
        )

        self.assertEqual(out.status, STATUS_SUCCESS)
        # 3 批，每批一次调用，批大小分别为 2/2/1。
        self.assertEqual(len(calls), 3)
        self.assertEqual([len(c) for c in calls], [2, 2, 1])
        # 5 条解释被正确合并，来自所有批。
        self.assertEqual(len(out.explanations), 5)
        self.assertEqual(
            {e.diff_key for e in out.explanations},
            {f"k{i}" for i in range(5)},
        )
        for e in out.explanations:
            self.assertEqual(e.source, EXPLANATION_SOURCE_LLM)
            self.assertEqual(e.status, EXPLANATION_STATUS_PENDING)
        # 分批计数写入脱敏 metadata。
        self.assertEqual(out.metadata["batch_total"], 3)
        self.assertEqual(out.metadata["batch_success"], 3)
        self.assertEqual(out.metadata["batch_failed"], 0)
        # diffs 只读、不改。
        self.assertTrue(out.diffs_unchanged)
        self.assertEqual(result.diffs, before)
        # 原文不写入 metadata。
        self.assertNotIn("C0", json.dumps(out.metadata, ensure_ascii=False))


class ExplainBatchIsolationTest(unittest.TestCase):
    """每批 known_diff_keys 严格限定为本批；跨批 diff_key 不会被误采纳。"""

    def test_cross_batch_diff_key_is_not_adopted(self):
        result = _make_diffs(2)  # k0, k1
        before = copy.deepcopy(result.diffs)
        policy = ServerLLMPolicy(mode="explain", max_rows=1)  # 2 批，每批 1 条

        def caller(payload):
            current = payload["rows"][0]["diff_key"]
            other = "k1" if current == "k0" else "k0"
            # 引用**另一批**的 diff_key —— 该 key 全局存在，但不在本批已知集合。
            # 若无按批隔离，会被误采纳；有隔离则本批被判 invalid。
            return _explain_json([
                {"diff_key": other, "explanation": "cross", "risk": "x"},
            ])

        out = generate_diff_explanations(result, policy, caller=caller)

        # 两批都只引用了不属于本批的 diff_key -> 两批都 invalid -> 整体 invalid。
        self.assertEqual(out.status, STATUS_INVALID)
        self.assertEqual(out.explanations, ())
        self.assertEqual(out.metadata["batch_total"], 2)
        self.assertEqual(out.metadata["batch_failed"], 2)
        self.assertEqual(result.diffs, before)


class ExplainBatchAggregationTest(unittest.TestCase):
    """部分批失败时的聚合语义：>=1 批成功即 success；全失败回退分类错误码。"""

    def test_one_success_one_provider_failure_is_success(self):
        result = _make_diffs(2)  # k0, k1
        before = copy.deepcopy(result.diffs)
        policy = ServerLLMPolicy(mode="explain", max_rows=1)  # 2 批

        def caller(payload):
            key = payload["rows"][0]["diff_key"]
            if key == "k0":
                return _explain_json([
                    {"diff_key": "k0", "explanation": "ok", "risk": "x"},
                ])
            raise RuntimeError("boom on batch k1")

        out = generate_diff_explanations(result, policy, caller=caller)

        self.assertEqual(out.status, STATUS_SUCCESS)
        self.assertEqual([e.diff_key for e in out.explanations], ["k0"])
        self.assertEqual(out.metadata["batch_success"], 1)
        self.assertEqual(out.metadata["batch_failed"], 1)
        self.assertTrue(out.diffs_unchanged)
        self.assertEqual(result.diffs, before)
        # 失败批的异常正文不泄露。
        self.assertNotIn(
            "boom on batch k1", json.dumps(out.to_dict(), ensure_ascii=False)
        )

    def test_all_batches_provider_failure_is_fallback(self):
        result = _make_diffs(3)
        policy = ServerLLMPolicy(mode="explain", max_rows=1)  # 3 批

        def caller(payload):
            raise RuntimeError("total failure")

        out = generate_diff_explanations(result, policy, caller=caller)

        self.assertEqual(out.status, STATUS_FALLBACK)
        self.assertEqual(out.error_code, ERROR_HTTP_ERROR)
        self.assertEqual(out.explanations, ())
        self.assertEqual(out.metadata["batch_total"], 3)
        self.assertEqual(out.metadata["batch_failed"], 3)

    def test_all_batches_invalid_is_invalid(self):
        result = _make_diffs(2)
        policy = ServerLLMPolicy(mode="explain", max_rows=1)  # 2 批

        def caller(payload):
            # schema_version 不匹配 -> 每批都 invalid。
            return _explain_json_wrong_version()

        out = generate_diff_explanations(result, policy, caller=caller)

        self.assertEqual(out.status, STATUS_INVALID)
        self.assertEqual(out.explanations, ())
        self.assertEqual(out.metadata["batch_failed"], 2)

    def test_mixed_failure_prefers_invalid_over_policy_skip(self):
        # 一批 invalid、一批 provider 失败，无成功 -> 优先暴露真正尝试过的失败。
        result = _make_diffs(2)
        policy = ServerLLMPolicy(mode="explain", max_rows=1)

        def caller(payload):
            key = payload["rows"][0]["diff_key"]
            if key == "k0":
                return _explain_json_wrong_version()  # invalid
            raise RuntimeError("boom")  # fallback

        out = generate_diff_explanations(result, policy, caller=caller)
        # 全失败：代表性状态取 fallback/invalid（两者皆真正尝试过），非 success。
        self.assertIn(out.status, {STATUS_INVALID, STATUS_FALLBACK})
        self.assertEqual(out.explanations, ())
        self.assertEqual(out.metadata["batch_failed"], 2)


class ExplainMergeDedupTest(unittest.TestCase):
    """合并时同一 diff_key 若多批返回，保留第一条、忽略重复。"""

    def test_duplicate_diff_key_across_batches_keeps_first(self):
        from report_verify.llm.explain import (
            DiffExplanation,
            _aggregate_batches,
            _BatchResult,
        )

        b1 = _BatchResult(
            status=STATUS_SUCCESS,
            explanations=(
                DiffExplanation(diff_key="k1", explanation="first", risk="x"),
            ),
        )
        b2 = _BatchResult(
            status=STATUS_SUCCESS,
            explanations=(
                DiffExplanation(diff_key="k1", explanation="second", risk="y"),
                DiffExplanation(diff_key="k2", explanation="e2", risk="z"),
            ),
        )
        out = _aggregate_batches([b1, b2], base_metadata={})

        self.assertEqual(out.status, STATUS_SUCCESS)
        self.assertEqual([e.diff_key for e in out.explanations], ["k1", "k2"])
        first_k1 = next(e for e in out.explanations if e.diff_key == "k1")
        self.assertEqual(first_k1.explanation, "first")


class ExplainSingleBatchIdenticalTest(unittest.TestCase):
    """差异数 <= max_rows 时行为与原来一致：单批、单次调用。"""

    def test_diffs_within_max_rows_single_call(self):
        result = _result_with_diffs()  # 2 条差异
        before = copy.deepcopy(result.diffs)
        policy = ServerLLMPolicy(mode="explain", max_rows=200)

        calls: list = []

        def caller(payload):
            calls.append(payload)
            return _explain_json([
                {"diff_key": "k-safety-1", "explanation": "e", "risk": "x"},
                {"diff_key": "k-emc-1", "explanation": "e2", "risk": "y"},
            ])

        out = generate_diff_explanations(result, policy, caller=caller)

        self.assertEqual(out.status, STATUS_SUCCESS)
        # 单批、单次调用。
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(out.explanations), 2)
        self.assertEqual(out.metadata["batch_total"], 1)
        self.assertEqual(out.metadata["batch_success"], 1)
        self.assertTrue(out.diffs_unchanged)
        self.assertEqual(result.diffs, before)


class ExplainConfigurableBatchRowsTest(unittest.TestCase):
    """批大小可配置：显式参数 > settings 配置 > 默认 50，且恒夹到 policy.max_rows。"""

    @staticmethod
    def _echo_caller(calls):
        def caller(payload):
            rows = payload["rows"]
            calls.append([r["diff_key"] for r in rows])
            return _explain_json([
                {"diff_key": r["diff_key"], "explanation": "e", "risk": "x"}
                for r in rows
            ])

        return caller

    def test_settings_explain_batch_rows_drives_batch_size(self):
        # 120 条差异 + 配置 batch=50 -> 3 批（50/50/20）。
        result = _make_diffs(120)
        before = copy.deepcopy(result.diffs)
        settings = _enabled_settings(
            REPORT_VERIFY_LLM_EXPLAIN_BATCH_ROWS="50",
        )
        calls: list[list[str]] = []

        out = generate_diff_explanations(
            result, settings, caller=self._echo_caller(calls), max_workers=1,
        )

        self.assertEqual(out.status, STATUS_SUCCESS)
        self.assertEqual([len(c) for c in calls], [50, 50, 20])
        self.assertEqual(out.metadata["batch_total"], 3)
        self.assertEqual(out.metadata["batch_rows"], 50)
        self.assertEqual(len(out.explanations), 120)
        self.assertTrue(out.diffs_unchanged)
        self.assertEqual(result.diffs, before)

    def test_default_batch_rows_is_50_when_settings_unset(self):
        result = _make_diffs(120)
        settings = _enabled_settings()  # 未设置 batch rows -> 默认 50
        calls: list[list[str]] = []

        out = generate_diff_explanations(
            result, settings, caller=self._echo_caller(calls), max_workers=1,
        )

        self.assertEqual(out.status, STATUS_SUCCESS)
        self.assertEqual(out.metadata["batch_rows"], 50)
        self.assertEqual([len(c) for c in calls], [50, 50, 20])

    def test_explicit_batch_rows_overrides_settings(self):
        result = _make_diffs(120)
        settings = _enabled_settings(
            REPORT_VERIFY_LLM_EXPLAIN_BATCH_ROWS="50",
        )
        calls: list[list[str]] = []

        out = generate_diff_explanations(
            result, settings, caller=self._echo_caller(calls), batch_rows=30,
            max_workers=1,
        )

        self.assertEqual(out.status, STATUS_SUCCESS)
        self.assertEqual(out.metadata["batch_rows"], 30)
        self.assertEqual([len(c) for c in calls], [30, 30, 30, 30])

    def test_batch_rows_clamped_to_policy_max_rows(self):
        # 策略上限仍是硬上限：配置/参数都不能把批放大到 max_rows 之上。
        result = _make_diffs(10)
        policy = ServerLLMPolicy(mode="explain", max_rows=3)
        calls: list[list[str]] = []

        out = generate_diff_explanations(
            result, policy, caller=self._echo_caller(calls), batch_rows=500,
            max_workers=1,
        )

        self.assertEqual(out.status, STATUS_SUCCESS)
        self.assertEqual(out.metadata["batch_rows"], 3)
        self.assertEqual([len(c) for c in calls], [3, 3, 3, 1])
        for c in calls:
            self.assertLessEqual(len(c), policy.max_rows)

    def test_settings_batch_rows_above_policy_max_rows_is_clamped(self):
        result = _make_diffs(5)
        settings = _enabled_settings(
            REPORT_VERIFY_LLM_EXPLAIN_BATCH_ROWS="400",
        )
        calls: list[list[str]] = []

        out = generate_diff_explanations(
            result, settings, caller=self._echo_caller(calls),
        )

        # policy_from_settings 的 max_rows 为服务器策略默认 200 -> 夹到 200，单批。
        self.assertEqual(out.status, STATUS_SUCCESS)
        self.assertLessEqual(out.metadata["batch_rows"], 200)
        self.assertEqual(len(calls), 1)

    def test_policy_only_caller_uses_default_batch_rows_clamped(self):
        # 传 ServerLLMPolicy（无 settings）时用默认 50 与 max_rows 取小。
        result = _make_diffs(4)
        policy = ServerLLMPolicy(mode="explain", max_rows=200)
        calls: list[list[str]] = []

        out = generate_diff_explanations(
            result, policy, caller=self._echo_caller(calls),
        )

        self.assertEqual(out.status, STATUS_SUCCESS)
        self.assertEqual(out.metadata["batch_rows"], 50)
        self.assertEqual(len(calls), 1)


class ExplainMaxDiffsTest(unittest.TestCase):
    """解释范围上限：超过上限只解释 diffs 的前 N 条，其余不进入任何 payload。"""

    @staticmethod
    def _echo_caller(sent_keys: list[str]):
        def caller(payload):
            rows = payload["rows"]
            sent_keys.extend(r["diff_key"] for r in rows)
            return _explain_json([
                {"diff_key": r["diff_key"], "explanation": "e", "risk": "x"}
                for r in rows
            ])

        return caller

    def test_diffs_over_max_diffs_only_first_n_explained(self):
        result = _make_diffs(30)
        before = copy.deepcopy(result.diffs)
        policy = ServerLLMPolicy(mode="explain", max_rows=5)
        sent: list[str] = []

        out = generate_diff_explanations(
            result, policy, caller=self._echo_caller(sent),
            max_diffs=12, max_workers=1,
        )

        self.assertEqual(out.status, STATUS_SUCCESS)
        # 只解释前 12 条，且顺序为 diffs 原顺序。
        self.assertEqual(sent, [f"k{i}" for i in range(12)])
        self.assertEqual(
            [e.diff_key for e in out.explanations],
            [f"k{i}" for i in range(12)],
        )
        # metadata 区分总数 / 实际解释数 / 是否截断。
        self.assertEqual(out.metadata["diff_count"], 30)
        self.assertEqual(out.metadata["explained_diff_count"], 12)
        self.assertTrue(out.metadata["truncated"])
        self.assertEqual(out.metadata["explain_max_diffs"], 12)
        # 超出上限的 diff_key 不出现在任何批的 payload 中。
        for i in range(12, 30):
            self.assertNotIn(f"k{i}", sent)
        # diffs 只读、不改。
        self.assertTrue(out.diffs_unchanged)
        self.assertEqual(result.diffs, before)

    def test_within_max_diffs_is_not_truncated(self):
        result = _make_diffs(8)
        policy = ServerLLMPolicy(mode="explain", max_rows=5)
        sent: list[str] = []

        out = generate_diff_explanations(
            result, policy, caller=self._echo_caller(sent),
            max_diffs=200, max_workers=1,
        )

        self.assertEqual(out.status, STATUS_SUCCESS)
        self.assertEqual(out.metadata["diff_count"], 8)
        self.assertEqual(out.metadata["explained_diff_count"], 8)
        self.assertFalse(out.metadata["truncated"])
        self.assertEqual(len(out.explanations), 8)

    def test_settings_explain_max_diffs_drives_limit(self):
        result = _make_diffs(20)
        settings = _enabled_settings(
            REPORT_VERIFY_LLM_EXPLAIN_MAX_DIFFS="7",
        )
        sent: list[str] = []

        out = generate_diff_explanations(
            result, settings, caller=self._echo_caller(sent), max_workers=1,
        )

        self.assertEqual(out.status, STATUS_SUCCESS)
        self.assertEqual(out.metadata["explained_diff_count"], 7)
        self.assertTrue(out.metadata["truncated"])
        self.assertEqual(sent, [f"k{i}" for i in range(7)])

    def test_explicit_max_diffs_overrides_settings(self):
        result = _make_diffs(20)
        settings = _enabled_settings(
            REPORT_VERIFY_LLM_EXPLAIN_MAX_DIFFS="7",
        )
        sent: list[str] = []

        out = generate_diff_explanations(
            result, settings, caller=self._echo_caller(sent),
            max_diffs=3, max_workers=1,
        )

        self.assertEqual(out.metadata["explained_diff_count"], 3)
        self.assertEqual(sent, ["k0", "k1", "k2"])

    def test_default_max_diffs_is_500(self):
        # 默认范围上限为 DEFAULT_EXPLAIN_MAX_DIFFS=500：超出只解释前 500 条，
        # 其余差异仍完整保留确定性证据并在 metadata 标记 truncated。
        result = _make_diffs(550)
        policy = ServerLLMPolicy(mode="explain", max_rows=50)
        sent: list[str] = []

        out = generate_diff_explanations(
            result, policy, caller=self._echo_caller(sent), max_workers=1,
        )

        self.assertEqual(out.status, STATUS_SUCCESS)
        self.assertEqual(out.metadata["explain_max_diffs"], 500)
        self.assertEqual(out.metadata["explained_diff_count"], 500)
        self.assertTrue(out.metadata["truncated"])
        self.assertEqual(len(sent), 500)


class ExplainConcurrencyTest(unittest.TestCase):
    """批次并发：解释合并顺序稳定，且与串行结果完全一致。"""

    @staticmethod
    def _recording_caller(observed_order: list[str]):
        """记录实际调用顺序的 stub；第一批故意慢一点以打乱执行顺序。"""

        import threading
        import time

        lock = threading.Lock()

        def caller(payload):
            rows = payload["rows"]
            first_key = rows[0]["diff_key"]
            if first_key == "k0":
                # 让首批最后完成：并发下执行顺序被打乱，但合并顺序必须仍稳定。
                time.sleep(0.05)
            with lock:
                observed_order.append(first_key)
            return _explain_json([
                {"diff_key": r["diff_key"], "explanation": "e", "risk": "x"}
                for r in rows
            ])

        return caller

    def test_concurrent_merge_order_matches_batch_order(self):
        result = _make_diffs(8)
        before = copy.deepcopy(result.diffs)
        policy = ServerLLMPolicy(mode="explain", max_rows=2)  # 4 批
        observed: list[str] = []

        out = generate_diff_explanations(
            result, policy, caller=self._recording_caller(observed),
            max_workers=4,
        )

        self.assertEqual(out.status, STATUS_SUCCESS)
        self.assertEqual(out.metadata["batch_total"], 4)
        self.assertEqual(out.metadata["batch_success"], 4)
        self.assertEqual(out.metadata["explain_max_workers"], 4)
        # 执行顺序被打乱（首批最后完成），说明确实并发执行。
        self.assertNotEqual(observed[0], "k0")
        # 合并顺序仍严格等于批次顺序 / diffs 原顺序。
        self.assertEqual(
            [e.diff_key for e in out.explanations],
            [f"k{i}" for i in range(8)],
        )
        self.assertTrue(out.diffs_unchanged)
        self.assertEqual(result.diffs, before)

    def test_serial_and_concurrent_results_are_identical(self):
        policy = ServerLLMPolicy(mode="explain", max_rows=2)

        def caller(payload):
            rows = payload["rows"]
            return _explain_json([
                {"diff_key": r["diff_key"], "explanation": "e", "risk": "x"}
                for r in rows
            ])

        serial = generate_diff_explanations(
            _make_diffs(9), policy, caller=caller, max_workers=1,
        )
        concurrent = generate_diff_explanations(
            _make_diffs(9), policy, caller=caller, max_workers=4,
        )

        self.assertEqual(serial.status, concurrent.status)
        self.assertEqual(
            [e.to_dict() for e in serial.explanations],
            [e.to_dict() for e in concurrent.explanations],
        )
        self.assertEqual(
            serial.metadata["batch_total"], concurrent.metadata["batch_total"]
        )

    def test_concurrent_batch_isolation_and_partial_failure(self):
        """并发下仍逐批隔离 known_diff_keys，且部分失败不影响聚合语义。"""

        result = _make_diffs(4)
        policy = ServerLLMPolicy(mode="explain", max_rows=1)  # 4 批

        def caller(payload):
            key = payload["rows"][0]["diff_key"]
            if key == "k1":
                raise RuntimeError("boom on k1")
            if key == "k2":
                # 引用别批的 diff_key -> 本批 invalid（跨批隔离生效）。
                return _explain_json([
                    {"diff_key": "k0", "explanation": "cross", "risk": "x"},
                ])
            return _explain_json([
                {"diff_key": key, "explanation": "e", "risk": "x"},
            ])

        out = generate_diff_explanations(
            result, policy, caller=caller, max_workers=4,
        )

        self.assertEqual(out.status, STATUS_SUCCESS)
        # 只采纳成功批，且顺序稳定（k0 在 k3 之前）。
        self.assertEqual([e.diff_key for e in out.explanations], ["k0", "k3"])
        self.assertEqual(out.metadata["batch_success"], 2)
        self.assertEqual(out.metadata["batch_failed"], 2)

    def test_settings_explain_max_workers_is_used(self):
        result = _make_diffs(4)
        settings = _enabled_settings(
            REPORT_VERIFY_LLM_EXPLAIN_MAX_WORKERS="2",
            REPORT_VERIFY_LLM_EXPLAIN_BATCH_ROWS="1",
        )

        out = generate_diff_explanations(
            result, settings,
            caller=lambda payload: _explain_json([
                {
                    "diff_key": payload["rows"][0]["diff_key"],
                    "explanation": "e",
                    "risk": "x",
                }
            ]),
        )

        self.assertEqual(out.status, STATUS_SUCCESS)
        self.assertEqual(out.metadata["explain_max_workers"], 2)
        self.assertEqual(
            [e.diff_key for e in out.explanations],
            [f"k{i}" for i in range(4)],
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
