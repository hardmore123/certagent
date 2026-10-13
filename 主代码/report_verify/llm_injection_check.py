"""Non-secret preflight checks for CertAgent -> ReportVerify injection.

This module deliberately checks environment *names* only.  It never reads an
environment value, and therefore cannot expose or persist an API key or a
user-key while checking a controlled deployment.
"""
from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


# These names mirror CertAgent's existing compare_core.config.Config fields.
# The target names are the only names ReportVerify is expected to receive at
# runtime.  Values are injected by the deployment environment, not copied by
# this module.
CERTAGENT_TO_REPORT_VERIFY_ENV = MappingProxyType({
    "LLM_BASE_URL": "REPORT_VERIFY_LLM_BASE_URL",
    "LLM_MODEL": "REPORT_VERIFY_LLM_MODEL",
    "LLM_API_KEY": "REPORT_VERIFY_LLM_API_KEY",
    "LLM_USER_KEY": "REPORT_VERIFY_LLM_USER_KEY",
})

REQUIRED_REPORT_VERIFY_ENV_NAMES = (
    "REPORT_VERIFY_LLM_BASE_URL",
    "REPORT_VERIFY_LLM_MODEL",
    "REPORT_VERIFY_LLM_API_KEY",
)
OPTIONAL_REPORT_VERIFY_ENV_NAMES = ("REPORT_VERIFY_LLM_USER_KEY",)

_SECRET_SOURCE_NAMES = frozenset({"LLM_API_KEY", "LLM_USER_KEY"})
_SECRET_TARGET_NAMES = frozenset({
    "REPORT_VERIFY_LLM_API_KEY",
    "REPORT_VERIFY_LLM_USER_KEY",
})
_EXPECTED_MAPPING = (
    ("LLM_BASE_URL", "REPORT_VERIFY_LLM_BASE_URL"),
    ("LLM_MODEL", "REPORT_VERIFY_LLM_MODEL"),
    ("LLM_API_KEY", "REPORT_VERIFY_LLM_API_KEY"),
    ("LLM_USER_KEY", "REPORT_VERIFY_LLM_USER_KEY"),
)


@dataclass(frozen=True)
class VariablePresence:
    """Presence/access result for one non-secret target variable name.

    No value is stored here.  ``accessible`` means that checking membership in
    the process environment was permitted; it does not imply that a value was
    fetched or that the value is non-empty.
    """

    source_name: str
    target_name: str
    present: bool
    accessible: bool


@dataclass(frozen=True)
class InjectionCheck:
    """Non-sensitive result of the controlled-injection preflight."""

    mapping_valid: bool
    variables: tuple[VariablePresence, ...]
    missing_required: tuple[str, ...]
    inaccessible: tuple[str, ...]

    @property
    def ready(self) -> bool:
        """Whether the name-level preflight passed.

        This check intentionally does not validate values, provider reachability
        or credentials.  Those are outside task 0.1 and must not cause this
        helper to read a secret.
        """

        return self.mapping_valid and not self.missing_required and not self.inaccessible

    def diagnostics(self) -> dict[str, Any]:
        """Return names and booleans only; never include environment values."""

        return {
            "mapping_valid": self.mapping_valid,
            "mapping": [
                {"source": source, "target": target}
                for source, target in _EXPECTED_MAPPING
            ],
            "variables": [
                {
                    "source": item.source_name,
                    "target": item.target_name,
                    "present": item.present,
                    "accessible": item.accessible,
                    "secret": item.target_name in _SECRET_TARGET_NAMES,
                }
                for item in self.variables
            ],
            "missing_required": list(self.missing_required),
            "inaccessible": list(self.inaccessible),
            # Explicit invariants make the redaction contract auditable without
            # exposing a value or a reversible representation of one.
            "secret_values_read": False,
            "secret_values_in_diagnostics": False,
            "secret_values_persisted": False,
        }


def _mapping_is_valid() -> bool:
    """Validate the fixed name-only mapping against the approved contract."""

    return tuple(CERTAGENT_TO_REPORT_VERIFY_ENV.items()) == _EXPECTED_MAPPING


def _check_presence(environment: Mapping[str, str], name: str) -> tuple[bool, bool]:
    """Check one variable name without calling ``get`` or ``__getitem__``."""

    try:
        return name in environment, True
    except (OSError, PermissionError):
        # A restricted environment/secret adapter can deny even name-level
        # inspection.  Fail closed, while retaining only the variable name.
        return False, False


def check_credential_injection(
    environment: Mapping[str, str] | None = None,
) -> InjectionCheck:
    """Run the CertAgent -> ReportVerify name-level injection preflight.

    ``environment`` is injectable for tests and deployment checks.  Only
    membership checks are performed.  In particular, this function never
    calls ``environment.get()``, indexes it, iterates values, or serializes it.
    The source CertAgent variables are not required in the running process:
    deployment maps them into the ReportVerify target names before startup.
    """

    env = os.environ if environment is None else environment
    variables: list[VariablePresence] = []
    missing_required: list[str] = []
    inaccessible: list[str] = []

    for source_name, target_name in _EXPECTED_MAPPING:
        present, accessible = _check_presence(env, target_name)
        variables.append(VariablePresence(
            source_name=source_name,
            target_name=target_name,
            present=present,
            accessible=accessible,
        ))
        if not accessible:
            inaccessible.append(target_name)
        elif target_name in REQUIRED_REPORT_VERIFY_ENV_NAMES and not present:
            missing_required.append(target_name)

    return InjectionCheck(
        mapping_valid=_mapping_is_valid(),
        variables=tuple(variables),
        missing_required=tuple(missing_required),
        inaccessible=tuple(inaccessible),
    )


def main() -> int:
    """Print a redacted preflight report and return a deployment-check status."""

    result = check_credential_injection()
    print(json.dumps(result.diagnostics(), ensure_ascii=False, sort_keys=True))
    return 0 if result.ready else 1


if __name__ == "__main__":  # pragma: no cover - exercised by the CLI check
    raise SystemExit(main())
