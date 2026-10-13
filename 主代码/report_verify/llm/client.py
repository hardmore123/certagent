"""ReportVerify 的 LLM 运行时 client（任务 1.3）。

本模块把 CertAgent 当前已批准的 OpenAI-compatible 请求/响应约定适配为
ReportVerify 的运行时 client：

- 请求装配：``POST {base_url}/chat/completions``、``Authorization: Bearer
  <in-memory key>``、可选 ``user_key`` query 参数、JSON body 含
  ``model/messages/temperature=0/stream=true``；完全沿用 CertAgent 语义。
- 响应读取：SSE reader 处理 ``data: {...}``、``data: [DONE]``、空行，累积
  ``choices[0].delta.content``，忽略 ``reasoning_content`` 等非 content 字段；
  非流式则读取 ``choices[0].message.content``。两种路径都施加单行和累计响应
  字节上限（``max_response_bytes``），并处理空响应/非法 JSON。
- JSON repair：复用 CertAgent 的语法容错意图（去 ```` ```json ```` 围栏、
  截取第一个 ``{...}``）。**repair 只作语法层**，结果仍留给后续任务 1.5 的
  Schema/安全校验；本模块不实现 Schema。

安全契约：

- ``api_key`` / ``user_key`` 只驻留在内存 settings，并只出现在请求头/query
  参数中；绝不进入日志、异常消息、trace 或返回的 :class:`LLMCallMetadata`。
- 元数据只含 provider host、model、transport、attempts、耗时和 request/response
  的 SHA-256 摘要哈希等非敏感项；不含 URL query（可能带 user_key）、prompt
  原文或 response 原文。
- 异常消息里不放响应正文或凭据。

本任务范围（1.3）**只做**请求装配与响应读取。重试、总墙钟超时和断路器属于
任务 1.4：这里为它们保留清晰的接口占位（``max_retry``、``deadline``、
``breaker`` 参数与 ``attempts`` 字段），但**不实现**其控制逻辑——client 只发起
一次请求、只按传入的 ``deadline`` 做一次读取级别的墙钟检查。
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Protocol
from urllib.parse import urlsplit

from .circuit import CircuitBreaker
from .config import LLMSettings
from .policy import (
    ERROR_POLICY_DENIED,
    ServerLLMPolicy,
    authorize_provider_endpoint,
)

# 分类错误码，与 design.md 的 Error Handling 表一致。
ERROR_RESPONSE_EMPTY = "llm_response_empty"
ERROR_RESPONSE_TOO_LARGE = "llm_response_too_large"
ERROR_MISCONFIGURED = "llm_misconfigured"
ERROR_HTTP_ERROR = "llm_http_error"
ERROR_ATTEMPT_TIMEOUT = "llm_attempt_timeout"
ERROR_TOTAL_TIMEOUT = "llm_total_timeout"
ERROR_RATE_LIMITED = "llm_rate_limited"
ERROR_AUTH_FAILED = "llm_auth_failed"
ERROR_CIRCUIT_OPEN = "llm_circuit_open"

# 可重试的错误码集合（连接错误、429、暂时性 5xx、临时空响应）。
# 鉴权、策略、Schema、总墙钟超时和断路器打开都**不**在此集合内。
RETRYABLE_ERROR_CODES: frozenset[str] = frozenset({
    ERROR_HTTP_ERROR,
    ERROR_RATE_LIMITED,
    ERROR_ATTEMPT_TIMEOUT,
    ERROR_RESPONSE_EMPTY,
})

# 退避上限（秒）：指数退避但封顶，避免长时间阻塞背景任务。
DEFAULT_BACKOFF_BASE_SECONDS = 0.5
DEFAULT_BACKOFF_MAX_SECONDS = 8.0

# transport 标识。
TRANSPORT_SSE = "sse"
TRANSPORT_JSON = "json"


class LLMClientError(Exception):
    """client 层错误。``code`` 为 design.md 中的分类错误码。

    消息中绝不包含响应正文、prompt 原文或任何凭据值。
    """

    def __init__(self, code: str, message: str, *, retryable: bool | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        # ``retryable=None`` 时按错误码集合判定；显式 True/False 可覆盖。
        self._retryable_override = retryable

    @property
    def retryable(self) -> bool:
        """是否可重试；显式覆盖优先，否则按 :data:`RETRYABLE_ERROR_CODES`。"""

        if self._retryable_override is not None:
            return self._retryable_override
        return self.code in RETRYABLE_ERROR_CODES


class LLMResponseTooLarge(LLMClientError):
    """响应超过单行或累计字节上限。"""

    def __init__(self, message: str) -> None:
        super().__init__(ERROR_RESPONSE_TOO_LARGE, message)


class LLMEmptyResponse(LLMClientError):
    """SSE/JSON 均未提取到任何 content。"""

    def __init__(self, message: str = "provider 响应为空") -> None:
        super().__init__(ERROR_RESPONSE_EMPTY, message)


class LLMRateLimited(LLMClientError):
    """provider 返回 429；可在墙钟约束内有限重试。"""

    def __init__(self, message: str = "provider 返回 429") -> None:
        super().__init__(ERROR_RATE_LIMITED, message)


class LLMAuthFailed(LLMClientError):
    """provider 返回 401/403；不可重试。"""

    def __init__(self, message: str = "provider 鉴权失败") -> None:
        super().__init__(ERROR_AUTH_FAILED, message)


class LLMTotalTimeout(LLMClientError):
    """单次调用（含所有重试与退避）超过总墙钟 deadline；不可重试。"""

    def __init__(self, message: str = "超过总墙钟时限") -> None:
        super().__init__(ERROR_TOTAL_TIMEOUT, message)


class LLMCircuitOpen(LLMClientError):
    """provider 断路器打开，冷却期内不发请求。"""

    def __init__(self, message: str = "provider 断路器打开（冷却中）") -> None:
        super().__init__(ERROR_CIRCUIT_OPEN, message)


class HttpResponse(Protocol):
    """``requests.Response`` 的最小子集，便于本地 stub 替换（不开 socket）。"""

    status_code: int

    def raise_for_status(self) -> None: ...

    def iter_lines(self, decode_unicode: bool = ...) -> Iterable[Any]: ...


class HttpTransport(Protocol):
    """``requests.post`` 兼容的最小传输接口。

    默认实现延迟导入 ``requests``；测试可注入 loopback-only stub。
    """

    def __call__(
        self,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, str],
        json: Any,
        timeout: float | None,
        stream: bool,
    ) -> HttpResponse: ...


def _default_transport(
    url: str,
    *,
    headers: dict[str, str],
    params: dict[str, str],
    json: Any,
    timeout: float | None,
    stream: bool,
) -> HttpResponse:
    """默认传输：延迟导入 ``requests`` 并转发调用。"""

    import requests  # 延迟导入，避免在未启用 LLM 时引入依赖

    return requests.post(
        url,
        headers=headers,
        params=params,
        json=json,
        timeout=timeout,
        stream=stream,
    )


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def repair_json(text: str) -> str:
    """复用 CertAgent 语法容错：去 ```` ```json ```` 围栏并截取第一个 ``{...}``。

    **仅做语法层修复**，不校验 Schema、不解释业务语义；返回内容留给任务 1.5 的
    Schema/安全 validator。输入若无 JSON 对象则原样（去围栏后）返回。
    """

    t = text.strip()
    t = re.sub(r"^```(?:json)?", "", t).strip()
    t = re.sub(r"```$", "", t).strip()
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end != -1 and end > start:
        t = t[start : end + 1]
    return t


