from __future__ import annotations

import json
import unittest
from collections.abc import Iterator, Mapping

from report_verify.llm_injection_check import (
    CERTAGENT_TO_REPORT_VERIFY_ENV,
    OPTIONAL_REPORT_VERIFY_ENV_NAMES,
    REQUIRED_REPORT_VERIFY_ENV_NAMES,
    check_credential_injection,
)


class PresenceOnlyEnvironment(Mapping[str, str]):
    """Test environment that fails if implementation reads a value."""

    def __init__(self, names: set[str], denied: set[str] | None = None) -> None:
        self._names = set(names)
        self._denied = set(denied or ())
        self.value_reads: list[str] = []
        self.presence_checks: list[str] = []

    def __contains__(self, name: object) -> bool:
        if not isinstance(name, str):
            return False
        self.presence_checks.append(name)
        if name in self._denied:
            raise PermissionError(name)
        return name in self._names

    def __getitem__(self, name: str) -> str:
        self.value_reads.append(name)
        raise AssertionError(f"environment value was read: {name}")

    def __iter__(self) -> Iterator[str]:
        return iter(self._names)

    def __len__(self) -> int:
        return len(self._names)


class LLMInjectionCheckTests(unittest.TestCase):
    def test_mapping_matches_certagent_contract_without_values(self):
        self.assertEqual(
            dict(CERTAGENT_TO_REPORT_VERIFY_ENV),
            {
                "LLM_BASE_URL": "REPORT_VERIFY_LLM_BASE_URL",
                "LLM_MODEL": "REPORT_VERIFY_LLM_MODEL",
                "LLM_API_KEY": "REPORT_VERIFY_LLM_API_KEY",
                "LLM_USER_KEY": "REPORT_VERIFY_LLM_USER_KEY",
            },
        )

    def test_required_targets_pass_with_placeholder_name_only_environment(self):
        environment = PresenceOnlyEnvironment(
            set(REQUIRED_REPORT_VERIFY_ENV_NAMES) | set(OPTIONAL_REPORT_VERIFY_ENV_NAMES)
        )

        result = check_credential_injection(environment)

        self.assertTrue(result.ready)
        self.assertEqual(result.missing_required, ())
        self.assertEqual(result.inaccessible, ())
        self.assertFalse(environment.value_reads)
        self.assertTrue(environment.presence_checks)

    def test_optional_user_key_is_not_required(self):
        environment = PresenceOnlyEnvironment(set(REQUIRED_REPORT_VERIFY_ENV_NAMES))

        result = check_credential_injection(environment)

        self.assertTrue(result.ready)
        self.assertEqual(result.missing_required, ())
        user_key = next(
            item for item in result.variables
            if item.target_name == "REPORT_VERIFY_LLM_USER_KEY"
        )
        self.assertFalse(user_key.present)
        self.assertFalse(environment.value_reads)

    def test_missing_required_name_is_reported_without_reading_value(self):
        environment = PresenceOnlyEnvironment({"REPORT_VERIFY_LLM_BASE_URL"})

        result = check_credential_injection(environment)

        self.assertFalse(result.ready)
        self.assertEqual(
            result.missing_required,
            ("REPORT_VERIFY_LLM_MODEL", "REPORT_VERIFY_LLM_API_KEY"),
        )
        self.assertFalse(environment.value_reads)

    def test_environment_permission_failure_fails_closed(self):
        environment = PresenceOnlyEnvironment(
            set(REQUIRED_REPORT_VERIFY_ENV_NAMES),
            denied={"REPORT_VERIFY_LLM_API_KEY"},
        )

        result = check_credential_injection(environment)

        self.assertFalse(result.ready)
        self.assertEqual(result.inaccessible, ("REPORT_VERIFY_LLM_API_KEY",))
        self.assertFalse(environment.value_reads)

    def test_diagnostics_are_redacted_and_contain_no_placeholder_values(self):
        environment = PresenceOnlyEnvironment(
            set(REQUIRED_REPORT_VERIFY_ENV_NAMES) | set(OPTIONAL_REPORT_VERIFY_ENV_NAMES)
        )

        diagnostics = check_credential_injection(environment).diagnostics()
        serialized = json.dumps(diagnostics, ensure_ascii=False, sort_keys=True)

        self.assertNotIn("placeholder-api-key", serialized)
        self.assertNotIn("placeholder-user-key", serialized)
        self.assertFalse(diagnostics["secret_values_read"])
        self.assertFalse(diagnostics["secret_values_in_diagnostics"])
        self.assertFalse(diagnostics["secret_values_persisted"])
        self.assertFalse(environment.value_reads)


if __name__ == "__main__":
    unittest.main()
