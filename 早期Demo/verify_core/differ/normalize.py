"""归一化：消除"无意义差异"（空格/全半角/标点/单位写法）。"""
from __future__ import annotations

import re

_SPACE = re.compile(r"\s+")
# 全角 -> 半角标点常见映射
_PUNCT = {
    "（": "(", "）": ")", "，": ",", "、": ",", "／": "/",
    "：": ":", "；": ";", "～": "~", "－": "-", "　": " ",
}


def norm(text: str | None) -> str:
    """强归一：去空格、全角转半角、小写。用于匹配键与字段比对。"""
    if not text:
        return ""
    s = str(text)
    for a, b in _PUNCT.items():
        s = s.replace(a, b)
    s = _SPACE.sub("", s)
    return s.lower()


def norm_std(text: str | None) -> str:
    """认证标准专用归一：GB/T 15934-2024 与 GB/T15934-2024 视为相同。"""
    return norm(text).replace(".", "")
