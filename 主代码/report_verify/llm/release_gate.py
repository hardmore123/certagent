"""脱敏的 ReportVerify LLM 发布门禁（任务 4.5）。

发布门禁只回答一个问题：当前服务器配置是否满足 *允许 provider 发起调用*
的全部前置条件。它不是健康检查，不访问网络，也不读取任何 API key/user key
的值。凭据映射只通过 :func:`check_credential_injection` 做变量名存在性检查；
运行时真正的 key 仍只由 provider client 在受控进程内使用。

安全默认值：

* ``REPORT_VERIFY_LLM_MODE`` 缺省为 ``off``；off 始终不会允许 provider 调用；
* enabled mode 必须同时通过凭据映射、host/TLS、服务器 mode allowlist、原文
  策略和图片固定拒绝检查；
* 任务级 ``llm_mode`` 与 override 字段使用同一服务器 allowlist/越权校验；
* 诊断只输出 mode、固定错误码和布尔/状态，不输出 URL、secret、prompt、response
  或 CERT/DRAFT 原文。

模块可以作为发布前本地检查执行：

``python -m report_verify.llm.release_gate``

退出码为 0 表示当前配置处于安全关闭状态（mode=off），或一个非 off 配置已经
通过全部 provider 激活门禁；退出码为 1 表示配置不能发布/激活。两种情况下都
不会发起 provider 请求。
"""
from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from report_verify.llm_injection_check import InjectionCheck, check_credential_injection
from .policy import (
    ALL_MODES,
    ERROR_IMAGE_REJECTED,
    ERROR_MISCONFIGURED,
    ERROR_POLICY_DENIED,
    ERROR_TASK_MODE_NOT_ALLOWED,
    PolicyError,
    ServerLLMPolicy,
    authorize_job_mode,
    authorize_provider_endpoint,
)

# 生产关闭开关的唯一安全默认值。该值是非敏感配置元数据，可以出现在诊断中。
DEFAULT_PRODUCTION_MODE = "off"
MODE_ENV_NAME = "REPORT_VERIFY_LLM_MODE"
BASE_URL_ENV_NAME = "REPORT_VERIFY_LLM_BASE_URL"

# 发布门禁使用的 stable 分类码；不携带配置值。
ERROR_MODE_GATE = "llm_release_mode_gate_failed"
ERROR_MAPPING_GATE = "llm_release_credential_mapping_failed"
ERROR_HOST_TLS_GATE = "llm_release_host_tls_gate_failed"
ERROR_MODE_ALLOWLIST_GATE = "llm_release_mode_allowlist_failed"
ERROR_ORIGINAL_TEXT_GATE = "llm_release_original_text_policy_failed"
ERROR_IMAGE_GATE = ERROR_IMAGE_REJECTED
ERROR_TASK_OVERRIDE_GATE = ERROR_TASK_MODE_NOT_ALLOWED
ERROR_POLICY_CONFIG_GATE = ERROR_MISCONFIGURED

_SAFE_CHECK_NAMES = frozenset({
    "production_mode",
    "credential_mapping",
    "host_tls_allowlist",
    "server_mode_allowlist",
    "task_mode_authorization",
    "original_text_policy",
    "image_hard_rejection",
    "policy_configuration",
})

_TRUE_VALUES = frozenset({"true", "1", "yes", "on"})
_FALSE_VALUES = frozenset({"false", "0", "no", "off", ""})


