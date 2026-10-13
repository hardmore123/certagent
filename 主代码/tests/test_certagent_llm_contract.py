from __future__ import annotations

import json
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

# The test deliberately exercises the current CertAgent adapter as a read-only
# contract reference.  It does not import or modify CertAgent production files.
CERTAGENT_DEMO = Path(__file__).resolve().parents[2] / "CertAgent" / "demo"
_certagent_demo_path = str(CERTAGENT_DEMO)
_certagent_path_added = _certagent_demo_path not in sys.path
if _certagent_path_added:
    sys.path.insert(0, _certagent_demo_path)
try:
    from compare_core.config import config as certagent_config  # noqa: E402
    from compare_core.suggester.llm_suggester import (  # noqa: E402
        LLMSuggester,
        _repair_json,
    )
    from compare_core.suggester.llm_suggester import _read_sse_stream  # noqa: E402
finally:
    # Keep CertAgent's package importable above, but do not shadow ReportVerify
    # modules for tests discovered after this module.
    if _certagent_path_added:
        sys.path.remove(_certagent_demo_path)

from llm_contract_stub import LocalOpenAIStub, response_from_fixture  # noqa: E402


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "llm_contract"


class CertAgentLLMContractTests(unittest.TestCase):
    """Verify the approved CertAgent request/response contract locally only."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(
            (FIXTURE_DIR / "request_contract.json").read_text(encoding="utf-8")
        )

    def _call_certagent(self, response_fixture: str, *, user_key: str | None = None):
        contract = self.contract
        configured_user_key = contract["user_key"] if user_key is None else user_key
        stub = LocalOpenAIStub(response_from_fixture(FIXTURE_DIR / response_fixture))

        # Patch only the transport and in-memory placeholder settings.  The
        # stub rejects non-loopback URLs and never opens a socket.
        with ExitStack() as stack:
            for name, value in {
                "LLM_BASE_URL": contract["base_url"],
                "LLM_API_KEY": contract["api_key"],
                "LLM_MODEL": contract["model"],
                "LLM_USER_KEY": configured_user_key,
                "LLM_TIMEOUT": contract["timeout_seconds"],
                "LLM_MAX_RETRY": 0,
            }.items():
                stack.enter_context(patch.object(certagent_config, name, value))
            stack.enter_context(patch("requests.post", new=stub.post))
            content = LLMSuggester()._call_llm(contract["prompt"])

        return content, stub

    def test_request_uses_certagent_model_endpoint_auth_and_generation_flags(self):
        content, stub = self._call_certagent("sse_fenced_json.txt")

        self.assertEqual(len(stub.calls), 1)
        request = stub.calls[0]
        expected = self.contract["expected"]
        self.assertEqual(request.url, expected["url"])
        self.assertEqual(request.headers, expected["headers"])
        self.assertEqual(request.params, expected["params"])
        self.assertEqual(request.json_body, expected["body"])
        self.assertEqual(request.timeout, self.contract["timeout_seconds"])
        self.assertTrue(request.stream)
        self.assertTrue(content)

    def test_sse_data_chunks_done_marker_and_reasoning_are_compatible(self):
        content, stub = self._call_certagent("sse_fenced_json.txt")

        self.assertEqual(len(stub.calls), 1)
        # reasoning_content and role-only chunks are not returned as model
        # content; the three content chunks are accumulated in order.
        self.assertEqual(
            content,
            '```json\n{"changes":[{"变更项目":"型号","变更前":"P-1","变更后":"P-2"}]}\n```',
        )
        self.assertEqual(
            json.loads(_repair_json(content)),
            {"changes": [{"变更项目": "型号", "变更前": "P-1", "变更后": "P-2"}]},
        )

    def test_non_streaming_json_message_content_is_compatible(self):
        content, stub = self._call_certagent("non_stream_json.txt")

        self.assertEqual(len(stub.calls), 1)
        self.assertEqual(
            content,
            '{"changes":[{"变更项目":"认证标准","变更前":"GB-1","变更后":"GB-2"}]}',
        )
        self.assertEqual(
            json.loads(_repair_json(content)),
            {"changes": [{"变更项目": "认证标准", "变更前": "GB-1", "变更后": "GB-2"}]},
        )

    def test_repair_extracts_json_from_fence_and_surrounding_prose(self):
        raw = (FIXTURE_DIR / "repair_with_prose.txt").read_text(encoding="utf-8")

        repaired = _repair_json(raw)

        self.assertEqual(
            json.loads(repaired),
            {
                "pairs": [{
                    "orig_index": 0,
                    "plm_index": 1,
                    "confidence": 0.94,
                    "reason": "同表同组的占位候选",
                }],
            },
        )

    def test_user_key_is_optional_but_bearer_auth_remains_required(self):
        _, stub = self._call_certagent("non_stream_json.txt", user_key="")

        self.assertEqual(len(stub.calls), 1)
        request = stub.calls[0]
        self.assertEqual(request.params, {})
        self.assertEqual(request.headers["Authorization"], "Bearer stub-api-key")

    def test_direct_stream_reader_accepts_fixture_without_network(self):
        response = response_from_fixture(FIXTURE_DIR / "sse_fenced_json.txt")

        content = _read_sse_stream(response, deadline=10**12)

        self.assertIn('"变更项目":"型号"', content)
        self.assertNotIn("stub reasoning is not output content", content)


if __name__ == "__main__":
    unittest.main()
