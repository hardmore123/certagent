"""ReportVerify 的服务器端 LLM policy gate（任务 0.2）。

本模块只做**服务器策略校验**，不发起任何 provider 网络请求，也不读取、
复制、打印或持久化真实 API key / user key。它把 design.md 中确认的服务器
策略固化为可测试的判定：

- ``REPORT_VERIFY_LLM_ALLOW_ORIGINAL_TEXT=true`` 时，仅允许 capability 字段
  白名单内的 CERT/DRAFT 字段原文进入 payload，并继续受字段/字符/行数上限和
  脱敏 profile 约束；为 false 时拒绝需要原文的 capability。
- ``allow_images`` 固定为 ``False``。任何环境变量、任务参数或 payload 的图片
  外发意图都在组装 payload / 发起 provider 请求之前硬拒绝，返回
  ``llm_image_externalization_rejected``，且不触发任何网络调用。
- provider host allowlist、TLS/非 TLS 策略和任务 ``llm_mode`` allowlist 只能由
  服务器配置决定；任务级请求不能覆盖 provider、model、Base URL、endpoint、
  凭据、host/TLS 或外发策略。

该模块只负责 gate 逻辑；真正的运行时 client、schema 校验和 orchestrator 是
后续任务（1.1 之后）的范围，本任务不实现它们。
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal, Mapping
from urllib.parse import urlsplit

# 与 design.md 一致的四种能力 mode。默认服务器保持 ``off``。
LLMMode = Literal["off", "candidate", "explain", "candidate_explain"]

ALL_MODES: tuple[LLMMode, ...] = ("off", "candidate", "explain", "candidate_explain")

# 每种 capability 允许离开本机的 CERT/DRAFT 字段原文白名单，以及最小结构化
# 上下文字段。原文字段只有在 ``allow_original_text=True`` 时才被允许发送。
_CERT_DRAFT_TEXT_FIELDS: frozenset[str] = frozenset({"cert_value", "draft_value"})
_STRUCTURAL_CONTEXT_FIELDS: frozenset[str] = frozenset({
    "block_type",
    "table_idx",
    "group",
    "item_name",
    "model",
    "field",
    "diff_type",
    "diff_key",
    "cert_index",
    "draft_index",
})

# capability -> 允许出现在 payload 行中的字段（含原文字段）。
CAPABILITY_FIELD_WHITELIST: Mapping[str, frozenset[str]] = MappingProxyType({
    "candidate": _STRUCTURAL_CONTEXT_FIELDS | _CERT_DRAFT_TEXT_FIELDS,
    "explain": _STRUCTURAL_CONTEXT_FIELDS | _CERT_DRAFT_TEXT_FIELDS,
    "discipline": _STRUCTURAL_CONTEXT_FIELDS,  # 专业候选不需要字段原文
})

# 无论策略如何都必须硬拒绝的字段/键：文件、路径、二进制、图片、嵌入对象、
# 工具调用和外部 URL 访问意图。这些是拒绝信号，不是白名单。
FORBIDDEN_PAYLOAD_KEYS: frozenset[str] = frozenset({
    "file",
    "files",
    "file_path",
    "filepath",
    "path",
    "paths",
    "document",
    "docx",
    "binary",
    "bytes",
    "blob",
    "attachment",
    "attachments",
    "image",
    "images",
    "image_url",
    "image_urls",
    "photo",
    "picture",
    "inline_image",
    "embedded_object",
    "embed",
    "embedding",
    "tool",
    "tools",
    "tool_call",
    "tool_calls",
    "function_call",
    "url",
    "urls",
    "external_url",
    "fetch_url",
    # Raw/body/provider material is not a capability field.  Reject it instead
    # of silently dropping it, so an outbound request cannot hide unauthorized
    # content behind an unrecognized key.
    "body",
    "prompt",
    "response",
    "content",
})

# 明确的图片相关键，命中即返回 image_externalization_rejected（在通用 forbidden
# 之前判定，以给出精确错误码）。
IMAGE_PAYLOAD_KEYS: frozenset[str] = frozenset({
    "image",
    "images",
    "image_url",
    "image_urls",
    "photo",
    "picture",
    "inline_image",
})

# 任务级请求绝不允许出现的、试图覆盖服务器策略的键。
FORBIDDEN_JOB_OVERRIDE_KEYS: frozenset[str] = frozenset({
    "base_url",
    "provider",
    "endpoint",
    "model",
    "api_key",
    "user_key",
    "allow_images",
    "allow_original_text",
    "allowed_hosts",
    "allow_plaintext",
    "redaction_profile",
    "host",
    "tls",
})

# 分类错误码，与 design.md 的 Error Handling 表一致。
ERROR_POLICY_DENIED = "llm_policy_denied"
ERROR_IMAGE_REJECTED = "llm_image_externalization_rejected"
ERROR_TASK_MODE_NOT_ALLOWED = "llm_task_mode_not_allowed"
ERROR_MISCONFIGURED = "llm_misconfigured"


class PolicyError(Exception):
    """策略拒绝。``code`` 为 design.md 中的分类错误码。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class PolicyConfigurationError(PolicyError):
    """服务器策略配置本身无效（misconfigured），任务应回退到确定性流程。"""

    def __init__(self, message: str) -> None:
        super().__init__(ERROR_MISCONFIGURED, message)


