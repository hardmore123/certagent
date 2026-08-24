"""规则加载器：正向规则 + 反向规则（误报防护）。极简。"""
from __future__ import annotations

from pathlib import Path

import yaml

from ..config import config


def load_rules() -> dict:
    path = config.RULES_DIR / "merge_rules.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_avoidance() -> list[dict]:
    path = config.RULES_DIR / "avoidance" / "false_positive.yaml"
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return data if isinstance(data, list) else data.get("rules", [])
