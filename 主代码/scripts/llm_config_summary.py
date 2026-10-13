"""打印当前生效的 LLM 配置摘要（脱敏）。

密钥只显示"已设置/未设置"，绝不打印值；base_url 只显示 host，不显示完整路径。
供 scripts/check_llm.ps1 调用，也可单独运行：
    python scripts/llm_config_summary.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# 允许从项目根目录外调用
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from report_verify.env_bootstrap import load_project_env  # noqa: E402


def _mask(value: str) -> str:
    return "已设置" if value else "未设置"


def _host_of(url: str) -> str:
    if "//" not in url:
        return "(未设置)"
    try:
        return url.split("/")[2]
    except IndexError:
        return "(无法解析)"


def main() -> int:
    load_project_env()
    from report_verify.llm.config import LLMSettings

    s = LLMSettings.from_env()
    rows = [
        ("mode", s.mode),
        ("model", s.model or "(未设置)"),
        ("base_url host", _host_of(s.base_url)),
        ("api_key", _mask(s.api_key)),
        ("user_key", _mask(s.user_key)),
        ("allowed_job_modes", ", ".join(sorted(s.allowed_job_modes))),
        ("allowed_hosts", ", ".join(sorted(s.allowed_hosts)) or "(空)"),
        ("allow_original_text", str(s.allow_original_text)),
        ("allow_images", f"{s.allow_images}（固定硬拒绝）"),
        ("timeout / total", f"{s.timeout_seconds}s / {s.total_timeout_seconds}s"),
        (
            "explain batch/max/workers",
            f"{s.explain_batch_rows} / {s.explain_max_diffs} / {s.explain_max_workers}",
        ),
        ("status", s.status()),
    ]
    width = max(len(name) for name, _ in rows)
    for name, value in rows:
        print(f"{name.ljust(width)} : {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