def _as_bool(value: Any, default: bool) -> bool:
    """把环境风格的字符串/布尔安全转换为 bool，不接受歧义值。"""

    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "1", "yes", "on"}:
            return True
        if text in {"false", "0", "no", "off", ""}:
            return False
    raise PolicyConfigurationError(f"无法解析布尔策略值: {value!r}")


def _parse_hosts(value: Any) -> frozenset[str]:
    if value is None:
        return frozenset()
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [str(v).strip().lower() for v in value]
    elif isinstance(value, str):
        items = [item.strip().lower() for item in value.split(",")]
    else:
        raise PolicyConfigurationError(f"无法解析 host allowlist: {value!r}")
    return frozenset(item for item in items if item)


def _parse_modes(value: Any, *, default: tuple[LLMMode, ...]) -> frozenset[LLMMode]:
    if value is None:
        raw = list(default)
    elif isinstance(value, (list, tuple, set, frozenset)):
        raw = [str(v).strip().lower() for v in value]
    elif isinstance(value, str):
        raw = [item.strip().lower() for item in value.split(",")]
    else:
        raise PolicyConfigurationError(f"无法解析 mode allowlist: {value!r}")
    modes: set[LLMMode] = set()
    for item in raw:
        if not item:
            continue
        if item not in ALL_MODES:
            raise PolicyConfigurationError(f"未知 mode 出现在服务器 allowlist: {item!r}")
        modes.add(item)  # type: ignore[arg-type]
    # off 永远隐式允许（相当于关闭）。
    modes.add("off")
    return frozenset(modes)