@dataclass(frozen=True)
class ReleaseGateCheck:
    """单项发布门禁结果。

    ``detail`` 只允许固定的非敏感说明；调用方不应把环境值拼接进来。
    ``required_for_provider`` 区分 mode=off 时不需要读取的可选门禁。
    """

    name: str
    passed: bool
    required_for_provider: bool
    code: str = ""
    detail: str = ""

    @property
    def status(self) -> str:
        if self.passed and not self.required_for_provider:
            return "not_required"
        return "passed" if self.passed else "blocked"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "passed": self.passed,
            "required_for_provider": self.required_for_provider,
            "code": self.code,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ReleaseGateResult:
    """完整的脱敏发布门禁结果。"""

    mode: str
    effective_mode: str
    provider_allowed: bool
    checks: tuple[ReleaseGateCheck, ...]

    @property
    def release_safe(self) -> bool:
        """配置是否可发布：off 安全关闭，或所有门禁均通过。"""

        return bool(self.mode in ALL_MODES) and all(check.passed for check in self.checks)

    @property
    def blocked_codes(self) -> tuple[str, ...]:
        return tuple(
            check.code
            for check in self.checks
            if not check.passed and check.code
        )

    def diagnostics(self) -> dict[str, Any]:
        """只返回非敏感状态；明确声明没有读取/持久化 secret 值。"""

        return {
            "mode": self.mode,
            "effective_mode": self.effective_mode,
            "provider_allowed": self.provider_allowed,
            "release_safe": self.release_safe,
            "checks": [check.to_dict() for check in self.checks],
            "blocked_codes": list(self.blocked_codes),
            "network_requests_made": False,
            "secret_values_read": False,
            "secret_values_in_diagnostics": False,
            "secret_values_persisted": False,
        }


def _env_value(environment: Mapping[str, str], name: str, default: str = "") -> str:
    """读取一个明确的非 secret 配置名。

    该 helper 不允许调用方把 key/user-key 名称传入；凭据名称只交给
    ``check_credential_injection`` 做 ``name in environment`` 检查。
    """

    if name in {
        "REPORT_VERIFY_LLM_API_KEY",
        "REPORT_VERIFY_LLM_USER_KEY",
        "LLM_API_KEY",
        "LLM_USER_KEY",
    }:
        raise ValueError("release gate 不读取 secret 值")
    try:
        value = environment.get(name, default)
    except (AttributeError, KeyError, OSError, PermissionError):
        return default
    return default if value is None else str(value)


def _parse_bool(value: str) -> bool | None:
    normalized = value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    return None


def _check(
    name: str,
    passed: bool,
    *,
    required: bool,
    code: str = "",
    detail: str = "",
) -> ReleaseGateCheck:
    if name not in _SAFE_CHECK_NAMES:
        raise ValueError(f"未知发布门禁名称: {name}")
    return ReleaseGateCheck(
        name=name,
        passed=passed,
        required_for_provider=required,
        code=code if not passed else "",
        detail=detail,
    )


def _policy_from_environment(environment: Mapping[str, str], mode: str) -> ServerLLMPolicy | None:
    """从非敏感 env 字段构造服务器策略，不读取凭据字段。"""

    config: dict[str, Any] = {
        "mode": mode,
        "allow_original_text": _env_value(
            environment, "REPORT_VERIFY_LLM_ALLOW_ORIGINAL_TEXT", "true"
        ),
        "allowed_hosts": _env_value(
            environment, "REPORT_VERIFY_LLM_ALLOWED_HOSTS", ""
        ),
        "allow_plaintext": _env_value(
            environment, "REPORT_VERIFY_LLM_ALLOW_PLAINTEXT", "false"
        ),
        "allow_job_override": _env_value(
            environment, "REPORT_VERIFY_LLM_ALLOW_JOB_OVERRIDE", "true"
        ),
        "allowed_modes": _env_value(
            environment, "REPORT_VERIFY_LLM_ALLOWED_MODES", ",".join(ALL_MODES)
        ),
        "redaction_profile": _env_value(
            environment, "REPORT_VERIFY_LLM_REDACTION_PROFILE", "standard"
        ),
        "policy_version": "policy-v1",
        # allow_images 刻意不传入：图片开关由 release gate 单独检查，避免
        # ServerLLMPolicy 的强制 False 把恶意 true 配置静默变成看似安全。
    }
    try:
        return ServerLLMPolicy.from_config(config)
    except (PolicyError, TypeError, ValueError):
        return None


