"""启动入口：python -m webapi"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 加载 .env
_root = Path(__file__).resolve().parents[1]
_env = _root / ".env"
if _env.exists():
    for line in _env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v

# 确保 compare_core 可导入
sys.path.insert(0, str(_root))

import uvicorn

from .app import app  # noqa: E402, F401

if __name__ == "__main__":
    uvicorn.run(
        "webapi.app:app",
        host="0.0.0.0",
        port=8125,
        reload=True,
        reload_dirs=[str(_root / "webapi"), str(_root / "compare_core")],
    )
else:
    # python -m webapi
    uvicorn.run(
        "webapi.app:app",
        host="0.0.0.0",
        port=8125,
        reload=True,
        reload_dirs=[str(_root / "webapi"), str(_root / "compare_core")],
    )