@dataclass(frozen=True)
class ServerLLMPolicy:
    """服务器端不可变策略对象。

    只包含非敏感的策略元数据。构造函数不接受、不存储任何凭据值。
    ``allow_images`` 是固定安全常量，无法通过任何入参设为 True。
    """

    mode: LLMMode = "off"
    allow_original_text: bool = True
    allowed_hosts: frozenset[str] = field(default_factory=frozenset)
    allow_plaintext: bool = False
    allow_job_override: bool = True
    allowed_job_modes: frozenset[LLMMode] = field(
        default_factory=lambda: frozenset(ALL_MODES)
    )
    redaction_profile: str = "standard"
    max_rows: int = 200
    max_chars_per_field: int = 2000
    policy_version: str = "policy-v1"
    # 固定安全常量：图片能力永远关闭，且构造函数会强制它。
    allow_images: Literal[False] = False

    def __post_init__(self) -> None:
        # 固定图片策略：任何试图开启的路径都必须失败。
        if self.allow_images is not False:
            object.__setattr__(self, "allow_images", False)
        if self.max_rows <= 0 or self.max_chars_per_field <= 0:
            raise PolicyConfigurationError("行数/字符上限必须为正整数")

    @classmethod
    def from_config(cls, cfg: Mapping[str, Any] | None) -> "ServerLLMPolicy":
        """从服务器配置映射构造。

        显式忽略任何 ``allow_images`` 覆盖，并拒绝无法解析的布尔值。凭据键
        （api_key/user_key/base_url 等）不在此读取，本对象不承载凭据。
        """

        cfg = dict(cfg or {})
        mode = str(cfg.get("mode", "off")).strip().lower()
        if mode not in ALL_MODES:
            raise PolicyConfigurationError(f"未知服务器 mode: {mode!r}")

        # allow_images 显式忽略配置输入，始终 False。
        if _as_bool(cfg.get("allow_images"), False):
            # 记录为配置错误更安全：明确拒绝任何试图开启图片的服务器配置。
            raise PolicyConfigurationError(
                "allow_images 固定为 false，不接受任何开启配置"
            )

        return cls(
            mode=mode,  # type: ignore[arg-type]
            allow_original_text=_as_bool(cfg.get("allow_original_text"), True),
            allowed_hosts=_parse_hosts(cfg.get("allowed_hosts")),
            allow_plaintext=_as_bool(cfg.get("allow_plaintext"), False),
            allow_job_override=_as_bool(cfg.get("allow_job_override"), True),
            allowed_job_modes=_parse_modes(
                cfg.get("allowed_modes"), default=ALL_MODES
            ),
            redaction_profile=str(cfg.get("redaction_profile", "standard")),
            max_rows=int(cfg.get("max_rows", 200)),
            max_chars_per_field=int(cfg.get("max_chars_per_field", 2000)),
            policy_version=str(cfg.get("policy_version", "policy-v1")),
        )

    def diagnostics(self) -> dict[str, Any]:
        """返回非敏感策略元数据；不含任何凭据或原文。"""

        return {
            "mode": self.mode,
            "allow_original_text": self.allow_original_text,
            "allow_images": self.allow_images,  # 固定 False
            "allow_plaintext": self.allow_plaintext,
            "allow_job_override": self.allow_job_override,
            "allowed_hosts": sorted(self.allowed_hosts),
            "allowed_job_modes": sorted(self.allowed_job_modes),
            "redaction_profile": self.redaction_profile,
            "max_rows": self.max_rows,
            "max_chars_per_field": self.max_chars_per_field,
            "policy_version": self.policy_version,
        }


@dataclass(frozen=True)
class OutboundAuthorization:
    authorized: bool
    capability: str
    reason: str
    document_text_allowed: bool
    images_allowed: Literal[False]
    redaction_profile: str
    error_code: str = ""


@dataclass(frozen=True)
class EndpointAuthorization:
    authorized: bool
    host: str
    reason: str
    error_code: str = ""


def _normalize_key(key: Any) -> str:
    """把键名归一，防止全角/兼容字符伪装绕过 allowlist/forbidden 判定。

    使用 Unicode NFKC 折叠（例如全角 ``ｉｍａｇｅ`` -> ``image``），再去空白并转小写。
    """

    return unicodedata.normalize("NFKC", str(key)).strip().lower()


def _contains_image_intent(obj: Any) -> bool:
    """递归检测 payload/请求对象中的图片外发意图。"""

    if isinstance(obj, Mapping):
        for key, value in obj.items():
            if _normalize_key(key) in IMAGE_PAYLOAD_KEYS:
                return True
            if _contains_image_intent(value):
                return True
        return False
    if isinstance(obj, (list, tuple, set)):
        return any(_contains_image_intent(v) for v in obj)
    return False


def _contains_forbidden_key(obj: Any) -> str:
    """递归检测被禁字段/二进制值；返回命中的分类或空串。"""

    # Binary document material must never be coerced to text and sent.  Check
    # values as well as keys because cert_value/draft_value are otherwise valid
    # whitelist names whose value type still has to remain textual.
    if isinstance(obj, (bytes, bytearray, memoryview)):
        return "binary"
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            name = _normalize_key(key)
            if name in FORBIDDEN_PAYLOAD_KEYS:
                return name
            hit = _contains_forbidden_key(value)
            if hit:
                return hit
        return ""
    if isinstance(obj, (list, tuple, set)):
        for v in obj:
            hit = _contains_forbidden_key(v)
            if hit:
                return hit
    return ""