@dataclass(frozen=True)
class LLMCallMetadata:
    """一次调用的非敏感可审计元数据。

    绝不包含 URL query（可能带 user_key）、prompt 原文、response 原文或任何凭据。
    """

    provider_host: str
    model: str
    schema_version: str
    attempts: int
    elapsed_ms: int
    transport: str            # sse | json
    status: str               # success | ...
    request_sha256: str
    response_sha256: str | None = None
    fallback_reason: str = ""


@dataclass(frozen=True)
class LLMRawResult:
    """已提取但**未经 Schema 校验**的原始 content 与元数据。"""

    content: str
    metadata: LLMCallMetadata


def _default_breaker(settings: LLMSettings) -> CircuitBreaker:
    return CircuitBreaker(
        failure_threshold=settings.circuit_failure_threshold,
        cooldown_seconds=settings.circuit_cooldown_seconds,
    )


class LLMClient:
    """复用 CertAgent 请求/响应约定的运行时 client。

    任务 1.3 负责单次请求装配与响应读取；任务 1.4 在其外叠加逐次 timeout、
    有限重试、总墙钟超时（不可重试）和 provider 级断路器。

    - ``breaker``：provider 级断路器；同一 provider 实例应共享同一个断路器，
      以便跨并发任务累计连续失败并统一冷却（任务 3.2 复用）。默认按 settings
      构造独立断路器。
    - ``sleep``：退避睡眠函数，测试可注入以免真实 sleep。
    - ``clock``：墙钟函数（``time.time()`` 基准），用于计算总 deadline；测试可
      注入假时钟。
    """

    def __init__(
        self,
        settings: LLMSettings,
        *,
        transport: HttpTransport | None = None,
        breaker: CircuitBreaker | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.settings = settings
        self._transport: HttpTransport = transport or _default_transport
        self.breaker = breaker if breaker is not None else _default_breaker(settings)
        self._sleep = sleep
        self._clock = clock

    # ---- 请求装配 -----------------------------------------------------------

    def _endpoint_url(self) -> str:
        return self.settings.base_url.rstrip("/") + "/chat/completions"

    def _headers(self) -> dict[str, str]:
        # Authorization 只在内存/请求头中出现，绝不进入日志/元数据。
        return {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }

    def _params(self) -> dict[str, str]:
        # user_key 走 query 参数（沿用 CertAgent 网关约定）；为空则不带。
        return {"user_key": self.settings.user_key} if self.settings.user_key else {}

    def _body(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.settings.model,
            "messages": messages,
            "temperature": 0,
            "stream": True,
        }
        # 安全阀：仅当配置了正整数上限时才写入 max_tokens；为 0（默认/未设置）时
        # 完全不加该键，请求体与既有行为保持一致（向后兼容）。
        if self.settings.max_tokens > 0:
            body["max_tokens"] = self.settings.max_tokens
        return body

    # ---- 退避 ---------------------------------------------------------------

    def _backoff_seconds(self, attempt_index: int) -> float:
        """第 ``attempt_index`` 次失败后的退避秒数（指数、封顶）。

        ``attempt_index`` 从 1 起（第 1 次失败后退避一次再做第 2 次尝试）。
        """

        raw = DEFAULT_BACKOFF_BASE_SECONDS * (2 ** (attempt_index - 1))
        return min(raw, DEFAULT_BACKOFF_MAX_SECONDS)

    # ---- provider 激活门禁 --------------------------------------------------

    def _ensure_provider_activation(self) -> None:
        """在任何 transport 调用前执行服务器-owned 的 fail-closed 检查。

        Release gate 负责部署前检查；这里是运行时最后一道边界，防止直接构造
        ``LLMClient`` 或绕过 Web route 的调用在 host/TLS、mode allowlist 或原文
        策略未通过时发出 provider 请求。该方法只使用已解析的非 secret 策略字段；
        API key 的存在性仍由下面的配置检查处理，值不会进入错误消息。
        """

        settings = self.settings
        if settings.mode == "off":
            raise LLMClientError(
                ERROR_POLICY_DENIED,
                "LLM mode 已关闭，不允许 provider 调用",
                retryable=False,
            )
        if settings.mode not in settings.allowed_job_modes:
            raise LLMClientError(
                ERROR_POLICY_DENIED,
                "LLM mode 未通过服务器 allowlist",
                retryable=False,
            )
        if not settings.allow_original_text:
            # 当前 candidate/explain 能力依赖服务器批准的字段原文策略；在
            # 策略关闭时宁可不调用，也不把结构化降级误当成已批准能力。
            raise LLMClientError(
                ERROR_POLICY_DENIED,
                "服务器原文外发策略未批准，禁止 provider 调用",
                retryable=False,
            )
        if not settings.image_policy_valid or settings.allow_images is not False:
            raise LLMClientError(
                ERROR_POLICY_DENIED,
                "图片能力固定关闭，禁止 provider 调用",
                retryable=False,
            )
        if not settings.allowed_hosts:
            raise LLMClientError(
                ERROR_POLICY_DENIED,
                "provider host allowlist 缺失，禁止 provider 调用",
                retryable=False,
            )

        policy = ServerLLMPolicy(
            mode=settings.mode,
            allow_original_text=settings.allow_original_text,
            allowed_hosts=settings.allowed_hosts,
            allow_plaintext=settings.allow_plaintext,
            allow_job_override=settings.allow_job_override,
            allowed_job_modes=settings.allowed_job_modes,
            redaction_profile=settings.redaction_profile,
            policy_version=settings.policy_version,
        )
        endpoint = authorize_provider_endpoint(policy, settings.base_url)
        if not endpoint.authorized:
            raise LLMClientError(
                ERROR_POLICY_DENIED,
                "provider endpoint 未通过 host/TLS allowlist",
                retryable=False,
            )

    # ---- 调用（任务 1.4：重试 + 总墙钟 + 断路器） --------------------------

    def complete_raw(
        self,
        messages: list[dict[str, str]],
        *,
        schema_version: str | None = None,
        request_id: str = "",
        deadline: float | None = None,
    ) -> LLMRawResult:
        """发起调用并返回**未经 Schema 校验**的原始 content。

        叠加任务 1.4 的控制逻辑：

        - 逐次请求超时用 ``settings.timeout_seconds``。
        - 连接错误、429、暂时性 5xx、临时空响应最多重试 ``settings.max_retry``
          次，退避指数封顶。
        - 单次调用（含所有重试与退避）受总墙钟 ``settings.total_timeout_seconds``
          约束；到期立即抛不可重试的 :class:`LLMTotalTimeout`。
        - 鉴权、Schema、总超时错误不重试。
        - provider 断路器打开时不发请求，直接抛 :class:`LLMCircuitOpen`；成功/
          失败结果反馈给断路器以驱动 open/half-open/close。

        ``deadline``：可选外部墙钟绝对时间（``clock()`` 基准），与总墙钟取更早者
        作为有效 deadline。``schema_version`` 仅作元数据标识。
        """

        self._ensure_provider_activation()

        if not (self.settings.base_url and self.settings.model and self.settings.api_key):
            # 与 config.status()=misconfigured 一致；不读取任何请求体凭据。
            raise LLMClientError(
                ERROR_MISCONFIGURED,
                "LLM 未正确配置（缺 Base URL / model / api_key）",
            )

        # 有效总 deadline：外部传入 deadline 与总墙钟取更早者。
        total_deadline = self._clock() + float(self.settings.total_timeout_seconds)
        effective_deadline = total_deadline
        if deadline is not None:
            effective_deadline = min(effective_deadline, deadline)

        schema = schema_version or self.settings.response_schema_version
        max_attempts = int(self.settings.max_retry) + 1
        last_error: LLMClientError | None = None

        for attempt in range(1, max_attempts + 1):
            # 断路器：打开则不发请求。
            if not self.breaker.allow():
                raise LLMCircuitOpen()

            # 总墙钟：重试前（非首次尝试）已到期则不再发请求（不可重试）。
            # 首次尝试始终执行，让读取级 deadline 产生 attempt_timeout 语义。
            if attempt > 1 and self._clock() >= effective_deadline:
                if last_error is not None and last_error.code == ERROR_ATTEMPT_TIMEOUT:
                    raise last_error
                raise LLMTotalTimeout()

            try:
                result = self._single_attempt(
                    messages,
                    schema=schema,
                    attempts=attempt,
                    read_deadline=effective_deadline,
                )
            except LLMClientError as exc:
                self.breaker.record_failure()
                last_error = exc

                # 不可重试错误：立即抛出。
                if not exc.retryable:
                    raise

                # 已是最后一次尝试：抛出最后错误（回退由上层处理）。
                if attempt >= max_attempts:
                    raise

                # 退避，但不得跨过有效 deadline；跨过则停止重试。
                backoff = self._backoff_seconds(attempt)
                if (self._clock() + backoff) >= effective_deadline:
                    if exc.code == ERROR_ATTEMPT_TIMEOUT:
                        raise
                    raise LLMTotalTimeout()
                if backoff > 0:
                    self._sleep(backoff)
                continue
            else:
                self.breaker.record_success()
                return result

        # 循环结构保证不会走到这里；防御性抛出最后错误。
        if last_error is not None:  # pragma: no cover - 防御性
            raise last_error
        raise LLMClientError(ERROR_HTTP_ERROR, "provider 调用未产生结果")

    def _single_attempt(
        self,
        messages: list[dict[str, str]],
        *,
        schema: str,
        attempts: int,
        read_deadline: float | None,
    ) -> LLMRawResult:
        """执行单次请求装配 + 响应读取，返回带真实 ``attempts`` 的结果。

        不做重试；错误按状态码/异常类型归一化为分类错误码。
        """

        url = self._endpoint_url()
        headers = self._headers()
        params = self._params()
        body = self._body(messages)

        # 请求摘要哈希只覆盖非敏感的 body，不覆盖 headers/params（含凭据）。
        request_sha256 = _sha256_hex(
            json.dumps(body, ensure_ascii=False, sort_keys=True)
        )
        provider_host = (urlsplit(url).hostname or "").lower()

        started = time.monotonic()
        try:
            resp = self._transport(
                url,
                headers=headers,
                params=params,
                json=body,
                timeout=float(self.settings.timeout_seconds),
                stream=True,
            )
        except LLMClientError:
            raise
        except Exception as exc:  # noqa: BLE001 - 归一化为 http 错误，不泄露内部细节
            # 只保留异常类型名，不放异常消息（可能含 URL/凭据/正文片段）。
            raise LLMClientError(
                ERROR_HTTP_ERROR,
                f"provider 请求失败: {type(exc).__name__}",
            ) from None

        self._raise_for_status(resp)

        content, transport = self._read_response(resp, deadline=read_deadline)
        if not content:
            raise LLMEmptyResponse()

        elapsed_ms = int((time.monotonic() - started) * 1000)
        metadata = LLMCallMetadata(
            provider_host=provider_host,
            model=self.settings.model,
            schema_version=schema,
            attempts=attempts,  # 真实尝试次数（1-based）
            elapsed_ms=elapsed_ms,
            transport=transport,
            status="success",
            request_sha256=request_sha256,
            response_sha256=_sha256_hex(content),
        )
        return LLMRawResult(content=content, metadata=metadata)

    @staticmethod
    def _raise_for_status(resp: HttpResponse) -> None:
        status = getattr(resp, "status_code", None)
        # 先按状态码分类（无需依赖底层 raise_for_status 的异常）。
        if isinstance(status, int):
            if status == 429:
                raise LLMRateLimited(f"provider 返回 HTTP status={status}")
            if status in (401, 403):
                raise LLMAuthFailed(f"provider 返回 HTTP status={status}")
            if status >= 500:
                # 暂时性服务端错误：可重试。
                raise LLMClientError(
                    ERROR_HTTP_ERROR, f"provider 返回 HTTP 错误 status={status}"
                )
            if status >= 400:
                # 其它 4xx（非鉴权）通常是请求问题：不可重试。
                raise LLMClientError(
                    ERROR_HTTP_ERROR,
                    f"provider 返回 HTTP 错误 status={status}",
                    retryable=False,
                )
        # 状态码不可判定时，回落到底层 raise_for_status 归一化。
        try:
            resp.raise_for_status()
        except LLMClientError:
            raise
        except Exception:  # noqa: BLE001
            # 只保留状态码，不放响应正文。
            raise LLMClientError(
                ERROR_HTTP_ERROR,
                f"provider 返回 HTTP 错误 status={status}",
            ) from None

    def _read_response(
        self,
        resp: HttpResponse,
        *,
        deadline: float | None,
    ) -> tuple[str, str]:
        """读取响应内容，返回 ``(content, transport)``。

        兼容 SSE 逐行与非流式整体 JSON 两种形态，并施加单行/累计上限。
        """

        return read_openai_compatible_stream(
            resp,
            max_response_bytes=self.settings.max_response_bytes,
            deadline=deadline,
        )


def _extract_content_piece(obj: Any) -> str | None:
    """从一个解析后的 JSON 对象提取 content 片段。

    只取 ``choices[0].delta.content``（SSE）或 ``choices[0].message.content``
    （非流式）。``reasoning_content``、``role`` 等非 content 字段一律忽略。
    """

    if not isinstance(obj, dict):
        return None
    choices = obj.get("choices") or []
    if not choices:
        return None
    ch = choices[0]
    if not isinstance(ch, dict):
        return None
    delta = ch.get("delta") if isinstance(ch.get("delta"), dict) else {}
    message = ch.get("message") if isinstance(ch.get("message"), dict) else {}
    piece = delta.get("content") or message.get("content")
    if isinstance(piece, str) and piece:
        return piece
    return None


def read_openai_compatible_stream(
    resp: HttpResponse,
    *,
    max_response_bytes: int,
    deadline: float | None = None,
) -> tuple[str, str]:
    """累积 OpenAI 兼容响应内容并施加字节上限。

    兼容：
    - SSE：逐行 ``data: {json}``，取 ``choices[0].delta.content`` 累积，遇
      ``[DONE]`` 结束；空行忽略。
    - 非流式：整块 ``choices[0].message.content``（无 ``data:`` 前缀的 JSON）。

    上限：任一单行超过 ``max_response_bytes`` 或累计 content 字节数超过上限都
    抛 :class:`LLMResponseTooLarge`。

    ``deadline``：可选墙钟绝对时间（``time.time()`` 基准）；每读取一行检查一次，
    超过即抛 :class:`LLMClientError`（``llm_attempt_timeout``）。总墙钟熔断/重试
    的完整语义属任务 1.4，这里只做读取级别的单次检查。

    非法 JSON 行被跳过（与 CertAgent 当前兼容策略一致），不放入异常消息。
    返回 ``(content, transport)``；``transport`` 为 ``sse`` 或 ``json``。
    """

    parts: list[str] = []
    total_bytes = 0
    saw_data_prefix = False

    for raw_line in resp.iter_lines(decode_unicode=True):
        if deadline is not None and time.time() > deadline:
            # 读取级别墙钟检查；不放响应正文。
            raise LLMClientError(
                ERROR_ATTEMPT_TIMEOUT,
                "读取 provider 响应超过 deadline",
            )

        if raw_line is None:
            continue
        line = raw_line if isinstance(raw_line, str) else raw_line.decode("utf-8", "replace")

        # 单行字节上限（原始行，防止巨大单行撑爆内存）。
        line_bytes = len(line.encode("utf-8"))
        if line_bytes > max_response_bytes:
            raise LLMResponseTooLarge(
                f"单行响应超过上限: {line_bytes} > {max_response_bytes}"
            )

        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("data:"):
            saw_data_prefix = True
            data = stripped[len("data:"):].strip()
        else:
            data = stripped

        if data == "[DONE]":
            break

        try:
            obj = json.loads(data)
        except Exception:  # noqa: BLE001 - 非法 JSON 行跳过，不放入异常消息
            continue

        piece = _extract_content_piece(obj)
        if piece:
            total_bytes += len(piece.encode("utf-8"))
            if total_bytes > max_response_bytes:
                raise LLMResponseTooLarge(
                    f"累计响应超过上限: {total_bytes} > {max_response_bytes}"
                )
            parts.append(piece)

    transport = TRANSPORT_SSE if saw_data_prefix else TRANSPORT_JSON
    return "".join(parts), transport
