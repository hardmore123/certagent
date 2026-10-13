"""创建任务场景的 ``llm_mode`` 校验入口（任务 1.6）。

任务 0.2 已在 :mod:`report_verify.llm.policy` 实现 :func:`authorize_job_mode`
（服务器 allowlist 校验 + override 字段硬拒绝）。本模块**不重复实现** allowlist
逻辑，而是把它整理成“创建任务”场景可直接调用的可复用入口：

- 从 :class:`report_verify.llm.config.LLMSettings`（任务 1.1）或已构造的
  :class:`report_verify.llm.policy.ServerLLMPolicy`（任务 0.2）派生策略视图，
  保证 allowlist / override 规则与 0.2、1.1 完全一致；
- 解析创建任务请求里的 ``llm_mode`` 与可选 override 字段；
- 委托 :func:`authorize_job_mode` 得到最终生效 mode，或抛出带分类错误码
  （``llm_task_mode_not_allowed``）的 :class:`PolicyError`。

安全契约：

- ``allow_job_override=true`` 只允许**选择** allowlist 中的 mode，绝不允许
  覆盖 provider / model / Base URL / api_key / user_key / host / TLS / 原文 /
  图片策略；任何此类 override 字段都被硬拒绝。
- 本模块只读非敏感策略元数据，绝不读取、复制、打印或持久化真实密钥。
- 本模块**不**接入 FastAPI 路由（那属于 Phase 3 的任务 3.3），只提供可复用的
  纯函数校验入口与数据结构。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .config import LLMSettings
from .policy import (
    ERROR_TASK_MODE_NOT_ALLOWED,
    LLMMode,
    PolicyError,
    ServerLLMPolicy,
    authorize_job_mode,
)

# 创建任务请求体中承载“选择 mode”的规范字段名。
JOB_MODE_REQUEST_KEY = "llm_mode"

# 请求体中属于策略/凭据配置、绝不允许任务级覆盖的键。这些键若出现在请求里，
# 必须交给 :func:`authorize_job_mode` 硬拒绝（它使用 policy.FORBIDDEN_JOB_OVERRIDE_KEYS
# 做归一化匹配，能识别全角/兼容字符伪装）。这里不再单独维护 allowlist，避免重复。
_RESERVED_REQUEST_KEYS: frozenset[str] = frozenset({JOB_MODE_REQUEST_KEY})


def policy_from_settings(settings: LLMSettings) -> ServerLLMPolicy:
    """从运行时 :class:`LLMSettings` 派生服务器策略视图。

    只复制非敏感的 mode / allowlist / override / 脱敏策略字段，绝不复制
    ``api_key`` / ``user_key`` / ``base_url`` 等凭据或 endpoint 值。派生结果的
    allowlist 与 override 语义与任务 0.2 的 :class:`ServerLLMPolicy` 一致。
    """

    return ServerLLMPolicy(
        mode=settings.mode,
        allow_original_text=settings.allow_original_text,
        allowed_hosts=settings.allowed_hosts,
        allow_plaintext=settings.allow_plaintext,
        allow_job_override=settings.allow_job_override,
        allowed_job_modes=settings.allowed_job_modes,
        redaction_profile=settings.redaction_profile,
        policy_version=settings.policy_version,
        # allow_images 固定 False，由 ServerLLMPolicy.__post_init__ 再次强制。
    )


def _coerce_policy(policy_or_settings: ServerLLMPolicy | LLMSettings) -> ServerLLMPolicy:
    if isinstance(policy_or_settings, ServerLLMPolicy):
        return policy_or_settings
    if isinstance(policy_or_settings, LLMSettings):
        return policy_from_settings(policy_or_settings)
    raise TypeError(
        "需要 ServerLLMPolicy 或 LLMSettings，收到: "
        f"{type(policy_or_settings).__name__}"
    )


@dataclass(frozen=True)
class JobModeDecision:
    """创建任务的 ``llm_mode`` 校验结果。

    只承载非敏感信息：最终生效 mode、是否由请求显式选择、以及服务器默认 mode。
    """

    mode: LLMMode
    requested: bool          # 请求是否显式提供了 llm_mode
    server_default: LLMMode  # 服务器配置的默认 mode（未显式选择时的回退值）


def _extract_override_fields(
    request: Mapping[str, Any],
) -> dict[str, Any]:
    """从请求体中提取“非 llm_mode”的字段，作为潜在的越权 override 交给校验。

    我们把除 ``llm_mode`` 之外的所有键都视为潜在 override，交给
    :func:`authorize_job_mode` 判定——它只会对真正的策略/凭据键
    （FORBIDDEN_JOB_OVERRIDE_KEYS）硬拒绝，普通业务键（如 cert/draft 文件引用）
    不在该集合内，因此不会被误拒。
    """

    return {
        str(key): value
        for key, value in request.items()
        if str(key) not in _RESERVED_REQUEST_KEYS
    }


def authorize_job_creation(
    policy_or_settings: ServerLLMPolicy | LLMSettings,
    request: Mapping[str, Any] | None,
) -> JobModeDecision:
    """校验创建任务请求的 ``llm_mode`` 并返回最终生效 mode。

    行为：

    - ``request`` 为 ``None`` 或不含 ``llm_mode`` 时，回退到服务器默认 mode；
    - ``llm_mode`` 只能取 ``off/candidate/explain/candidate_explain`` 且必须在
      服务器 allowlist 中；未知或未允许的 mode 抛出 ``llm_task_mode_not_allowed``；
    - ``allow_job_override=false`` 时只允许与服务器默认相同的 mode；
    - 请求中出现任何试图覆盖 provider / model / key / host / TLS / 原文 / 图片
      策略的字段，都会被硬拒绝（``llm_task_mode_not_allowed``）。

    该函数只做纯策略判定，不发起任何网络请求，也不读取凭据值。
    """

    policy = _coerce_policy(policy_or_settings)

    if request is None:
        request = {}

    requested_raw = request.get(JOB_MODE_REQUEST_KEY, None)
    requested = requested_raw is not None
    override_fields = _extract_override_fields(request)

    effective = authorize_job_mode(
        policy,
        requested_raw,
        override_fields=override_fields or None,
    )

    return JobModeDecision(
        mode=effective,
        requested=requested,
        server_default=policy.mode,
    )


def resolve_job_mode(
    policy_or_settings: ServerLLMPolicy | LLMSettings,
    requested_mode: str | None,
    *,
    override_fields: Mapping[str, Any] | None = None,
) -> LLMMode:
    """轻量入口：直接传入已解析的 ``requested_mode`` 与可选 override 字段。

    适用于调用方已经从请求中拆出 mode 的场景（例如未来的 FastAPI 路由层）。
    语义与 :func:`authorize_job_creation` 完全一致，只是不做请求体解析。
    """

    policy = _coerce_policy(policy_or_settings)
    return authorize_job_mode(
        policy,
        requested_mode,
        override_fields=override_fields,
    )


__all__ = [
    "JOB_MODE_REQUEST_KEY",
    "JobModeDecision",
    "authorize_job_creation",
    "policy_from_settings",
    "resolve_job_mode",
    # 便于调用方在需要时直接引用分类错误码。
    "ERROR_TASK_MODE_NOT_ALLOWED",
    "PolicyError",
]
