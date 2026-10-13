"""CERT/DRAFT 表头别名和字段映射。"""
from __future__ import annotations

import re

# 仅用于识别字段，不用于自动忽略正文字符差异。
ALIASES: dict[str, str] = {
    "序号": "序号",
    "位号": "位号",
    "部件号": "位号",
    "元件": "位号",
    "关键件名称": "关键件名称",
    "名称": "关键件名称",
    "型号": "型号",
    "规格/材料": "规格材料",
    "规格材料": "规格材料",
    "规格": "规格材料",
    "生产者(制造商)": "制造商",
    "生产者（制造商）": "制造商",
    "制造商": "制造商",
    "制造商 (全称)": "制造商",
    "制造商（全称）": "制造商",
    "制造商(全称)": "制造商",
    "生产企业": "生产企业",
    "生产厂(全称)": "生产企业",
    "生产厂（全称）": "生产企业",
    "认证标准": "认证标准",
    "认证标准（重复列）": "认证标准",
    "本次使用/备用": "本次使用",
    "使用/备用": "本次使用",
    "备注": "备注",
    "证书号": "证书号",
    "序号和名称": "项目",
    "变更前": "变更前",
    "变更后": "变更后",
}

TARGET_FIELDS = [
    "序号", "位号", "关键件名称", "型号", "规格材料", "制造商",
    "生产企业", "认证标准", "证书号", "本次使用", "备注",
]

# 归一化后被视为“空”的占位符值（小写）；与 verify_differ 的 _PLACEHOLDERS 保持单一事实源。
PLACEHOLDER_VALUES = frozenset({"", "/", "-", "—", "–", "n/a", "na", "none"})

# 这些规则只处理已确认的格式差异；不会删除型号、证书号或数值中的实质字符。
DEFAULT_ENABLED_RULES = (
    "trim_outer_space",
    "collapse_whitespace",
    "casefold",
    "fullwidth_ascii",
    "wave_dash",
    "list_separator",
    "strip_all_space",
    "placeholder_blank",
)
_FULLWIDTH_ASCII = str.maketrans(
    {chr(code): chr(code - 0xFEE0) for code in range(0xFF01, 0xFF5F)}
    | {"\u3000": " "}
)


def clean_text(value: object) -> str:
    """只做文档结构清理，不做业务归一化。"""
    if value is None:
        return ""
    return str(value).replace("\r", "\n").strip()


def compact_header(value: object) -> str:
    text = clean_text(value).replace("（", "(").replace("）", ")")
    return re.sub(r"\s+", "", text)


def canonical_header(value: object) -> str | None:
    text = clean_text(value).replace("（", "(").replace("）", ")")
    if text in ALIASES:
        return ALIASES[text]
    if text.startswith("变更前"):
        return "变更前"
    if text.startswith("变更后"):
        return "变更后"
    compact = compact_header(text)
    for alias, field in ALIASES.items():
        if compact_header(alias) == compact:
            return field
    return None


def normalize_for_compare(value: object, rules: dict | None = None) -> str:
    """返回仅用于比较的值，默认忽略已确认的格式差异。

    传入 ``enabled: []`` 可显式使用严格模式；未传规则或未声明 enabled
    时使用 DEFAULT_ENABLED_RULES。原始值始终由调用方保留用于展示。
    """
    text = "" if value is None else str(value)
    if rules is None:
        enabled = set(DEFAULT_ENABLED_RULES)
    else:
        enabled = set(rules.get("enabled", DEFAULT_ENABLED_RULES))
    if "fullwidth_ascii" in enabled:
        text = text.translate(_FULLWIDTH_ASCII)
    if "wave_dash" in enabled:
        text = text.replace("～", "~")
    if "collapse_whitespace" in enabled:
        text = re.sub(r"\s+", " ", text)
    if "trim_outer_space" in enabled:
        text = text.strip()
    if "casefold" in enabled:
        text = text.casefold()
    if "list_separator" in enabled:
        text = re.sub(r"[;,；，、]", " ", text)   # 列表分隔符统一成空格
        text = re.sub(r"\s+", " ", text).strip()  # 再压一次空白（换行此前已被压成空格）
    if "strip_all_space" in enabled:
        text = re.sub(r"\s+", "", text)  # 去掉所有内部空白（标准号/型号内部空格视为格式差异）
    if "placeholder_blank" in enabled and text.strip().casefold() in PLACEHOLDER_VALUES:
        return ""
    return text
