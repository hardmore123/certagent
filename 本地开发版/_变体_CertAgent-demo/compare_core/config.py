"""运行配置：从环境变量读取，集中管理。"""
from __future__ import annotations

import os
from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parent


class Config:
    # suggester: mock | llm
    SUGGESTER_MODE = os.getenv("SUGGESTER_MODE", "mock")

    # OpenAI 兼容 LLM 接口（内网聚好看 higpt 等）
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")
    LLM_MODEL = os.getenv("LLM_MODEL", "")
    # 聚好看网关需要的额外鉴权：作为 query 参数 ?user_key=... 传递（非聚好看留空即可）
    LLM_USER_KEY = os.getenv("LLM_USER_KEY", "")
    LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "60"))
    LLM_MAX_RETRY = int(os.getenv("LLM_MAX_RETRY", "2"))

    # 输出是否统一转简体（繁→简）。默认开启，可 OUTPUT_SIMPLIFIED=false 关闭以保留原文
    OUTPUT_SIMPLIFIED = os.getenv("OUTPUT_SIMPLIFIED", "true").strip().lower() != "false"

    # 输出统一字体（中英文）。可用 OUTPUT_FONT 覆盖
    OUTPUT_FONT = os.getenv("OUTPUT_FONT", "宋体")

    # 整合清单“来源”呈现方式：true=Word 批注（去掉来源列，列结构贴近标准模板），
    # false=保留末列“来源”文本列。默认走批注。
    OUTPUT_SOURCE_AS_COMMENT = os.getenv("OUTPUT_SOURCE_AS_COMMENT", "true").strip().lower() != "false"
    # 批注作者/缩写
    OUTPUT_COMMENT_AUTHOR = os.getenv("OUTPUT_COMMENT_AUTHOR", "认证Agent")

    # 是否以输入文件（PLM 新版本=输出骨架）为格式模板：提取其字体/字号/页面/列宽套用到整合清单。
    # 默认开启；关闭则用 OUTPUT_FONT + python-docx 默认排版（旧行为）。
    OUTPUT_USE_INPUT_TEMPLATE = os.getenv("OUTPUT_USE_INPUT_TEMPLATE", "true").strip().lower() != "false"

    # 长期记忆：是否在 suggest 时读回历史决策反哺建议（默认开启）。
    MEMORY_ENABLED = os.getenv("MEMORY_ENABLED", "true").strip().lower() != "false"
    # 视为“强信号”的最小样本数：某指纹被否/被确认达到该次数才触发预置动作/置信度调整。
    MEMORY_STRONG_MIN = int(os.getenv("MEMORY_STRONG_MIN", "2"))

    RULES_DIR = _root() / "rules" / "data"
    TRACE_DIR = Path(os.getenv("TRACE_DIR", str(_root().parent / "runs")))
    FEEDBACK_FILE = Path(os.getenv("FEEDBACK_FILE", str(_root().parent / "runs" / "feedback.jsonl")))


config = Config()
