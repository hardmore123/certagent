"""可版本化、可解释的字段归一化规则。"""
from __future__ import annotations

import json
from pathlib import Path

from .field_map import DEFAULT_ENABLED_RULES, normalize_for_compare

DEFAULT_RULE_VERSION = "normalized-v2"
DEFAULT_RULES = {
    "version": DEFAULT_RULE_VERSION,
    "enabled": list(DEFAULT_ENABLED_RULES),
    "description": "默认忽略外层空白、连续空白、大小写、全半角及明确等价波浪线，并把占位符（/、-、N/A 等）视为空，以及把列表分隔符（换行/分号/顿号/逗号）视为等价（顺序敏感），并忽略所有内部空白（标准号/型号内部空格视为格式差异）；实质字符差异仍保留。",
}


def load_rules(path: str | None = None) -> dict:
    candidate = Path(path) if path else Path(__file__).resolve().parents[1] / "rules" / "normalization.json"
    if not candidate.exists():
        return dict(DEFAULT_RULES)
    return json.loads(candidate.read_text(encoding="utf-8"))


def same_value(cert_value: str, draft_value: str, rules: dict | None = None) -> bool:
    return normalize_for_compare(cert_value, rules) == normalize_for_compare(draft_value, rules)
