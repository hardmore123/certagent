"""归一化：比对前消除格式类噪声，减少误报。含繁→简折叠。"""
from __future__ import annotations

import re

_TILDE = {"～": "~", "﹀": "~"}

# opencc 繁→简 转换器（懒加载，未安装则优雅降级为原样返回）
_CONVERTER = None
_CONVERTER_TRIED = False


def _get_converter():
    global _CONVERTER, _CONVERTER_TRIED
    if not _CONVERTER_TRIED:
        _CONVERTER_TRIED = True
        try:
            from opencc import OpenCC

            _CONVERTER = OpenCC("t2s")
        except Exception:  # noqa: BLE001 - 无 opencc 时不阻断
            _CONVERTER = None
    return _CONVERTER


def to_simplified(text: str) -> str:
    """繁体→简体；未安装 opencc 时原样返回。"""
    if not text:
        return text
    conv = _get_converter()
    if conv is None:
        return text
    try:
        return conv.convert(text)
    except Exception:  # noqa: BLE001
        return text


def _fullwidth_to_halfwidth(s: str) -> str:
    out = []
    for ch in s:
        code = ord(ch)
        if code == 0x3000:
            out.append(" ")
        elif 0xFF01 <= code <= 0xFF5E:
            out.append(chr(code - 0xFEE0))
        else:
            out.append(ch)
    return "".join(out)


def normalize(text: str, *, drop_space: bool = True) -> str:
    if not text:
        return ""
    s = to_simplified(text)          # 繁→简折叠，避免繁/简变体判为差异
    s = _fullwidth_to_halfwidth(s)
    for k, v in _TILDE.items():
        s = s.replace(k, v)
    s = s.replace("，", ",").replace("、", ",")
    if drop_space:
        s = re.sub(r"\s+", "", s)
    else:
        s = re.sub(r"\s+", " ", s).strip()
    return s.lower()