def check_server_policy(cfg: Mapping[str, Any] | None) -> ServerLLMPolicy:
    """校验服务器策略配置并返回不可变策略对象。

    misconfigured 会抛出 ``PolicyConfigurationError``；调用方应据此保持
    ``mode=off`` 并回退到确定性流程。
    """

    policy = ServerLLMPolicy.from_config(cfg)

    # 若服务器要启用非 off 能力，host allowlist 必须存在，避免误指向未批准
    # endpoint。
    if policy.mode != "off" and not policy.allowed_hosts:
        raise PolicyConfigurationError(
            "启用 LLM 能力时必须配置 provider host allowlist"
        )
    return policy


def authorize_job_mode(
    policy: ServerLLMPolicy,
    requested_mode: str | None,
    *,
    override_fields: Mapping[str, Any] | None = None,
) -> LLMMode:
    """校验任务级 ``llm_mode``。

    - 未提供时使用服务器默认 mode；
    - 只接受服务器 allowlist 中的 mode；
    - 任何试图覆盖 provider/model/key/host/TLS/外发策略的字段都拒绝。
    """

    if override_fields:
        bad = sorted(
            str(k) for k in override_fields
            if _normalize_key(k) in FORBIDDEN_JOB_OVERRIDE_KEYS
        )
        if bad:
            raise PolicyError(
                ERROR_TASK_MODE_NOT_ALLOWED,
                f"任务请求不能覆盖服务器策略字段: {bad}",
            )

    if requested_mode is None:
        # A server default that is not itself allowlisted is an invalid
        # activation configuration.  Without this check, a deployment could
        # set mode=candidate while allowing only off and still enable the
        # provider when a task omitted llm_mode.
        if policy.mode not in policy.allowed_job_modes:
            raise PolicyError(
                ERROR_TASK_MODE_NOT_ALLOWED,
                "服务器默认 llm_mode 不在 allowlist",
            )
        return policy.mode

    normalized = str(requested_mode).strip().lower()
    if normalized not in ALL_MODES:
        raise PolicyError(
            ERROR_TASK_MODE_NOT_ALLOWED,
            f"未知 llm_mode: {requested_mode!r}",
        )
    if not policy.allow_job_override and normalized != policy.mode:
        raise PolicyError(
            ERROR_TASK_MODE_NOT_ALLOWED,
            "服务器未开启任务级 mode 覆盖",
        )
    if normalized not in policy.allowed_job_modes:
        raise PolicyError(
            ERROR_TASK_MODE_NOT_ALLOWED,
            f"llm_mode 不在服务器 allowlist: {normalized!r}",
        )
    return normalized  # type: ignore[return-value]


def authorize_provider_endpoint(
    policy: ServerLLMPolicy,
    base_url: str,
) -> EndpointAuthorization:
    """校验 provider endpoint 的 host allowlist 与 TLS 策略。

    任务级请求无法到达此处提供不同 host —— base_url 来自服务器配置。此函数
    只做纯策略判定，不发起任何网络请求。
    """

    parsed = urlsplit(base_url)
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()

    if not host:
        return EndpointAuthorization(
            authorized=False,
            host=host,
            reason="base_url 缺少 host",
            error_code=ERROR_MISCONFIGURED,
        )

    if scheme not in {"http", "https"}:
        return EndpointAuthorization(
            authorized=False,
            host=host,
            reason=f"不支持的 scheme: {scheme}",
            error_code=ERROR_POLICY_DENIED,
        )

    if scheme != "https" and not policy.allow_plaintext:
        return EndpointAuthorization(
            authorized=False,
            host=host,
            reason="非 TLS endpoint 被策略拒绝",
            error_code=ERROR_POLICY_DENIED,
        )

    if policy.allowed_hosts and host not in policy.allowed_hosts:
        return EndpointAuthorization(
            authorized=False,
            host=host,
            reason="host 不在服务器 allowlist",
            error_code=ERROR_POLICY_DENIED,
        )

    return EndpointAuthorization(authorized=True, host=host, reason="ok")


