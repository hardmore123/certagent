"""ReportVerify 的 LLM 运行时配置对象（任务 1.1）。

本模块把 design.md 的 ``report_verify.llm.config`` 与 Low-Level Design 环境
变量表固化为不可变的 :class:`LLMSettings`。它只负责从受控环境变量读取配置并
产出**非敏感**诊断信息，绝不发起 provider 网络请求（那属于任务 1.3）。

安全契约（与 design.md 一致）：

- 默认 ``mode="off"``；未启用时不需要凭据。
- ``allow_images`` 是固定安全常量 ``False``，任何入参/环境变量都无法开启。
- ``allow_original_text`` 默认 ``True``（已确认的服务器策略；只能由服务器关闭，
  不能由任务请求开启）。
- ``allow_job_override`` 默认 ``True``（仅允许任务选择服务器 allowlist 中的 mode）。
- ``api_key`` / ``user_key`` 只驻留在内存中的 settings 对象，绝不进入
  :meth:`LLMSettings.diagnostics`、``repr``、序列化、日志或异常消息。
- CertAgent → ReportVerify 的变量映射沿用任务 0.1 的名称语义：
  ``LLM_BASE_URL/LLM_MODEL/LLM_API_KEY/LLM_USER_KEY`` →
  ``REPORT_VERIFY_LLM_*``。本模块只读取 ``REPORT_VERIFY_LLM_*`` 目标名。

本任务不实现运行时 HTTP client、SSE/JSON 解析或 orchestrator。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from types import MappingProxyType
from typing import Any, Literal, Mapping

# 与 design.md / policy.py 一致的四种能力 mode，默认 ``off``。
LLMMode = Literal["off", "candidate", "explain", "candidate_explain"]

ALL_MODES: tuple[LLMMode, ...] = ("off", "candidate", "explain", "candidate_explain")

# 沿用任务 0.1 的 CertAgent → ReportVerify 变量名映射（只映射名称，不复制值）。
CERTAGENT_TO_REPORT_VERIFY_ENV: Mapping[str, str] = MappingProxyType({
    "LLM_BASE_URL": "REPORT_VERIFY_LLM_BASE_URL",
    "LLM_MODEL": "REPORT_VERIFY_LLM_MODEL",
    "LLM_API_KEY": "REPORT_VERIFY_LLM_API_KEY",
    "LLM_USER_KEY": "REPORT_VERIFY_LLM_USER_KEY",
})

# 只有在 mode 非 off 时才必须存在的运行时目标变量名。
REQUIRED_WHEN_ENABLED: tuple[str, ...] = (
    "REPORT_VERIFY_LLM_BASE_URL",
    "REPORT_VERIFY_LLM_MODEL",
    "REPORT_VERIFY_LLM_API_KEY",
)

# settings 中被视为凭据、绝不外泄的字段名。
_SECRET_FIELD_NAMES: frozenset[str] = frozenset({"api_key", "user_key"})

# 诊断/序列化时应显示为掩码占位而不是真实值的键名。
_REDACTED_PLACEHOLDER = "***redacted***"

# 配置状态码。
STATUS_DISABLED = "disabled"          # mode=off
STATUS_READY = "ready"                # mode!=off 且凭据/endpoint 齐备
STATUS_MISCONFIGURED = "misconfigured"  # mode!=off 但缺 Base URL/model/key 等


class LLMConfigurationError(Exception):
    """配置值无法解析。消息中不包含任何凭据值。"""


def _as_bool(value: Any, default: bool) -> bool:
    """把环境风格字符串/布尔安全转换为 bool，不接受歧义值。"""

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
    raise LLMConfigurationError(f"无法解析布尔配置值: {value!r}")


def _as_int(value: Any, default: int, *, name: str, minimum: int = 1) -> int:
    """把环境值转换为正整数上限，缺省时回退默认值。"""

    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        raise LLMConfigurationError(f"配置 {name} 需要整数") from None
    if parsed < minimum:
        raise LLMConfigurationError(f"配置 {name} 必须 >= {minimum}")
    return parsed


def _parse_modes(value: Any, *, default: tuple[LLMMode, ...]) -> frozenset[LLMMode]:
    if value is None or (isinstance(value, str) and not value.strip()):
        raw = list(default)
    elif isinstance(value, (list, tuple, set, frozenset)):
        raw = [str(v).strip().lower() for v in value]
    elif isinstance(value, str):
        raw = [item.strip().lower() for item in value.split(",")]
    else:
        raise LLMConfigurationError(f"无法解析 mode allowlist: {value!r}")

    modes: set[LLMMode] = set()
    for item in raw:
        if not item:
            continue
        if item not in ALL_MODES:
            raise LLMConfigurationError(f"未知 mode 出现在 allowlist: {item!r}")
        modes.add(item)  # type: ignore[arg-type]
    modes.add("off")  # off 永远隐式允许。
    return frozenset(modes)


def _parse_hosts(value: Any) -> frozenset[str]:
    if value is None:
        return frozenset()
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [str(v).strip().lower() for v in value]
    elif isinstance(value, str):
        items = [item.strip().lower() for item in value.split(",")]
    else:
        raise LLMConfigurationError(f"无法解析 host allowlist: {value!r}")
    return frozenset(item for item in items if item)


@dataclass(frozen=True)
class LLMSettings:
    """不可变 LLM 运行配置。

    只承载启用能力所需的最小配置。``api_key`` / ``user_key`` 只用于内存中的
    provider client（后续任务），绝不进入 :meth:`diagnostics`、``repr`` 或任何
    序列化输出。
    """

    mode: LLMMode = "off"
    base_url: str = ""
    model: str = ""
    api_key: str = ""    # 与 CertAgent 同一受控 secret；绝不序列化/记录
    user_key: str = ""   # 可选 gateway 凭据；绝不序列化/记录
    timeout_seconds: int = 60
    max_retry: int = 2
    total_timeout_seconds: int = 120
    circuit_failure_threshold: int = 3
    circuit_cooldown_seconds: int = 60
    max_response_bytes: int = 1_048_576
    # 单次响应 token 上限的安全阀。0（默认/未设置）= 不限制（不写入请求体，保持
    # 现有行为）；正整数 = 作为请求体 ``max_tokens`` 传给推理模型网关，兜底防止
    # 个别响应生成过长导致耗时/超时。实测网关接受该参数（返回 200）。
    max_tokens: int = 0
    # 差异解释单批行数。默认小于服务器策略 max_rows（200），因为真实网关下单批
    # 200 行（含 CERT/DRAFT 原文）的生成耗时会超出总墙钟预算并触发
    # ``llm_attempt_timeout``。策略 max_rows 仍是硬上限，本配置只能把批调小。
    explain_batch_rows: int = 50
    # 单次 explain 调用最多解释多少条差异。真实文档可能有近千条差异，全部解释会
    # 让 LLM 阶段耗时到分钟级且价值递减；默认只解释前 500 条（保持 diffs 原序），
    # 其余差异仍完整保留确定性证据，UI 依据 metadata 说明“仅解释前 N 条”。
    explain_max_diffs: int = 500
    # explain 批次并发度。provider 调用是阻塞 IO，用线程池并发各批可把墙钟耗时
    # 从批数×单批耗时压到约 ceil(批数/并发)×单批耗时。1 表示串行（便于回退）。
    explain_max_workers: int = 4
    allow_original_text: bool = True          # 服务器策略；默认已确认为 true
    allow_plaintext: bool = False             # 遵从 CertAgent TLS 策略，默认禁明文
    allow_job_override: bool = True           # 允许任务选择 allowlist 中的 mode
    allowed_job_modes: frozenset[LLMMode] = field(
        default_factory=lambda: frozenset(ALL_MODES)
    )
    allowed_hosts: frozenset[str] = field(default_factory=frozenset)
    redaction_profile: str = "standard"
    response_schema_version: str = "reportverify-llm-v1"
    policy_version: str = "policy-v1"
    # 固定安全常量：图片能力永远关闭，构造函数强制它。
    allow_images: Literal[False] = False
    # 环境中的 true/歧义图片配置不能被静默归一后继续启用 provider；该标志
    # 只记录策略是否通过，不保存原始配置值。
    image_policy_valid: bool = True

    def __post_init__(self) -> None:
        # 归一化 mode。
        normalized_mode = str(self.mode).strip().lower()
        if normalized_mode not in ALL_MODES:
            raise LLMConfigurationError(f"未知 mode: {self.mode!r}")
        object.__setattr__(self, "mode", normalized_mode)

        # 固定图片策略：任何试图开启的路径都必须记录为无效并强制回 False。
        if self.allow_images is not False:
            object.__setattr__(self, "allow_images", False)
            object.__setattr__(self, "image_policy_valid", False)

        # 上限必须为正整数。
        for name in (
            "timeout_seconds",
            "max_retry",
            "total_timeout_seconds",
            "circuit_failure_threshold",
            "circuit_cooldown_seconds",
            "max_response_bytes",
            "explain_batch_rows",
            "explain_max_diffs",
            "explain_max_workers",
            "max_tokens",
        ):
            minimum = 0 if name in {"max_retry", "max_tokens"} else 1
            if getattr(self, name) < minimum:
                raise LLMConfigurationError(f"配置 {name} 必须 >= {minimum}")

    # ---- 构造 ---------------------------------------------------------------

    @classmethod
    def from_env(cls, environment: Mapping[str, str] | None = None) -> "LLMSettings":
        """从受控环境变量构造运行配置。

        只读取 ``REPORT_VERIFY_LLM_*`` 目标变量名；不读取 CertAgent 源名，也不
        复制凭据到仓库/文档。缺配置不在此抛错，而是让 :meth:`status` 标记为
        ``misconfigured``，以便任务仍能回退到确定性流程。
        """

        env = os.environ if environment is None else environment

        def get(name: str) -> str:
            value = env.get(name)
            return "" if value is None else str(value)

        raw_image_policy = env.get("REPORT_VERIFY_LLM_ALLOW_IMAGES")
        image_policy_valid = True
        if raw_image_policy is not None:
            # Keep allow_images fixed False, but do not silently treat an
            # attempted true override as a valid enabled configuration.
            image_policy_valid = not _as_bool(raw_image_policy, False)

        return cls(
            mode=get("REPORT_VERIFY_LLM_MODE") or "off",  # type: ignore[arg-type]
            base_url=get("REPORT_VERIFY_LLM_BASE_URL"),
            model=get("REPORT_VERIFY_LLM_MODEL"),
            api_key=get("REPORT_VERIFY_LLM_API_KEY"),
            user_key=get("REPORT_VERIFY_LLM_USER_KEY"),
            timeout_seconds=_as_int(
                env.get("REPORT_VERIFY_LLM_TIMEOUT"), 60,
                name="REPORT_VERIFY_LLM_TIMEOUT",
            ),
            max_retry=_as_int(
                env.get("REPORT_VERIFY_LLM_MAX_RETRY"), 2,
                name="REPORT_VERIFY_LLM_MAX_RETRY", minimum=0,
            ),
            total_timeout_seconds=_as_int(
                env.get("REPORT_VERIFY_LLM_TOTAL_TIMEOUT"), 120,
                name="REPORT_VERIFY_LLM_TOTAL_TIMEOUT",
            ),
            circuit_failure_threshold=_as_int(
                env.get("REPORT_VERIFY_LLM_CIRCUIT_FAILURE_THRESHOLD"), 3,
                name="REPORT_VERIFY_LLM_CIRCUIT_FAILURE_THRESHOLD",
            ),
            circuit_cooldown_seconds=_as_int(
                env.get("REPORT_VERIFY_LLM_CIRCUIT_COOLDOWN"), 60,
                name="REPORT_VERIFY_LLM_CIRCUIT_COOLDOWN",
            ),
            max_response_bytes=_as_int(
                env.get("REPORT_VERIFY_LLM_MAX_RESPONSE_BYTES"), 1_048_576,
                name="REPORT_VERIFY_LLM_MAX_RESPONSE_BYTES",
            ),
            max_tokens=_as_int(
                env.get("REPORT_VERIFY_LLM_MAX_TOKENS"), 0,
                name="REPORT_VERIFY_LLM_MAX_TOKENS", minimum=0,
            ),
            explain_batch_rows=_as_int(
                env.get("REPORT_VERIFY_LLM_EXPLAIN_BATCH_ROWS"), 50,
                name="REPORT_VERIFY_LLM_EXPLAIN_BATCH_ROWS",
            ),
            explain_max_diffs=_as_int(
                env.get("REPORT_VERIFY_LLM_EXPLAIN_MAX_DIFFS"), 500,
                name="REPORT_VERIFY_LLM_EXPLAIN_MAX_DIFFS",
            ),
            explain_max_workers=_as_int(
                env.get("REPORT_VERIFY_LLM_EXPLAIN_MAX_WORKERS"), 4,
                name="REPORT_VERIFY_LLM_EXPLAIN_MAX_WORKERS",
            ),
            allow_original_text=_as_bool(
                env.get("REPORT_VERIFY_LLM_ALLOW_ORIGINAL_TEXT"), True,
            ),
            allow_plaintext=_as_bool(
                env.get("REPORT_VERIFY_LLM_ALLOW_PLAINTEXT"), False,
            ),
            allow_job_override=_as_bool(
                env.get("REPORT_VERIFY_LLM_ALLOW_JOB_OVERRIDE"), True,
            ),
            allowed_job_modes=_parse_modes(
                env.get("REPORT_VERIFY_LLM_ALLOWED_MODES"), default=ALL_MODES,
            ),
            allowed_hosts=_parse_hosts(env.get("REPORT_VERIFY_LLM_ALLOWED_HOSTS")),
            redaction_profile=(
                env.get("REPORT_VERIFY_LLM_REDACTION_PROFILE") or "standard"
            ),
            response_schema_version=(
                env.get("REPORT_VERIFY_LLM_RESPONSE_SCHEMA")
                or "reportverify-llm-v1"
            ),
            image_policy_valid=image_policy_valid,
            # allow_images 永远忽略环境，固定 False（__post_init__ 再次强制）。
        )

    # ---- 状态判定 -----------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """mode 非 off 时视为启用（仍需 :meth:`status` 判断是否可用）。"""

        return self.mode != "off"

    @property
    def has_credentials(self) -> bool:
        """启用所需的 Base URL / model / key 是否齐备。"""

        return bool(self.base_url and self.model and self.api_key)

    def missing_required(self) -> tuple[str, ...]:
        """返回启用时仍缺失的目标变量名（用于诊断，不含值）。"""

        missing: list[str] = []
        if not self.base_url:
            missing.append("REPORT_VERIFY_LLM_BASE_URL")
        if not self.model:
            missing.append("REPORT_VERIFY_LLM_MODEL")
        if not self.api_key:
            missing.append("REPORT_VERIFY_LLM_API_KEY")
        return tuple(missing)

    def status(self) -> str:
        """返回配置状态：disabled / ready / misconfigured。"""

        if not self.enabled:
            return STATUS_DISABLED
        if not self.image_policy_valid:
            return STATUS_MISCONFIGURED
        if self.missing_required():
            return STATUS_MISCONFIGURED
        return STATUS_READY

    # ---- 诊断（脱敏） -------------------------------------------------------

    def diagnostics(self) -> dict[str, Any]:
        """返回非敏感的 mode/limits/host/schema 等元数据。

        绝不包含 ``api_key`` / ``user_key`` 的值。启用但缺凭据时状态为
        ``misconfigured``，并列出缺失的目标变量名（仅名称）。
        """

        return {
            "mode": self.mode,
            "status": self.status(),
            "enabled": self.enabled,
            "base_url_configured": bool(self.base_url),
            "model_configured": bool(self.model),
            "api_key_present": bool(self.api_key),
            "user_key_present": bool(self.user_key),
            "missing_required": list(self.missing_required()),
            "timeout_seconds": self.timeout_seconds,
            "max_retry": self.max_retry,
            "total_timeout_seconds": self.total_timeout_seconds,
            "circuit_failure_threshold": self.circuit_failure_threshold,
            "circuit_cooldown_seconds": self.circuit_cooldown_seconds,
            "max_response_bytes": self.max_response_bytes,
            "max_tokens": self.max_tokens,
            "explain_batch_rows": self.explain_batch_rows,
            "explain_max_diffs": self.explain_max_diffs,
            "explain_max_workers": self.explain_max_workers,
            "allow_original_text": self.allow_original_text,
            "allow_images": self.allow_images,  # 固定 False
            "image_policy_valid": self.image_policy_valid,
            "allow_plaintext": self.allow_plaintext,
            "allow_job_override": self.allow_job_override,
            "allowed_job_modes": sorted(self.allowed_job_modes),
            "allowed_hosts": sorted(self.allowed_hosts),
            "redaction_profile": self.redaction_profile,
            "response_schema_version": self.response_schema_version,
            "policy_version": self.policy_version,
            # 显式脱敏契约，便于审计而不暴露任何值或可逆表示。
            "secret_values_in_diagnostics": False,
        }

    # ---- 表示与序列化（脱敏） ----------------------------------------------

    def __repr__(self) -> str:  # noqa: D401 - 简单脱敏 repr
        """脱敏 repr：凭据字段显示为掩码占位，绝不暴露真实值。"""

        parts: list[str] = []
        for f in fields(self):
            if f.name in _SECRET_FIELD_NAMES:
                present = bool(getattr(self, f.name))
                parts.append(f"{f.name}={_REDACTED_PLACEHOLDER if present else ''!r}")
            else:
                parts.append(f"{f.name}={getattr(self, f.name)!r}")
        return f"LLMSettings({', '.join(parts)})"

    __str__ = __repr__
