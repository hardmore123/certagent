"""Web 配置：全从环境变量读取。"""
from __future__ import annotations

import os
from pathlib import Path


class WebSettings:
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-change-in-prod")
    JOBS_DIR: Path = Path(os.getenv("JOBS_DIR", str(Path(__file__).resolve().parents[1] / "runs" / "web_jobs")))
    MAX_UPLOAD_MB: int = int(os.getenv("MAX_UPLOAD_MB", "50"))
    MAX_CONCURRENT_JOBS: int = int(os.getenv("MAX_CONCURRENT_JOBS", "2"))
    CORS_ALLOW_ORIGINS: list[str] = os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:8123").split(",")
    # 默认用户（简化版，不需要 users.yaml）
    DEFAULT_USER: str = os.getenv("DEFAULT_USER", "admin")
    DEFAULT_PASSWORD: str = os.getenv("DEFAULT_PASSWORD", "admin123")
    # 是否启用 LLM fuzzy 候选提名（默认关闭；需 .env 配好 LLM_*）。开启后每个任务会多一次 LLM 调用。
    ENABLE_FUZZY_LLM: bool = os.getenv("ENABLE_FUZZY_LLM", "false").strip().lower() == "true"
    FUZZY_THRESHOLD: float = float(os.getenv("FUZZY_THRESHOLD", "0.8"))


settings = WebSettings()