def authorize_outbound(
    policy: ServerLLMPolicy,
    *,
    capability: str,
    payload_sample: Mapping[str, Any] | None = None,
) -> OutboundAuthorization:
    """判定某能力的外发是否被授权，并对图片/文件等意图硬拒绝。

    ``payload_sample`` 是可选的、用于预检的结构化请求样本（例如任务请求体或
    候选 payload 草稿）。图片意图优先命中，返回精确的 image 错误码。
    """

    if capability not in CAPABILITY_FIELD_WHITELIST:
        return OutboundAuthorization(
            authorized=False,
            capability=capability,
            reason=f"未知 capability: {capability!r}",
            document_text_allowed=False,
            images_allowed=False,
            redaction_profile=policy.redaction_profile,
            error_code=ERROR_POLICY_DENIED,
        )

    # 图片意图：在任何网络请求前硬拒绝（固定 allow_images=False）。
    if payload_sample is not None and _contains_image_intent(payload_sample):
        return OutboundAuthorization(
            authorized=False,
            capability=capability,
            reason="发现图片外发意图；图片策略固定为 false",
            document_text_allowed=False,
            images_allowed=False,
            redaction_profile=policy.redaction_profile,
            error_code=ERROR_IMAGE_REJECTED,
        )

    # 其它被禁内容（文件/路径/二进制/嵌入对象/工具调用/URL）。
    if payload_sample is not None:
        hit = _contains_forbidden_key(payload_sample)
        if hit:
            return OutboundAuthorization(
                authorized=False,
                capability=capability,
                reason=f"payload 含被禁字段: {hit}",
                document_text_allowed=False,
                images_allowed=False,
                redaction_profile=policy.redaction_profile,
                error_code=ERROR_POLICY_DENIED,
            )

    document_text_allowed = policy.allow_original_text

    return OutboundAuthorization(
        authorized=True,
        capability=capability,
        reason="ok",
        document_text_allowed=document_text_allowed,
        images_allowed=False,
        redaction_profile=policy.redaction_profile,
    )


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit]


# ---------------------------------------------------------------------------
# 提示注入隔离（任务 1.2）
# ---------------------------------------------------------------------------
#
# 文档字段中的文本（cert_value/draft_value 等）是**不可信输入**。无论它包含
# 指令、URL、代码围栏还是 "忽略系统要求 / ignore previous instructions" 之类
# 的越权字样，都只能作为**纯数据字符串**进入 payload，绝不能改变系统 prompt、
# endpoint、工具权限、字段结构或服务器策略。
#
# 本模块采取“结构隔离 + 显式包裹”的策略，而不是尝试删除/改写注入文本：
#
# 1. 字段值始终以 str 形式承载在受白名单约束的 key 下（见 build_minimal_payload）。
#    任何 dict/list 结构都不会从字段值“逃逸”成 payload 结构，因为原文字段被强制
#    ``str(value)``，注入文本因此无法引入新的 JSON 键或图片/工具字段。
# 2. ``wrap_untrusted_text`` 把字段值标记为 ``{"type": "untrusted_document_text",
#    "value": <str>}``，供 client 层构造 prompt 时明确区分“数据”与“指令”。
# 3. ``isolate_field_value`` 对任意字段值做纯数据归一：非字符串标量转 str，
#    并按上限截断，保证注入内容不改变结构、长度受控。

# 注入探测标记：仅用于**诊断/审计计数**，不改写文本内容，也不作为放行/拒绝依据。
# 原文一律作为普通数据保留；这里只是让 trace 能记录“检测到疑似注入”的非敏感信号。
_INJECTION_MARKERS: tuple[str, ...] = (
    "ignore previous instructions",
    "ignore all previous",
    "disregard previous",
    "忽略系统要求",
    "忽略以上",
    "忽略上述",
    "忽略之前",
    "you are now",
    "system prompt",
    "```",
    "http://",
    "https://",
)

UNTRUSTED_TEXT_TYPE = "untrusted_document_text"


def looks_like_injection(value: Any) -> bool:
    """启发式判断文本是否**疑似**包含提示注入/越权字样。

    仅用于非敏感诊断计数（trace 可记录检测到的疑似注入数量）；**绝不**据此
    改写、删除或拒绝字段值——字段原文始终作为普通数据保留。
    """

    if not isinstance(value, str):
        return False
    text = value.lower()
    return any(marker in text for marker in _INJECTION_MARKERS)


def isolate_field_value(value: Any, *, max_chars: int) -> str:
    """把任意字段值归一为受长度约束的**纯数据字符串**。

    - 非字符串标量转为 ``str``；
    - 按 ``max_chars`` 截断；
    - 不解释、不执行、不解析其中的指令/URL/代码围栏——它们只是字符。

    这保证注入文本无法改变 payload 结构或长度上限。
    """

    text = "" if value is None else str(value)
    return _truncate(text, max_chars)


