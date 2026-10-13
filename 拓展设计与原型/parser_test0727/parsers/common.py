"""Small helpers shared by parser route adapters."""
from __future__ import annotations

import re
from typing import Any

from compare_core.models import Row
from compare_core.parser.doc_parser import HEADER_MAP

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def clean(value: Any) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ")
    return _CTRL.sub("", text).strip()


def field_for_header(value: str) -> str | None:
    text = clean(value).replace("（", "(").replace("）", ")")
    direct = HEADER_MAP.get(text)
    if direct:
        return direct
    compact = "".join(text.split())
    if compact == "规格":
        return "规格材料"
    for header, field in HEADER_MAP.items():
        normalized = header.replace("（", "(").replace("）", ")")
        if "".join(normalized.split()) == compact:
            return field
    return None


def make_row(data: dict[str, Any], raw: dict[str, str]) -> Row:
    data["raw"] = raw
    return Row(**{k: v for k, v in data.items() if k in Row.model_fields or k == "raw"})


def row_dicts(rows: list[Row]) -> list[dict[str, Any]]:
    return [row.model_dump(mode="json") for row in rows]
