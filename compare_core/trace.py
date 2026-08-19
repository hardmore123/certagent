"""极简 trace：把各阶段中间产物落盘，供人工核对与排查。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import config


def _run_dir() -> Path:
    d = config.TRACE_DIR / datetime.now().strftime("%m%d-%H%M%S")
    d.mkdir(parents=True, exist_ok=True)
    return d


_CURRENT: Path | None = None


def new_run() -> Path:
    global _CURRENT
    _CURRENT = _run_dir()
    return _CURRENT


def dump(name: str, data: Any) -> None:
    """把一个阶段产物写成 json（容错，失败不影响主流程）。"""
    global _CURRENT
    if _CURRENT is None:
        _CURRENT = _run_dir()
    try:
        path = _CURRENT / f"{name}.json"

        def _default(o: Any):
            if hasattr(o, "model_dump"):
                return o.model_dump()
            return str(o)

        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=_default), encoding="utf-8")
    except Exception as e:  # noqa: BLE001 - trace 不能拖垮主流程
        print(f"[trace] dump {name} failed: {e}")