def evaluate_release_gate(
    environment: Mapping[str, str] | None = None,
    *,
    requested_mode: str | None = None,
    override_fields: Mapping[str, Any] | None = None,
    provider_base_url: str | None = None,
) -> ReleaseGateResult:
    """执行本地、无网络、脱敏的 LLM 发布门禁。

    Parameters
    ----------
    environment:
        可注入的环境映射。实现只读取非敏感配置值；凭据目标名只做存在性
        检查。默认使用当前进程环境。
    requested_mode:
        可选的任务级 mode。它只会经过服务器 allowlist 校验，不会改变 provider
        或外发策略。
    override_fields:
        可选任务请求字段名映射。只检查字段名，绝不回显字段值。
    provider_base_url:
        可选的非敏感 endpoint 值，便于部署检查使用受控 placeholder；未传时
        从 ``REPORT_VERIFY_LLM_BASE_URL`` 读取，但不会写入诊断。
    """

    env = os.environ if environment is None else environment
    mode = _env_value(env, MODE_ENV_NAME, DEFAULT_PRODUCTION_MODE).strip().lower()
    mode_valid = mode in ALL_MODES

    # 图片开关必须显式 fail closed。LLMSettings 会把 true 强制成 False，但
    # 发布门禁仍需发现原始配置中的越权意图，而不是把它静默当成通过。
    raw_image = _env_value(env, "REPORT_VERIFY_LLM_ALLOW_IMAGES", "")
    image_flag = _parse_bool(raw_image)
    image_ok = not raw_image.strip() or image_flag is False
    image_check = _check(
        "image_hard_rejection",
        image_ok,
        required=True,
        code=ERROR_IMAGE_GATE if not image_ok else "",
        detail=(
            "图片能力固定为 false；true 或歧义配置阻断 provider"
            if not image_ok
            else "图片能力固定为 false"
        ),
    )

    policy = _policy_from_environment(env, mode) if mode_valid else None
    policy_ok = policy is not None
    policy_check = _check(
        "policy_configuration",
        policy_ok,
        required=mode_valid and mode != DEFAULT_PRODUCTION_MODE,
        code=ERROR_POLICY_CONFIG_GATE if not policy_ok else "",
        detail="服务器策略可解析" if policy_ok else "服务器策略配置无效，保持关闭",
    )

    # 服务器默认 mode 必须是已知值；off 的关闭语义本身永远安全。
    mode_check = _check(
        "production_mode",
        mode_valid,
        required=True,
        code=ERROR_MODE_GATE if not mode_valid else "",
        detail=(
            "生产默认 mode=off，provider 不启用"
            if mode == DEFAULT_PRODUCTION_MODE
            else "服务器 mode 已声明，仍需通过其余激活门禁"
        ),
    )

    effective_mode = ""
    server_mode_allowlist_ok = False
    task_mode_ok = False
    mode_error_code = ""
    task_error_code = ""
    if policy is not None:
        server_mode_allowlist_ok = policy.mode in policy.allowed_job_modes
        try:
            effective_mode = authorize_job_mode(
                policy,
                requested_mode,
                override_fields=override_fields,
            )
            task_mode_ok = True
        except PolicyError as exc:
            task_error_code = exc.code or ERROR_TASK_MODE_NOT_ALLOWED
    else:
        task_error_code = ERROR_POLICY_CONFIG_GATE

    if not server_mode_allowlist_ok:
        mode_error_code = ERROR_MODE_ALLOWLIST_GATE
    mode_allowlist_check = _check(
        "server_mode_allowlist",
        server_mode_allowlist_ok,
        required=mode_valid and (mode != DEFAULT_PRODUCTION_MODE or requested_mode not in (None, "off")),
        code=mode_error_code,
        detail=(
            "服务器默认 mode 在 allowlist 中"
            if server_mode_allowlist_ok
            else "服务器默认 mode 不在 allowlist，保持关闭"
        ),
    )
    task_check = _check(
        "task_mode_authorization",
        task_mode_ok,
        required=requested_mode is not None or bool(override_fields),
        code=task_error_code or ERROR_TASK_MODE_NOT_ALLOWED,
        detail=(
            "任务只选择服务器 allowlist 中的 mode，未覆盖安全策略"
            if task_mode_ok
            else "任务 mode/策略覆盖未通过服务器校验"
        ),
    )

    activation_mode = effective_mode or (mode if mode_valid else "")
    enabled_for_activation = activation_mode in ALL_MODES and activation_mode != DEFAULT_PRODUCTION_MODE

    # 凭据映射只做变量名存在性检查；即便 enabled 也不读取 API key/user key 值。
    injection: InjectionCheck = check_credential_injection(env)
    mapping_ok = injection.ready
    mapping_check = _check(
        "credential_mapping",
        mapping_ok if enabled_for_activation else True,
        required=enabled_for_activation,
        code=ERROR_MAPPING_GATE if enabled_for_activation and not mapping_ok else "",
        detail=(
            "CertAgent→ReportVerify 目标变量名映射已通过"
            if mapping_ok
            else "凭据目标变量缺失或不可检查，保持关闭"
        ),
    )

    original_ok = bool(policy is not None and policy.allow_original_text)
    original_check = _check(
        "original_text_policy",
        original_ok if enabled_for_activation else True,
        required=enabled_for_activation,
        code=ERROR_ORIGINAL_TEXT_GATE if enabled_for_activation and not original_ok else "",
        detail=(
            "服务器允许字段白名单原文并继续受限"
            if original_ok
            else "服务器原文策略未获批准，保持关闭"
        ),
    )

    # host/TLS 检查只在实际 effective mode 非 off 时成为 provider 激活条件。
    endpoint_ok = True
    endpoint_detail = "mode=off，不检查 provider endpoint"
    endpoint_code = ""
    if enabled_for_activation:
        if policy is None or not policy.allowed_hosts:
            endpoint_ok = False
            endpoint_code = ERROR_HOST_TLS_GATE
            endpoint_detail = "host allowlist 缺失，保持关闭"
        else:
            base_url = (
                provider_base_url
                if provider_base_url is not None
                else _env_value(env, BASE_URL_ENV_NAME, "")
            )
            endpoint = authorize_provider_endpoint(policy, base_url)
            endpoint_ok = endpoint.authorized
            endpoint_code = ERROR_HOST_TLS_GATE if not endpoint.authorized else ""
            endpoint_detail = (
                "provider host/TLS 通过服务器 allowlist"
                if endpoint.authorized
                else "provider host/TLS 未通过服务器 allowlist，保持关闭"
            )
    endpoint_check = _check(
        "host_tls_allowlist",
        endpoint_ok,
        required=enabled_for_activation,
        code=endpoint_code,
        detail=endpoint_detail,
    )

    checks = (
        mode_check,
        policy_check,
        mapping_check,
        endpoint_check,
        mode_allowlist_check,
        task_check,
        original_check,
        image_check,
    )
    provider_allowed = bool(
        enabled_for_activation
        and all(check.passed for check in checks if check.required_for_provider)
    )
    return ReleaseGateResult(
        mode=mode,
        effective_mode=activation_mode,
        provider_allowed=provider_allowed,
        checks=checks,
    )


def main() -> int:
    """输出脱敏门禁结果；不访问网络。"""

    result = evaluate_release_gate()
    print(json.dumps(result.diagnostics(), ensure_ascii=False, sort_keys=True))
    return 0 if result.release_safe else 1


__all__ = [
    "DEFAULT_PRODUCTION_MODE",
    "MODE_ENV_NAME",
    "BASE_URL_ENV_NAME",
    "ERROR_MODE_GATE",
    "ERROR_MAPPING_GATE",
    "ERROR_HOST_TLS_GATE",
    "ERROR_MODE_ALLOWLIST_GATE",
    "ERROR_ORIGINAL_TEXT_GATE",
    "ERROR_IMAGE_GATE",
    "ERROR_TASK_OVERRIDE_GATE",
    "ERROR_POLICY_CONFIG_GATE",
    "ReleaseGateCheck",
    "ReleaseGateResult",
    "evaluate_release_gate",
    "main",
]


if __name__ == "__main__":  # pragma: no cover - exercised by release command
    raise SystemExit(main())
