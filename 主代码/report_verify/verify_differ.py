"""CERT 应然值与 DRAFT 实然值的匹配和字段级核对。

匹配策略参考 CertAgent，但不复用其 orig/plm 方向：
- 先恢复解析层的 group/纵向合并字段；
- 语义块内使用分组上下文 + 名称 + 型号候选；
- 型号列支持 equal/subset/overlap 集合关系；
- 规格、证书号只用于字段比较和候选消歧，不独立构成身份键；
- 重复行按候选评分做一对一多重集消费，绝不覆盖或按字典丢行。
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass

from .field_map import canonical_header, PLACEHOLDER_VALUES
from .models import Anchor, DocumentRow, LocatedBlock, RowDiff, VerifyDiff
from .rules import load_rules, same_value

LIST_FIELDS = [
    "位号", "关键件名称", "型号", "规格材料", "制造商", "生产企业",
    "认证标准", "证书号", "本次使用", "备注",
]
CHANGE_FIELDS = ["变更前", "变更后"]
_PLACEHOLDERS = PLACEHOLDER_VALUES
_PAREN = re.compile(r"[（(][^（()]*[)）]")
_MODEL_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9*#_.+\-/]{1,}")
_WILDCARD_SUFFIX = re.compile(r"^(.+?)\*+$")


def _value(row: DocumentRow | None, field: str) -> str:
    return (row.values.get(field, "") if row else "") or ""


def _anchor(row: DocumentRow | None, field: str) -> Anchor | None:
    if row is None:
        return None
    if field in row.anchors:
        return row.anchors[field]
    return next(iter(row.anchors.values()), None)


def _key_norm(value: str) -> str:
    """匹配键安全归一化；不改变展示值或字段比较规则。"""
    text = value or ""
    text = text.replace("（", "(").replace("）", ")").replace("～", "~")
    text = text.translate(str.maketrans("，、；", ",,;"))
    return re.sub(r"\s+", "", text).casefold()


def _is_placeholder(value: str) -> bool:
    return _key_norm(value) in _PLACEHOLDERS


def _strip_model_notes(text: str) -> str:
    stripped = _PAREN.sub(" ", text or "")
    stripped = _PAREN.sub(" ", stripped)
    return stripped if stripped.strip() else (text or "")


def _model_tokens(text: str) -> set[str]:
    """参考 CertAgent：先去括号说明，再按外部连接符拆分，保留型号内部 /。"""
    text = _strip_model_notes(text)
    if not text.strip():
        return set()
    primary = "、,，;；+＋\n\r"
    for separator in primary:
        text = text.replace(separator, "\x00")
    tokens = []
    for token in text.split("\x00"):
        token = _key_norm(token).strip(";,，、")
        if token and not _is_placeholder(token) and len(token) >= 2:
            tokens.append(token)
    return set(tokens)


def _model_identity_tokens(text: str) -> set[str]:
    """返回仅用于行身份匹配的型号族键。

    样本中的 ``*`` 尾缀表示企业内部代码，星号数量变化不改变安全/EMC
    适用的型号族。这里只把连续尾部星号折叠为一个标记；原始型号仍由
    ``_value(row, "型号")`` 保留并继续逐字核对。
    """
    identity_tokens: set[str] = set()
    for token in _model_tokens(text):
        match = _WILDCARD_SUFFIX.fullmatch(token)
        if match and match.group(1):
            identity_tokens.add(f"{match.group(1)}*")
        else:
            identity_tokens.add(token)
    return identity_tokens


def _model_relation(left: str, right: str) -> str:
    left_tokens, right_tokens = _model_tokens(left), _model_tokens(right)
    if not left_tokens and not right_tokens:
        return "empty"
    if not left_tokens or not right_tokens:
        return "one_empty"
    if left_tokens == right_tokens:
        return "equal"
    left_identity = _model_identity_tokens(left)
    right_identity = _model_identity_tokens(right)
    if left_identity == right_identity:
        return "wildcard_equal"
    if left_identity < right_identity or right_identity < left_identity:
        return "subset"
    if left_tokens < right_tokens or right_tokens < left_tokens:
        return "subset"
    if left_tokens & right_tokens:
        return "overlap"
    return "disjoint"


def _name_relation(left: str, right: str) -> str:
    left_norm, right_norm = _key_norm(left), _key_norm(right)
    if left_norm and left_norm == right_norm:
        return "equal"
    short, long = sorted((left_norm, right_norm), key=len)
    if len(short) >= 3 and short and long.startswith(short):
        return "prefix"
    return "different"


def _restricted_name_containment(left: str, right: str) -> bool:
    """判断同表场景下可提名复核的短名称包含关系。

    普通前缀仍要求至少 3 个字符；本辅助关系只允许长度为 2 的短名，
    由调用方额外要求同一物理表、型号族相同和分组兼容，不能跨表泛配。
    """
    left_norm, right_norm = _key_norm(left), _key_norm(right)
    if not left_norm or not right_norm or left_norm == right_norm:
        return False
    short, long = sorted((left_norm, right_norm), key=len)
    return len(short) >= 2 and long.startswith(short)


def _group_info(value: str) -> tuple[str, set[str]]:
    normalized = _key_norm(value)
    tokens = {
        _key_norm(token)
        for token in _MODEL_TOKEN.findall(value or "")
        if any(char.isdigit() for char in token) or "-" in token or "*" in token
    }
    return normalized, tokens


def _groups_compatible(left: DocumentRow, right: DocumentRow) -> tuple[bool, bool]:
    """返回 (可匹配, 是否同一规范分组)。空分组是未知，不作为硬拒绝。"""
    left_norm, left_tokens = _group_info(left.group)
    right_norm, right_tokens = _group_info(right.group)
    if not left_norm or not right_norm:
        return True, False
    if left_norm == right_norm:
        return True, True
    if left_tokens and right_tokens and left_tokens & right_tokens:
        return True, False
    return False, False


@dataclass(frozen=True)
class _Profile:
    index: int
    row: DocumentRow
    name: str
    model: str
    position: str
    group_norm: str
    group_tokens: frozenset[str]


def _profile(index: int, row: DocumentRow) -> _Profile:
    group_norm, group_tokens = _group_info(row.group)
    return _Profile(
        index=index,
        row=row,
        name=_key_norm(_value(row, "关键件名称")),
        model=_value(row, "型号"),
        position=_value(row, "位号"),
        group_norm=group_norm,
        group_tokens=frozenset(group_tokens),
    )


def _candidate(
    cert: _Profile, draft: _Profile, *,
    allow_same_table_name_variant: bool = False,
) -> tuple[int, float, str, str] | None:
    compatible, same_group = _groups_compatible(cert.row, draft.row)
    if not compatible:
        return None
    model_relation = _model_relation(cert.model, draft.model)
    if model_relation in {"disjoint", "one_empty"}:
        # 一侧型号缺失不能被名称相同掩盖；否则会把解析错误或真实漏填
        # 当成同一行，进而吞掉 missing/extra 证据。
        return None
    # 名称是常用身份字段，但报告模板可能增加“天线/内置”等语义前缀。
    # 只有型号集合相同/包含关系，并且证书号相同，或规格+位号同时相同，
    # 才允许名称不同的确定性候选；该候选降置信度并保留名称字段差异。
    cert_no, draft_no = _value(cert.row, "证书号"), _value(draft.row, "证书号")
    cert_spec, draft_spec = _value(cert.row, "规格材料"), _value(draft.row, "规格材料")
    cert_pos, draft_pos = cert.position, draft.position
    certificate_same = (
        not _is_placeholder(cert_no) and not _is_placeholder(draft_no)
        and _key_norm(cert_no) == _key_norm(draft_no)
    )
    spec_and_position_same = (
        not _is_placeholder(cert_spec) and not _is_placeholder(draft_spec)
        and _key_norm(cert_spec) == _key_norm(draft_spec)
        and not _is_placeholder(cert_pos) and not _is_placeholder(draft_pos)
        and _key_norm(cert_pos) == _key_norm(draft_pos)
    )
    name_relation = _name_relation(cert.name, draft.name)
    same_table_name_variant = (
        allow_same_table_name_variant
        and name_relation == "different"
        and _restricted_name_containment(cert.name, draft.name)
        and model_relation in {"equal", "wildcard_equal"}
    )
    strong_identity = (
        model_relation in {"equal", "wildcard_equal", "subset"}
        and (certificate_same or spec_and_position_same)
    )
    if name_relation == "different" and not (strong_identity or same_table_name_variant):
        return None
    # 名称为空是解析/数据质量问题，不能拿空名称自动合并。
    if not cert.name or not draft.name:
        return None

    score = 0
    reasons: list[str] = []
    if same_group:
        score += 30
        reasons.append("同分组")
    elif cert.group_norm and draft.group_norm:
        score += 12
        reasons.append("分组型号上下文相容")
    else:
        reasons.append("分组未知")
    if name_relation == "equal":
        score += 55
        reasons.append("名称相同")
    elif name_relation == "prefix":
        score += 22
        reasons.append("名称前缀候选")
    elif same_table_name_variant:
        score += 24
        reasons.append("同一物理表内名称包含且型号族相同，需复核名称")
    else:
        score += 30
        reasons.append("名称不同但型号与证书/规格身份强一致，需复核名称")
    confidence = 0.94 if name_relation == "equal" else 0.72
    if same_table_name_variant:
        confidence = min(confidence, 0.58)
    elif strong_identity and name_relation == "different":
        confidence = min(confidence, 0.70)
    status = "matched"
    if model_relation == "equal":
        score += 45
        reasons.append("型号集合相同")
        confidence += 0.04
    elif model_relation == "wildcard_equal":
        score += 40
        reasons.append("型号通配符族相同，保留星号原文差异，需复核")
        confidence = min(confidence, 0.78)
        status = "needs_review"
    elif model_relation == "subset":
        score += 35
        reasons.append("型号集合存在子集关系")
        confidence = min(confidence, 0.88)
    elif model_relation == "overlap":
        score += 12
        reasons.append("型号集合部分重叠，需人工复核")
        confidence = min(confidence, 0.60)
        status = "needs_review"
    else:  # both empty
        score += 8
        reasons.append("型号为空，依赖其他字段消歧")
        confidence = min(confidence, 0.55)
        status = "needs_review"
    if same_table_name_variant:
        status = "needs_review"

    left_pos, right_pos = _is_placeholder(cert.position), _is_placeholder(draft.position)
    if not left_pos and not right_pos and _key_norm(cert.position) == _key_norm(draft.position):
        score += 16
        reasons.append("位号相同")
    elif left_pos or right_pos:
        score += 4
        reasons.append("位号为空或占位")
    else:
        score -= 3
        reasons.append("位号不同，保留为字段差异")
    if _key_norm(_value(cert.row, "规格材料")) == _key_norm(_value(draft.row, "规格材料")):
        score += 5
        reasons.append("规格用于消歧一致")
    if _key_norm(_value(cert.row, "证书号")) == _key_norm(_value(draft.row, "证书号")):
        score += 3
        reasons.append("证书号用于消歧一致")
    return score, min(confidence, 1.0), "；".join(reasons), status


def _match_rows(
    cert_rows: list[DocumentRow], draft_rows: list[DocumentRow], *,
    allow_same_table_name_variant: bool = False,
) -> tuple[list[tuple[DocumentRow, DocumentRow, float, str, str]], list[DocumentRow], list[DocumentRow]]:
    cert_profiles = [_profile(index, row) for index, row in enumerate(cert_rows)]
    draft_profiles = [_profile(index, row) for index, row in enumerate(draft_rows)]
    by_name: dict[str, list[_Profile]] = defaultdict(list)
    by_model: dict[frozenset[str], list[_Profile]] = defaultdict(list)
    for profile in draft_profiles:
        by_name[profile.name].append(profile)
        model_key = frozenset(_model_identity_tokens(profile.model))
        if model_key:
            by_model[model_key].append(profile)

    edges: list[tuple[int, float, str, str, int, int]] = []
    for cert in cert_profiles:
        candidate_profiles = list(by_name.get(cert.name, []))
        model_key = frozenset(_model_identity_tokens(cert.model))
        if model_key:
            candidate_profiles.extend(by_model.get(model_key, []))
        # 名称前缀只作为候选，不跨分组/语义块自动泛配。
        if cert.name:
            candidate_profiles.extend(
                draft for draft in draft_profiles
                if draft.name != cert.name and _name_relation(cert.name, draft.name) == "prefix"
            )
        seen: set[int] = set()
        for draft in candidate_profiles:
            if draft.index in seen:
                continue
            seen.add(draft.index)
            candidate = _candidate(
                cert, draft,
                allow_same_table_name_variant=allow_same_table_name_variant,
            )
            if candidate is None:
                continue
            score, confidence, reason, status = candidate
            edges.append((score, confidence, reason, status, cert.index, draft.index))

    # 全局按候选质量消费，避免同名重复行只按输入顺序贪心错配。
    edges.sort(key=lambda item: (-item[0], item[4], item[5]))
    used_cert: set[int] = set()
    used_draft: set[int] = set()
    matched: list[tuple[DocumentRow, DocumentRow, float, str, str]] = []
    for _score, confidence, reason, status, cert_index, draft_index in edges:
        if cert_index in used_cert or draft_index in used_draft:
            continue
        used_cert.add(cert_index)
        used_draft.add(draft_index)
        matched.append((cert_rows[cert_index], draft_rows[draft_index], confidence, reason, status))
    matched.sort(key=lambda item: item[0].row_idx)
    return (
        matched,
        [row for index, row in enumerate(cert_rows) if index not in used_cert],
        [row for index, row in enumerate(draft_rows) if index not in used_draft],
    )


def _header_signature(block: LocatedBlock) -> tuple[set[str], tuple[str, ...]]:
    fields = tuple(
        canonical_header(header) or _key_norm(header)
        for header in block.header
        if canonical_header(header) or _key_norm(header)
    )
    return set(fields), fields


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _table_features(block: LocatedBlock) -> tuple[set[str], set[str], set[str]]:
    group_tokens: set[str] = set()
    names: set[str] = set()
    models: set[str] = set()
    for row in block.rows:
        _group_name, tokens = _group_info(row.group)
        group_tokens.update(tokens)
        name = _key_norm(_value(row, "关键件名称"))
        if name:
            names.add(name)
        models.update(_model_tokens(_value(row, "型号")))
    return group_tokens, names, models


def _table_candidate(cert_block: LocatedBlock, draft_block: LocatedBlock) -> tuple[float, str]:
    """计算物理表候选分数；只用于选表，不改变字段比较规则。"""
    cert_headers, cert_sequence = _header_signature(cert_block)
    draft_headers, draft_sequence = _header_signature(draft_block)
    header_score = _jaccard(cert_headers, draft_headers)
    if cert_sequence and draft_sequence:
        sequence_score = sum(
            1 for left, right in zip(cert_sequence, draft_sequence) if left == right
        ) / max(len(cert_sequence), len(draft_sequence))
        header_score = 0.7 * header_score + 0.3 * sequence_score
    cert_groups, cert_names, cert_models = _table_features(cert_block)
    draft_groups, draft_names, draft_models = _table_features(draft_block)
    group_score = _jaccard(cert_groups, draft_groups)
    name_score = _jaccard(cert_names, draft_names)
    model_score = _jaccard(cert_models, draft_models)
    cert_count, draft_count = len(cert_block.rows), len(draft_block.rows)
    count_score = min(cert_count, draft_count) / max(cert_count, draft_count) if max(cert_count, draft_count) else 1.0
    score = (
        0.50 * header_score
        + 0.18 * group_score
        + 0.17 * name_score
        + 0.05 * model_score
        + 0.10 * count_score
    )
    reason = (
        f"表头={header_score:.2f}；分组={group_score:.2f}；名称={name_score:.2f}；"
        f"型号={model_score:.2f}；行数={count_score:.2f}"
    )
    return score, reason


def _table_pair_reason(cert_block: LocatedBlock, draft_block: LocatedBlock, score: float, detail: str) -> str:
    return (
        f"表级匹配 CERT表{cert_block.table_idx}→DRAFT表{draft_block.table_idx} "
        f"（得分={score:.2f}；{detail}）"
    )


def _row_payload(row: DocumentRow | None) -> dict[str, str]:
    """返回前端展示用的完整行值，不改变任何字段比较规则。"""
    if row is None:
        return {}
    payload = {
        str(key): str(value or "")
        for key, value in row.values.items()
        if not key.endswith("__2")
    }
    if row.group and "分组" not in payload:
        payload["分组"] = row.group
    return payload


def _row_ref(row: DocumentRow | None) -> dict[str, str | int]:
    if row is None:
        return {}
    return {
        "block_type": row.block_type,
        "table_idx": row.source_table,
        "row_idx": row.row_idx,
    }


def _block_ref(block: LocatedBlock) -> dict[str, str | int]:
    return {
        "block_type": block.block_type,
        "table_idx": block.table_idx,
    }


def _row_key(
    block_type: str, cert_row: DocumentRow | None = None,
    draft_row: DocumentRow | None = None, *, row_kind: str = "row",
    cert_ref: dict[str, object] | None = None,
    draft_ref: dict[str, object] | None = None,
) -> str:
    """根据物理位置生成稳定的行级 key，不依赖展示文本或字段归一化。"""
    references = {
        "block_type": block_type,
        "row_kind": row_kind,
        "cert": cert_ref if cert_ref is not None else _row_ref(cert_row),
        "draft": draft_ref if draft_ref is not None else _row_ref(draft_row),
    }
    source = json.dumps(references, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"row-{hashlib.sha1(source.encode('utf-8')).hexdigest()[:16]}"


def _display_row(row: DocumentRow) -> str:
    return json.dumps(_row_payload(row), ensure_ascii=False, separators=(",", ":"))


def _key(block_type: str, item: str, field: str, cert: str, draft: str) -> str:
    source = "|".join((block_type, item, field, cert, draft))
    digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:12]
    return f"verify-{digest}"


def _bind_diff_keys(row_diffs: list[RowDiff], diffs: list[VerifyDiff]) -> None:
    keys_by_row: dict[str, list[str]] = defaultdict(list)
    for diff in diffs:
        if diff.row_key:
            keys_by_row[diff.row_key].append(diff.key)
    for row_diff in row_diffs:
        row_diff.diff_keys = keys_by_row.get(row_diff.row_key, [])


def _new_diff(
    *, block_type: str, item_name: str, diff_type: str, field: str,
    cert_value: str = "", draft_value: str = "", cert_location: str = "",
    draft_anchor: Anchor | None = None, rule_version: str,
    match_confidence: float = 1.0, match_reason: str = "", match_status: str = "matched",
    row_key: str = "",
) -> VerifyDiff:
    return VerifyDiff(
        key=_key(block_type, item_name, field, cert_value, draft_value),
        block_type=block_type,
        item_name=item_name,
        diff_type=diff_type,
        field=field,
        cert_value=cert_value,
        draft_value=draft_value,
        cert_location=cert_location,
        draft_anchor=draft_anchor,
        rule_version=rule_version,
        match_confidence=match_confidence,
        match_reason=match_reason,
        match_status=match_status,
        row_key=row_key,
    )


def _list_diffs_for_match(
    matched: list[tuple[DocumentRow, DocumentRow, float, str, str]],
    missing_rows: list[DocumentRow], extra_rows: list[DocumentRow],
    block_type: str, rules: dict, *, table_reason: str = "",
    row_diffs: list[RowDiff] | None = None,
) -> list[VerifyDiff]:
    diffs: list[VerifyDiff] = []
    rule_version = rules.get("version", "strict-v1")
    for cert_row, draft_row, confidence, reason, status in matched:
        item_name = _value(cert_row, "关键件名称") or _value(draft_row, "关键件名称")
        combined_reason = "；".join(x for x in (table_reason, reason) if x)
        current_row_key = _row_key(block_type, cert_row, draft_row)
        changed_fields: list[str] = []
        for field in LIST_FIELDS:
            cert_value = _value(cert_row, field)
            draft_value = _value(draft_row, field)
            if not same_value(cert_value, draft_value, rules):
                changed_fields.append(field)
                diffs.append(_new_diff(
                    block_type=block_type, item_name=item_name,
                    diff_type="field_mismatch", field=field,
                    cert_value=cert_value, draft_value=draft_value,
                    cert_location=f"表{cert_row.source_table}第{cert_row.row_idx}行",
                    draft_anchor=_anchor(draft_row, field), rule_version=rule_version,
                    match_confidence=confidence, match_reason=combined_reason,
                    match_status=status, row_key=current_row_key,
                ))
        if row_diffs is not None:
            row_diffs.append(RowDiff(
                row_key=current_row_key,
                block_type=block_type,
                row_status="CHANGED" if changed_fields else "SAME",
                item_name=item_name,
                cert_row=_row_payload(cert_row),
                draft_row=_row_payload(draft_row),
                cert_row_ref=_row_ref(cert_row),
                draft_row_ref=_row_ref(draft_row),
                changed_fields=changed_fields,
                match_confidence=confidence,
                match_reason=combined_reason,
                match_status=status,
            ))
    for cert_row in missing_rows:
        item_name = _value(cert_row, "关键件名称") or "（名称为空，需人工确认）"
        current_row_key = _row_key(block_type, cert_row, None)
        diffs.append(_new_diff(
            block_type=block_type, item_name=item_name,
            diff_type="missing_in_draft", field="整行",
            cert_value=_display_row(cert_row),
            cert_location=f"表{cert_row.source_table}第{cert_row.row_idx}行",
            rule_version=rule_version, match_reason=table_reason,
            match_status="unmatched", row_key=current_row_key,
        ))
        if row_diffs is not None:
            row_diffs.append(RowDiff(
                row_key=current_row_key,
                block_type=block_type,
                row_status="ONLY_CERT",
                item_name=item_name,
                cert_row=_row_payload(cert_row),
                cert_row_ref=_row_ref(cert_row),
                changed_fields=["整行"],
                match_confidence=0.0,
                match_reason=table_reason or "CERT 行在 DRAFT 中未找到对应行",
                match_status="unmatched",
            ))
    for draft_row in extra_rows:
        item_name = _value(draft_row, "关键件名称") or "（名称为空，需人工确认）"
        current_row_key = _row_key(block_type, None, draft_row)
        diffs.append(_new_diff(
            block_type=block_type, item_name=item_name,
            diff_type="extra_in_draft", field="整行",
            draft_value=_display_row(draft_row),
            draft_anchor=_anchor(draft_row, "关键件名称"),
            cert_location="认证资料中未找到对应行",
            rule_version=rule_version, match_reason=table_reason,
            match_status="unmatched", row_key=current_row_key,
        ))
        if row_diffs is not None:
            row_diffs.append(RowDiff(
                row_key=current_row_key,
                block_type=block_type,
                row_status="ONLY_DRAFT",
                item_name=item_name,
                draft_row=_row_payload(draft_row),
                draft_row_ref=_row_ref(draft_row),
                changed_fields=["整行"],
                match_confidence=0.0,
                match_reason=table_reason or "DRAFT 行在 CERT 中未找到对应行",
                match_status="unmatched",
            ))
    return diffs


def _list_diffs(
    cert_rows: list[DocumentRow], draft_rows: list[DocumentRow],
    block_type: str, rules: dict, *, row_diffs: list[RowDiff] | None = None,
) -> list[VerifyDiff]:
    matched, missing_rows, extra_rows = _match_rows(cert_rows, draft_rows)
    return _list_diffs_for_match(
        matched, missing_rows, extra_rows, block_type, rules,
        row_diffs=row_diffs,
    )


def _table_presence_diff(
    block_type: str, block: LocatedBlock, rules: dict, *, missing_in_draft: bool,
    row_diffs: list[RowDiff] | None = None,
) -> VerifyDiff:
    if missing_in_draft:
        diff_type = "table_missing_in_draft"
        cert_value = f"CERT 表{block.table_idx}：{len(block.rows)} 行"
        draft_value = "DRAFT 未找到对应物理表"
        reason = "表级匹配未找到候选，未将整张 CERT 表展开成逐行漏项"
        row_key = _row_key(
            block_type, row_kind="block", cert_ref=_block_ref(block),
        )
        cert_row = {"__summary__": cert_value}
        draft_row: dict[str, str] = {"__summary__": draft_value}
        cert_ref, draft_ref = _block_ref(block), {}
        row_status = "ONLY_CERT"
    else:
        diff_type = "table_extra_in_draft"
        cert_value = "CERT 未找到对应物理表"
        draft_value = f"DRAFT 表{block.table_idx}：{len(block.rows)} 行"
        reason = "表级匹配未找到候选，需确认是否为 DRAFT 模板差异"
        row_key = _row_key(
            block_type, row_kind="block", draft_ref=_block_ref(block),
        )
        cert_row = {"__summary__": cert_value}
        draft_row = {"__summary__": draft_value}
        cert_ref, draft_ref = {}, _block_ref(block)
        row_status = "ONLY_DRAFT"
    diff = _new_diff(
        block_type=block_type, item_name=f"表{block.table_idx}（物理表）",
        diff_type=diff_type, field="整表", cert_value=cert_value,
        draft_value=draft_value,
        cert_location=f"表{block.table_idx}" if missing_in_draft else "认证资料中未找到对应物理表",
        draft_anchor=_anchor(block.rows[0], "关键件名称") if block.rows and not missing_in_draft else None,
        rule_version=rules.get("version", "strict-v1"), match_confidence=0.2,
        match_reason=reason, match_status="needs_review", row_key=row_key,
    )
    if row_diffs is not None:
        row_diffs.append(RowDiff(
            row_key=row_key,
            block_type=block_type,
            row_status=row_status,
            row_kind="block",
            item_name=f"表{block.table_idx}（物理表）",
            cert_row=cert_row,
            draft_row=draft_row,
            cert_row_ref=cert_ref,
            draft_row_ref=draft_ref,
            changed_fields=["整表"],
            match_confidence=0.2,
            match_reason=reason,
            match_status="needs_review",
        ))
    return diff


def _list_block_diffs(
    cert_blocks: list[LocatedBlock], draft_blocks: list[LocatedBlock],
    block_type: str, rules: dict, *, row_diffs: list[RowDiff] | None = None,
) -> list[VerifyDiff]:
    """先匹配物理表，再在表对内匹配行；DRAFT 表可承接多个 CERT 分表。"""
    diffs: list[VerifyDiff] = []
    consumed_draft_rows: set[int] = set()
    assigned_draft_blocks: set[int] = set()
    one_to_one_tables = len(cert_blocks) <= len(draft_blocks)

    for cert_block in sorted(cert_blocks, key=lambda block: block.table_idx):
        candidates: list[tuple[float, str, LocatedBlock]] = []
        for draft_block in draft_blocks:
            if one_to_one_tables and id(draft_block) in assigned_draft_blocks:
                continue
            score, detail = _table_candidate(cert_block, draft_block)
            candidates.append((score, detail, draft_block))
        if not candidates:
            diffs.append(_table_presence_diff(
                block_type, cert_block, rules, missing_in_draft=True,
                row_diffs=row_diffs,
            ))
            continue
        score, detail, draft_block = max(
            candidates, key=lambda item: (item[0], -item[2].table_idx)
        )
        cert_header_fields, _ = _header_signature(cert_block)
        draft_header_fields, _ = _header_signature(draft_block)
        minimum_score = 0.25 if cert_header_fields and draft_header_fields else 0.10
        if score < minimum_score:
            diffs.append(_table_presence_diff(
                block_type, cert_block, rules, missing_in_draft=True,
                row_diffs=row_diffs,
            ))
            continue
        assigned_draft_blocks.add(id(draft_block))
        table_reason = _table_pair_reason(cert_block, draft_block, score, detail)
        available_draft_rows = [
            row for row in draft_block.rows if id(row) not in consumed_draft_rows
        ]
        matched, missing_rows, _unused_extra_rows = _match_rows(
            cert_block.rows, available_draft_rows,
            allow_same_table_name_variant=True,
        )
        consumed_draft_rows.update(id(draft_row) for _, draft_row, *_ in matched)
        diffs.extend(_list_diffs_for_match(
            matched, missing_rows, [], block_type, rules,
            table_reason=table_reason, row_diffs=row_diffs,
        ))

    for draft_block in draft_blocks:
        residual_rows = [
            row for row in draft_block.rows if id(row) not in consumed_draft_rows
        ]
        if id(draft_block) not in assigned_draft_blocks:
            diffs.append(_table_presence_diff(
                block_type, draft_block, rules, missing_in_draft=False,
                row_diffs=row_diffs,
            ))
        elif residual_rows:
            diffs.extend(_list_diffs_for_match(
                [], [], residual_rows, block_type, rules,
                table_reason=f"DRAFT表{draft_block.table_idx}已参与表级匹配，但仍有未消费行",
                row_diffs=row_diffs,
            ))
    return diffs


def _rows_by_identity(rows: list[DocumentRow], block_type: str) -> dict[str, list[DocumentRow]]:
    grouped: dict[str, list[DocumentRow]] = defaultdict(list)
    for row in rows:
        if block_type == "product_description":
            identity = f"product|{_key_norm(_value(row, '项目'))}"
        else:
            identity = f"change|{_key_norm(_value(row, '项目'))}"
        grouped[identity].append(row)
    return grouped


def _product_or_change_diffs(
    cert_rows: list[DocumentRow], draft_rows: list[DocumentRow],
    block_type: str, rules: dict, *, row_diffs: list[RowDiff] | None = None,
) -> list[VerifyDiff]:
    cert_map = _rows_by_identity(cert_rows, block_type)
    draft_map = _rows_by_identity(draft_rows, block_type)
    fields = CHANGE_FIELDS if block_type == "change_confirmation" else ["值"]
    diffs: list[VerifyDiff] = []
    for identity in sorted(set(cert_map) | set(draft_map)):
        cert_items, draft_items = cert_map.get(identity, []), draft_map.get(identity, [])
        for cert_row, draft_row in zip(cert_items, draft_items):
            item_name = _value(cert_row, "项目") or _value(draft_row, "项目") or identity
            current_row_key = _row_key(block_type, cert_row, draft_row)
            changed_fields: list[str] = []
            for field in fields:
                cert_value, draft_value = _value(cert_row, field), _value(draft_row, field)
                if not same_value(cert_value, draft_value, rules):
                    changed_fields.append(field)
                    diffs.append(_new_diff(
                        block_type=block_type, item_name=item_name,
                        diff_type="field_mismatch", field=field,
                        cert_value=cert_value, draft_value=draft_value,
                        cert_location=f"表{cert_row.source_table}第{cert_row.row_idx}行",
                        draft_anchor=_anchor(draft_row, field),
                        rule_version=rules.get("version", "strict-v1"),
                        row_key=current_row_key,
                    ))
            if row_diffs is not None:
                row_diffs.append(RowDiff(
                    row_key=current_row_key,
                    block_type=block_type,
                    row_status="CHANGED" if changed_fields else "SAME",
                    item_name=item_name,
                    cert_row=_row_payload(cert_row),
                    draft_row=_row_payload(draft_row),
                    cert_row_ref=_row_ref(cert_row),
                    draft_row_ref=_row_ref(draft_row),
                    changed_fields=changed_fields,
                    match_reason="按项目字段配对",
                ))
        for cert_row in cert_items[len(draft_items):]:
            item_name = _value(cert_row, "项目") or identity
            current_row_key = _row_key(block_type, cert_row, None)
            changed_fields: list[str] = []
            for field in fields:
                cert_value = _value(cert_row, field)
                if cert_value or field != "值":
                    changed_fields.append(field)
                    diffs.append(_new_diff(
                        block_type=block_type, item_name=item_name,
                        diff_type="missing_in_draft", field=field, cert_value=cert_value,
                        cert_location=f"表{cert_row.source_table}第{cert_row.row_idx}行",
                        rule_version=rules.get("version", "strict-v1"),
                        match_status="unmatched", row_key=current_row_key,
                    ))
            if row_diffs is not None:
                row_diffs.append(RowDiff(
                    row_key=current_row_key,
                    block_type=block_type,
                    row_status="ONLY_CERT",
                    item_name=item_name,
                    cert_row=_row_payload(cert_row),
                    cert_row_ref=_row_ref(cert_row),
                    changed_fields=changed_fields or ["整行"],
                    match_confidence=0.0,
                    match_reason="CERT 行在 DRAFT 中未找到对应项目",
                    match_status="unmatched",
                ))
        for draft_row in draft_items[len(cert_items):]:
            item_name = _value(draft_row, "项目") or identity
            current_row_key = _row_key(block_type, None, draft_row)
            diffs.append(_new_diff(
                block_type=block_type, item_name=item_name,
                diff_type="extra_in_draft", field="整行", draft_value=_display_row(draft_row),
                draft_anchor=_anchor(draft_row, "项目"), cert_location="认证资料中未找到对应字段",
                rule_version=rules.get("version", "strict-v1"), match_status="unmatched",
                row_key=current_row_key,
            ))
            if row_diffs is not None:
                row_diffs.append(RowDiff(
                    row_key=current_row_key,
                    block_type=block_type,
                    row_status="ONLY_DRAFT",
                    item_name=item_name,
                    draft_row=_row_payload(draft_row),
                    draft_row_ref=_row_ref(draft_row),
                    changed_fields=["整行"],
                    match_confidence=0.0,
                    match_reason="DRAFT 行在 CERT 中未找到对应项目",
                    match_status="unmatched",
                ))
    return diffs


def _block_presence_diff(
    *, block_type: str, cert_present: bool, draft_present: bool,
    cert_rows: list[DocumentRow], draft_rows: list[DocumentRow], rules: dict,
    row_diffs: list[RowDiff] | None = None,
) -> VerifyDiff:
    if cert_present and not draft_present:
        diff_type = "block_missing_in_draft"
        cert_value = f"CERT 已定位 {len(cert_rows)} 行"
        draft_value = "DRAFT 未识别到该子块"
        reason = "DRAFT 未包含该子块；未将 CERT 行逐条计为报告漏项，需人工确认是否适用"
        cert_ref = {
            "block_type": block_type,
            "row_count": len(cert_rows),
            "tables": sorted({row.source_table for row in cert_rows}),
        }
        draft_ref: dict[str, object] = {}
        row_status = "ONLY_CERT"
    else:
        diff_type = "block_extra_in_draft"
        cert_value = "CERT 未识别到该子块"
        draft_value = f"DRAFT 已定位 {len(draft_rows)} 行"
        reason = "DRAFT 包含 CERT 未定位的子块，需人工确认是否为模板差异"
        cert_ref = {}
        draft_ref = {
            "block_type": block_type,
            "row_count": len(draft_rows),
            "tables": sorted({row.source_table for row in draft_rows}),
        }
        row_status = "ONLY_DRAFT"
    row_key = _row_key(
        block_type, row_kind="block", cert_ref=cert_ref, draft_ref=draft_ref,
    )
    diff = _new_diff(
        block_type=block_type, item_name=f"{block_type}（子块）",
        diff_type=diff_type, field="子块", cert_value=cert_value,
        draft_value=draft_value, cert_location="子块级定位结果",
        rule_version=rules.get("version", "strict-v1"),
        match_confidence=0.3, match_reason=reason, match_status="needs_review",
        row_key=row_key,
    )
    if row_diffs is not None:
        row_diffs.append(RowDiff(
            row_key=row_key,
            block_type=block_type,
            row_status=row_status,
            row_kind="block",
            item_name=f"{block_type}（子块）",
            cert_row={"__summary__": cert_value},
            draft_row={"__summary__": draft_value},
            cert_row_ref=cert_ref,
            draft_row_ref=draft_ref,
            changed_fields=["子块"],
            match_confidence=0.3,
            match_reason=reason,
            match_status="needs_review",
        ))
    return diff


def compare_blocks(
    cert_blocks: list[LocatedBlock], draft_blocks: list[LocatedBlock],
    rules: dict | None = None, *, row_diffs: list[RowDiff] | None = None,
) -> list[VerifyDiff]:
    """先做物理表级候选匹配，再在每个表对内做守恒的一对一行匹配。"""
    rules = load_rules() if rules is None else rules
    diffs: list[VerifyDiff] = []
    block_types = sorted({b.block_type for b in cert_blocks} | {b.block_type for b in draft_blocks})
    for block_type in block_types:
        cert_type_blocks = [block for block in cert_blocks if block.block_type == block_type]
        draft_type_blocks = [block for block in draft_blocks if block.block_type == block_type]
        if block_type in {"safety_list", "emc_list"}:
            diffs.extend(_list_block_diffs(
                cert_type_blocks, draft_type_blocks, block_type, rules,
                row_diffs=row_diffs,
            ))
        else:
            cert_rows = [row for block in cert_type_blocks for row in block.rows]
            draft_rows = [row for block in draft_type_blocks for row in block.rows]
            cert_present = bool(cert_type_blocks)
            draft_present = bool(draft_type_blocks)
            if cert_present != draft_present:
                # 变更确认/产品描述是否属于当前 DRAFT 模板不能从缺失本身推断。
                # 只产出子块级待确认证据，避免把整个 CERT 子块机械扩大为逐行漏项。
                diffs.append(_block_presence_diff(
                    block_type=block_type, cert_present=cert_present,
                    draft_present=draft_present, cert_rows=cert_rows,
                    draft_rows=draft_rows, rules=rules, row_diffs=row_diffs,
                ))
            else:
                diffs.extend(_product_or_change_diffs(
                    cert_rows, draft_rows, block_type, rules, row_diffs=row_diffs,
                ))
    seen: dict[str, int] = {}
    for diff in diffs:
        count = seen.get(diff.key, 0)
        seen[diff.key] = count + 1
        if count:
            diff.key = f"{diff.key}-{count + 1}"
    if row_diffs is not None:
        _bind_diff_keys(row_diffs, diffs)
    return diffs