def wrap_untrusted_text(value: Any, *, max_chars: int) -> dict[str, Any]:
    """把字段原文包裹为显式的“不可信数据”对象。

    返回结构固定为 ``{"type": UNTRUSTED_TEXT_TYPE, "value": <str>}``；client 层
    据此在 prompt 中明确标注该内容为数据而非指令。value 已经过纯数据归一和截断，
    因此注入文本不会引入额外的键或改变结构。
    """

    return {
        "type": UNTRUSTED_TEXT_TYPE,
        "value": isolate_field_value(value, max_chars=max_chars),
    }


def build_minimal_payload(
    policy: ServerLLMPolicy,
    capability: str,
    rows: list[Mapping[str, Any]],
    *,
    rules_version: str,
) -> dict[str, Any]:
    """把结构化行组装为最小、白名单化、受限的 payload。

    只接受已经解析的结构化值。任何文件路径、二进制、图片、嵌入对象或工具调用
    字段都在这里被拒绝。原文字段只有在 ``allow_original_text=True`` 时才保留，
    并受字符/行数上限约束。文档正文中的指令/URL/代码块一律当作普通值。
    """

    auth = authorize_outbound(policy, capability=capability)
    if not auth.authorized:
        raise PolicyError(auth.error_code or ERROR_POLICY_DENIED, auth.reason)

    whitelist = CAPABILITY_FIELD_WHITELIST[capability]

    if len(rows) > policy.max_rows:
        raise PolicyError(
            ERROR_POLICY_DENIED,
            f"payload 行数超过上限: {len(rows)} > {policy.max_rows}",
        )

    safe_rows: list[dict[str, Any]] = []
    injection_signal_count = 0
    for row in rows:
        # 每行先做图片/被禁字段硬拒绝，即使 caller 传入了非白名单键。
        if _contains_image_intent(row):
            raise PolicyError(
                ERROR_IMAGE_REJECTED,
                "payload 行含图片外发意图；图片策略固定为 false",
            )
        hit = _contains_forbidden_key(row)
        if hit:
            raise PolicyError(
                ERROR_POLICY_DENIED,
                f"payload 行含被禁字段: {hit}",
            )

        safe_row: dict[str, Any] = {}
        for key, value in row.items():
            name = str(key)
            if name not in whitelist:
                # 白名单之外的字段一律丢弃，不外发。
                continue
            if name in _CERT_DRAFT_TEXT_FIELDS:
                if not policy.allow_original_text:
                    # 服务器策略关闭原文时，跳过原文字段。
                    continue
                # 提示注入隔离：原文一律以纯数据字符串承载并截断；即使包含
                # 指令/URL/代码围栏/"忽略系统要求" 也只是普通字符，不改变结构。
                if looks_like_injection(value):
                    injection_signal_count += 1
                safe_row[name] = isolate_field_value(
                    value, max_chars=policy.max_chars_per_field
                )
            else:
                # 非原文字段同样做纯数据归一，避免结构从字段值“逃逸”；
                # 但结构上下文字段（如 table_idx）应保留其标量类型。
                if isinstance(value, (Mapping, list, tuple, set)):
                    # 结构上下文字段不应是嵌套容器；命中即当作非法输入拒绝，
                    # 防止注入内容借嵌套结构携带新键。
                    raise PolicyError(
                        ERROR_POLICY_DENIED,
                        f"字段 {name!r} 不允许嵌套结构值",
                    )
                safe_row[name] = value
        safe_rows.append(safe_row)

    return {
        "capability": capability,
        "rows": safe_rows,
        "metadata": {
            "rules_version": rules_version,
            "policy_version": policy.policy_version,
            "redaction_profile": policy.redaction_profile,
            "allow_original_text": policy.allow_original_text,
            "allow_images": policy.allow_images,  # 固定 False
            "max_rows": policy.max_rows,
            "max_chars_per_field": policy.max_chars_per_field,
            "field_whitelist": sorted(whitelist),
            # 非敏感诊断：疑似注入命中计数，仅用于审计信号，不含原文。
            "injection_signal_count": injection_signal_count,
        },
    }
