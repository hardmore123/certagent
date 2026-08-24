"""对齐 + 差异分类 + 置信度。核心确定性（默认不调用 LLM）。

匹配策略（分趟）：
1. Rich key（行级唯一键）：table + group + 关键件名称 + 型号 + 位号 + 规格材料 + 证书号
   → 命中后仍复核 _VERIFY_FIELDS：无差异 SAME、有差异 CHANGED
2. Loose key（宽松键）：table + group + 关键件名称 + 型号（整格全等）→ CHANGED
2.5 型号集合匹配（确定性，可配开关）：约束同 loose，仅把型号判据从"整格全等"放宽为
   "集合关系"——真子集(型号列表扩充/收窄) → CHANGED 并标注新增/移除的型号；
   部分重叠 → 默认仅标"待确认配对"交人工（语义待业务确认，不自动合并）。
   与书写顺序无关，可复现。
3.（可选）LLM fuzzy 候选提名：仅对前几趟后的残余候选池（未配对 orig × 未配对 plm）
   调用注入的 fuzzy_proposer，LLM 只"提名"疑似同一件的配对 + 置信度，不直接决策；
   置信度≥阈值才标为 CHANGED（待人工确认），仍走行级多重集消费，保证守恒。

设计原则：
- 以 PLM(变更后) 为基底逐行匹配，保留全部行（不丢行）
- 使用行级多重集（defaultdict(list) + used 集合），避免同键多行被覆盖
- 每个 DiffItem 对应"一行输出"，key 全局唯一
- fuzzy_proposer 依赖注入（默认 None）：diff_engine 本身不依赖 LLM，可复现·可测试
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Callable, Optional

from ..models import Confidence, DiffItem, DiffType, Row
from .normalize import normalize

# fuzzy 候选提名器签名：入参(未配对 orig 列表, 未配对 plm 列表)，
# 返回若干 (orig_index, plm_index, confidence, reason)。index 指向入参列表下标。
FuzzyProposer = Callable[[list[Row], list[Row]], list[tuple[int, int, float, str]]]

# 行级唯一键字段（尽量区分每一物理行）。
# group 是关键件身份的一部分：不同机内电源单元分组下的同名同型号
# 器件不能跨组匹配；位号/规格/证书号继续区分同组内的多条物理行。
_RICH_FIELDS = ["group", "关键件名称", "型号", "位号", "规格材料", "证书号"]
# 宽松键只用于判断同一分组下的内容变更，不用于跨组合并。
# 同组内同名同型号的重复行仍通过 list + used 逐条消费，不会被字典覆盖。
_LOOSE_FIELDS = ["group", "关键件名称", "型号"]

# rich 命中后的"内容复核"字段：涵盖 rich 键未包含的所有实质内容列
# （制造商/生产企业/认证标准/备注/本次使用），避免这些字段的变更被判为 SAME 静默吞掉。
_VERIFY_FIELDS = ["位号", "规格材料", "制造商", "生产企业", "认证标准",
                  "证书号", "备注", "本次使用"]

# 第 2.5 趟"型号集合匹配"的默认参数（可被 rules.model_set_match 覆盖）
_MS_DEFAULTS = {
    "enabled": True,
    "separators": "、,;；/／+＋\n\r",
    "min_token_len": 2,
    "accept_subset": True,
    "accept_overlap": False,
}


_PAREN = re.compile(r"[（(][^（()]*[)）]")


def _strip_notes(text: str) -> str:
    """剥离型号格里的括号说明文字。

    真实数据如：`HD850K8U61-TBLC*(*代表企业内部代码，由一个或多个空、字母、数字…)`
    括号内是说明而非型号；若不剥离，会被分隔符拆成"字母""数字"等伪型号 token，
    导致不同型号因共享同一段说明文字而产生虚假交集。
    剥离后为空则退回原文（防止整个型号被括号包裹的极端情形）。
    """
    if not text:
        return text
    stripped = _PAREN.sub(" ", text)
    # 可能有嵌套/未闭合括号，再扫一遍
    stripped = _PAREN.sub(" ", stripped)
    return stripped if stripped.strip() else text


def _split_models(text: str, separators: str, min_len: int) -> set[str]:
    """把型号格拆成型号集合（归一化后）。

    型号列常一格罗列多个可选型号（如 "PC/ABS-5140、PC/ABS-5143"）。
    两个要点：
    - 先剥离括号说明文字（见 `_strip_notes`），避免说明被拆成伪型号
    - 分隔符里含 '/'，但部分型号本身带 '/'（如 PC/ABS-5140），
      故只按**非 '/' 分隔符**切分，避免把 "PC/ABS-5140" 误拆成 {pc, abs-5140}
    """
    t = normalize(_strip_notes(text or ""))
    if not t:
        return set()
    primary = "".join(ch for ch in separators if ch not in "/／")
    for ch in primary:
        t = t.replace(ch, "\x00")
    tokens = [x.strip() for x in t.split("\x00")]
    tokens = [x for x in tokens if x and x != "/" and len(x) >= min_len]
    return set(tokens)


def _model_set_relation(a_models: set[str], b_models: set[str]) -> str:
    """返回集合关系：equal / subset(真子集,含超集) / overlap(部分重叠) / disjoint(无交集)。"""
    if not a_models or not b_models:
        return "disjoint"
    if a_models == b_models:
        return "equal"
    if a_models < b_models or b_models < a_models:
        return "subset"
    if a_models & b_models:
        return "overlap"
    return "disjoint"


def _model_set_desc(a_models: set[str], b_models: set[str]) -> str:
    """人类可读的集合差异说明，写入 changed_fields。"""
    added = sorted(b_models - a_models)
    removed = sorted(a_models - b_models)
    parts = []
    if added:
        parts.append("新增 " + "、".join(added[:5]) + ("…" if len(added) > 5 else ""))
    if removed:
        parts.append("移除 " + "、".join(removed[:5]) + ("…" if len(removed) > 5 else ""))
    return "(型号集合：" + "；".join(parts) + ")" if parts else "(型号集合变化)"


def _key(row: Row, fields: list[str]) -> str:
    # 含 table，避免表1/表2 跨表误匹配
    return f"t{row.table}|" + "|".join(normalize(getattr(row, f, "")) for f in fields)


def _compare_fields(a: Row, b: Row, fields: list[str]) -> list[str]:
    return [f for f in fields if normalize(getattr(a, f, "")) != normalize(getattr(b, f, ""))]


def _name_is_prefix(a_name: str, b_name: str) -> bool:
    """判断 a 和 b 的关键件名称是否有前缀关系（且不完全相同）。

    条件：
    - 两者 normalize 后不相同（相同的应该已被 loose key 处理）
    - 短名 >= 3 字符
    - 短名是长名的前缀
    """
    na = normalize(a_name)
    nb = normalize(b_name)
    if not na or not nb or len(na) < 3 or len(nb) < 3:
        return False
    if na == nb:
        return False
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    return longer.startswith(shorter)


def _fuzzy_name_compatible(p: Row, o: Row) -> bool:
    """第三级 fuzzy name 匹配的全部约束。

    场景：orig 的"电线组件" HL-006L 应归入 PLM 的"电线组件(0.5平方毫米...)"组。
    约束：
    - 同表
    - group 完全相同（都为空 或 都有值且相同）—— 不允许跨组配对
    - 名称不同且有前缀关系
    """
    if p.table != o.table:
        return False
    pg = normalize(p.group, drop_space=False)
    og = normalize(o.group, drop_space=False)
    if pg != og:
        return False
    return _name_is_prefix(p.关键件名称, o.关键件名称)


def run_diff(rows_orig: list[Row], rows_plm: list[Row], rules: dict,
             fuzzy_proposer: Optional[FuzzyProposer] = None,
             fuzzy_threshold: float = 0.8) -> list[DiffItem]:
    """行级对齐两侧清单，产出与"输出行"一一对应的 diff 项（不丢行）。

    角色定义（2026-07-30 业务确认）：
    - rows_plm  = PLM 导出（85ZXSF 新品）= 新版本/变更后 → 遍历基底，输出骨架
    - rows_orig = 原始清单（人工整理）    = 旧版本/变更前 → 匹配池

    输出行数 = PLM 全部行 + 原始清单未消费行。PLM 的行保持原序（输出骨架，即新版本清单），
    原始清单独有行（旧版本保留项）按关键件组插入对应位置。

    DiffItem.orig 始终指向原始清单行，DiffItem.plm 始终指向 PLM 行（语义不变）。
    """
    compare_fields = rules.get("compare_fields", ["规格材料", "制造商", "生产企业", "认证标准", "证书号"])

    # 原始清单（旧版本）行池：按 rich / loose 键索引，用 used 记录已消费
    orig_rich: dict[str, list[Row]] = defaultdict(list)
    orig_loose: dict[str, list[Row]] = defaultdict(list)
    for r in rows_orig:
        orig_rich[_key(r, _RICH_FIELDS)].append(r)
        orig_loose[_key(r, _LOOSE_FIELDS)].append(r)
    used: set[int] = set()

    def take(pool: dict[str, list[Row]], k: str) -> Row | None:
        for r in pool.get(k, []):
            if id(r) not in used:
                used.add(id(r))
                return r
        return None

    # ===== 分趟匹配（避免贪心错配）=====
    # 以 PLM（新版本）为遍历基底。先让所有 PLM 行做 rich 精确匹配，再 loose，最后 fuzzy。
    # match_result[id(p)] = (dtype, orig_row, changed_fields) —— orig_row=None 表示未匹配
    match_result: dict[int, tuple[DiffType, Row | None, list[str]]] = {}

    # 第一趟：rich key 精确匹配。
    # 注意：rich 键不含 制造商/生产企业/认证标准/备注 等字段，命中后仍需逐字段复核——
    # 若这些字段有实质差异（如认证标准 2013→2024），必须升级为 CHANGED 交人工确认，
    # 不能当作"完全相同"自动保留（否则变更被静默吞掉）。
    for p in rows_plm:
        o = take(orig_rich, _key(p, _RICH_FIELDS))
        if o is not None:
            changed = _compare_fields(o, p, _VERIFY_FIELDS)
            if changed:
                match_result[id(p)] = (DiffType.CHANGED, o, changed)
            else:
                match_result[id(p)] = (DiffType.SAME, o, [])

    # 第二趟：loose key 宽松匹配（同名同型号但内容不同 → CHANGED）
    for p in rows_plm:
        if id(p) in match_result:
            continue
        o = take(orig_loose, _key(p, _LOOSE_FIELDS))
        if o is not None:
            changed = _compare_fields(o, p, compare_fields)
            match_result[id(p)] = (DiffType.CHANGED, o, changed or ["(整体)"])

    # pair_meta[id(p)] = (confidence, reason)，供后续 DiffItem 携带"待确认配对"信息。
    pair_meta: dict[int, tuple[float, str]] = {}

    # ===== 第 2.5 趟：型号集合匹配（确定性，无 LLM）=====
    # 场景：型号列一格罗列多个可选型号，新版本在旧版本基础上扩充/收窄。
    #   A="PC/ABS-5140"  B="PC/ABS-5140、PC/ABS-5143、PC/ABS-5144"
    # 整格字符串比较判为两侧各自独有；按集合关系则是"同一件、型号列表扩充"。
    # 约束与 loose 完全一致（同表 + 同组 + 同关键件名称），仅放宽型号判据。
    # 与书写顺序无关（集合），可复现。
    _ms = dict(_MS_DEFAULTS)
    _ms.update(rules.get("model_set_match") or {})
    if _ms.get("enabled"):
        seps = str(_ms.get("separators") or _MS_DEFAULTS["separators"])
        min_len = int(_ms.get("min_token_len") or 2)

        def _base_key(r: Row) -> tuple:
            """同表 + 同组 + 同关键件名称（型号除外）"""
            return (r.table, normalize(r.group, drop_space=False), normalize(r.关键件名称))

        # 残余 A 行按 base_key 分桶
        rest_orig: dict[tuple, list[Row]] = defaultdict(list)
        for o in rows_orig:
            if id(o) not in used:
                rest_orig[_base_key(o)].append(o)

        if rest_orig:
            for p in rows_plm:
                if id(p) in match_result:
                    continue
                bucket = rest_orig.get(_base_key(p))
                if not bucket:
                    continue
                p_models = _split_models(p.型号, seps, min_len)
                if not p_models:
                    continue
                # 在同桶内找关系最强的候选：subset 优先于 overlap
                best: tuple[int, Row, str] | None = None   # (优先级, 行, 关系)
                for o in bucket:
                    if id(o) in used:
                        continue
                    rel = _model_set_relation(_split_models(o.型号, seps, min_len), p_models)
                    if rel == "subset" and _ms.get("accept_subset"):
                        best = (2, o, rel)
                        break                      # subset 语义最明确，直接采用
                    if rel == "overlap" and best is None:
                        best = (1, o, rel)         # overlap 暂存，继续找更好的
                if best is None:
                    continue
                _prio, o, rel = best
                # overlap 语义待业务确认：默认不自动合并，仅标为"待确认配对"交人工
                if rel == "overlap" and not _ms.get("accept_overlap"):
                    o_models = _split_models(o.型号, seps, min_len)
                    used.add(id(o))
                    changed = _compare_fields(o, p, compare_fields)
                    match_result[id(p)] = (DiffType.CHANGED, o, changed or ["(整体)"])
                    inter = sorted(o_models & p_models)
                    pair_meta[id(p)] = (
                        0.6,
                        f"型号集合部分重叠（共有 {'、'.join(inter[:3])}，两侧各有独有），"
                        f"是否同一件需人工确认",
                    )
                    continue
                o_models = _split_models(o.型号, seps, min_len)
                used.add(id(o))
                changed = _compare_fields(o, p, compare_fields)
                changed = [_model_set_desc(o_models, p_models)] + changed
                match_result[id(p)] = (DiffType.CHANGED, o, changed)

    # 第三趟（可选）：LLM fuzzy 候选提名——仅对残余候选池，LLM 只提名不决策。
    if fuzzy_proposer is not None:
        unmatched_plm = [p for p in rows_plm if id(p) not in match_result]
        unmatched_orig = [o for o in rows_orig if id(o) not in used]
        if unmatched_plm and unmatched_orig:
            try:
                proposals = fuzzy_proposer(unmatched_orig, unmatched_plm) or []
            except Exception as e:  # noqa: BLE001 - 提名失败不影响主流程
                from ..trace import dump
                dump("fuzzy_proposer_error", {"error": str(e)})
                proposals = []
            for oi, pi, conf, reason in proposals:
                if not (0 <= oi < len(unmatched_orig) and 0 <= pi < len(unmatched_plm)):
                    continue
                if conf < fuzzy_threshold:
                    continue
                o = unmatched_orig[oi]
                p = unmatched_plm[pi]
                # 守恒护栏：任一侧已被消费则跳过；同表同组才接受（不允许跨表/跨组配对）
                if id(p) in match_result or id(o) in used:
                    continue
                if p.table != o.table:
                    continue
                if normalize(p.group, drop_space=False) != normalize(o.group, drop_space=False):
                    continue
                used.add(id(o))
                changed = _compare_fields(o, p, compare_fields)
                match_result[id(p)] = (DiffType.CHANGED, o, changed or ["(整体)"])
                pair_meta[id(p)] = (float(conf), str(reason))

    diffs: list[DiffItem] = []
    seq = 0

    def add(kind: str, dtype: DiffType, conf: Confidence, table: int,
            orig: Row | None = None, plm: Row | None = None, changed: list[str] | None = None,
            pair_conf: float = 0.0, pair_reason: str = ""):
        nonlocal seq
        seq += 1
        diffs.append(DiffItem(key=f"{kind}-{seq}", table=table, type=dtype, confidence=conf,
                              orig=orig, plm=plm, changed_fields=changed or [],
                              pair_confidence=pair_conf, pair_reason=pair_reason))

    # 按 PLM（新版本）原序生成 DiffItem（保持输出骨架）
    _conf = {DiffType.SAME: Confidence.HIGH, DiffType.CHANGED: Confidence.LOW}
    _kind = {DiffType.SAME: "same", DiffType.CHANGED: "changed"}
    for p in rows_plm:
        res = match_result.get(id(p))
        if res is None:
            # PLM 独有（新版本新增项）→ 标红
            add("only_plm", DiffType.ONLY_PLM, Confidence.MEDIUM, p.table, plm=p)
            continue
        dtype, o, changed = res
        pc, pr = pair_meta.get(id(p), (0.0, ""))
        # LLM 提名的配对在 changed_fields 前置一个标记，便于前端识别
        if pr and "(AI疑似同一件)" not in changed:
            changed = ["(AI疑似同一件)"] + changed
        add(_kind[dtype], dtype, _conf[dtype], p.table, orig=o, plm=p, changed=changed,
            pair_conf=pc, pair_reason=pr)

    # 原始清单（旧版本）中未被消费的行 = 旧版本独有（保留项）→ 追加，不标红
    for o in rows_orig:
        if id(o) not in used:
            add("only_orig", DiffType.ONLY_ORIG, Confidence.MEDIUM, o.table, orig=o)

    return diffs
