"""In-process OpenAI-compatible transport stub for contract tests.

The stub deliberately does not open a socket.  It accepts the same request
shape used by CertAgent's ``requests.post`` call and returns fixture-backed
responses, while rejecting any non-loopback URL.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit


@dataclass(frozen=True)
class StubResponse:
    """Small ``requests.Response``-compatible surface used by the tests."""

    lines: tuple[str, ...]
    status_code: int = 200
    reason: str = "OK"

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"stub HTTP {self.status_code} {self.reason}")

    def iter_lines(self, decode_unicode: bool = False):
        # ``decode_unicode`` is accepted to match requests.Response.
        del decode_unicode
        yield from self.lines


@dataclass(frozen=True)
class StubRequest:
    """Captured request data, with no credential value transformed or stored."""

    url: str
    headers: dict[str, str]
    params: dict[str, str]
    json_body: Any
    timeout: float | None
    stream: bool | None


class LocalOpenAIStub:
    """A deterministic, loopback-only replacement for ``requests.post``.

    This is intentionally a transport stub rather than a provider client.  It
    records one request and always returns the response loaded by the test
    fixture.  The loopback guard makes an accidental real-provider URL fail
    before any network-capable implementation could be reached.
    """

    def __init__(self, response: StubResponse) -> None:
        self.response = response
        self.calls: list[StubRequest] = []

    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        json: Any = None,
        timeout: float | None = None,
        stream: bool | None = None,
        **kwargs: Any,
    ) -> StubResponse:
        if kwargs:
            raise AssertionError(f"unexpected requests.post arguments: {sorted(kwargs)}")

        parsed = urlsplit(url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise AssertionError(f"contract stub rejects non-loopback URL: {url}")

        self.calls.append(StubRequest(
            url=url,
            headers=dict(headers or {}),
            params=dict(params or {}),
            json_body=deepcopy(json),
            timeout=timeout,
            stream=stream,
        ))
        return self.response


def response_from_fixture(path: Path) -> StubResponse:
    """Load a text/JSONL response fixture without contacting a provider."""

    return StubResponse(tuple(path.read_text(encoding="utf-8").splitlines()))
