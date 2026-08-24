"""长期记忆：用户决策落盘 JSONL + 指纹聚合读回 + 反哺建议。

闭环设计（本次完善）：
  写：record_decisions() 记录每条决策，附"指纹"(件名+型号+diff类型)、拒绝理由、变更字段。
  读：recall(context) 按指纹聚合历史 accept/reject，给出 MemoryHint 供 suggest 反哺。
  炼：mine_aliases()（同一件别名）、mine_reject_rules()（高频被否模式）供人工复核/沉淀规则。

设计原则：
  - 只写不读 → 现在读回，历史被反复否决的差异自动预置 ignore / 降置信度。
  - 记忆是"建议"不是"强制"：仍由人工在确认页决策，记忆只改动作/理由/置信度。
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from typing import Optional

from ..config import config
from ..differ.normalize import normalize
from ..models import MemoryHint

# 视为"强信号"的最小样本数（可由 config 覆盖）
_MIN_STRONG = getattr(config, "MEMORY_STRONG_MIN", 2)


# ---------------------------------------------------------------------------
# 指纹：把一条差异的"身份"压成稳定 key，供跨任务聚合。
# 身份 = diff类型 + 归一化(关键件名称) + 归一化(型号)。
# 不含证书号等易变字段，保证同一个件在不同任务里指纹一致。
# ---------------------------------------------------------------------------
def signature(context: dict) -> str:
    name = normalize(context.get("关键件名称", "") or "")
    model = normalize(context.get("型号", "") or "")
    dtype = context.get("diff类型", "") or context.get("type", "")
    dtype = getattr(dtype, "value", dtype)   # 枚举→值(如 "changed")，避免 "DiffType.CHANGED"
    return f"{dtype}|{name}|{model}"


def _context_of(diff: dict) -> dict:
    """从 diff.model_dump() 提炼记忆上下文（件名/型号取 plm 优先，回退 orig）。"""
    row = diff.get("plm") or diff.get("orig") or {}
    ctx = {
        "关键件名称": row.get("关键件名称", ""),
        "型号": row.get("型号", ""),
        "diff类型": diff.get("type", ""),
        "changed_fields": diff.get("changed_fields", []),
    }
    if diff.get("pair_reason"):
        orig, plm = diff.get("orig") or {}, diff.get("plm") or {}
        ctx["pair"] = {
            "orig_name": orig.get("关键件名称", ""),
            "plm_name": plm.get("关键件名称", ""),
            "confidence": diff.get("pair_confidence", 0),
            "reason": diff.get("pair_reason", ""),
        }
    return ctx


# ---------------------------------------------------------------------------
# 写：记录决策
# ---------------------------------------------------------------------------
def record_decisions(
    diffs_by_key: dict,
    decisions: dict[str, str],
    reasons: Optional[dict[str, str]] = None,
) -> None:
    """把本次人工决策追加到反馈文件。

    diffs_by_key: {diff_key: diff.model_dump()}
    decisions:    {diff_key: "accept"|"reject"|...}
    reasons:      {diff_key: "拒绝/接受理由"}（可选，拒绝策略完善点）
    """
    reasons = reasons or {}
    config.FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with config.FEEDBACK_FILE.open("a", encoding="utf-8") as f:
        for key, verdict in decisions.items():
            diff = diffs_by_key.get(key)
            ctx = _context_of(diff) if diff is not None else {}
            rec = {
                "ts": datetime.now().isoformat(timespec="seconds"),
                "key": key,
                "verdict": verdict,
                "reason": reasons.get(key, ""),
                "sig": signature(ctx) if ctx else "",
                "context": ctx,
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# 读：加载 + 按指纹聚合
# ---------------------------------------------------------------------------
def _iter_records():
    if not config.FEEDBACK_FILE.exists():
        return
    for line in config.FEEDBACK_FILE.read_text(encoding="utf-8").splitlines():
        try:
            yield json.loads(line)
        except Exception:  # noqa: BLE001
            continue


def _aggregate() -> dict[str, dict]:
    """按指纹聚合历史决策：{sig: {accepts, rejects, last_verdict, last_reason, reasons[]}}。"""
    agg: dict[str, dict] = defaultdict(
        lambda: {"accepts": 0, "rejects": 0, "last_verdict": "", "last_reason": "", "reasons": []}
    )
    for rec in _iter_records():
        sig = rec.get("sig") or (signature(rec.get("context", {})) if rec.get("context") else "")
        if not sig:
            continue
        verdict = rec.get("verdict", "")
        a = agg[sig]
        if verdict == "accept":
            a["accepts"] += 1
        elif verdict in ("reject", "unpair"):
            a["rejects"] += 1
        a["last_verdict"] = verdict
        if rec.get("reason"):
            a["last_reason"] = rec["reason"]
            a["reasons"].append(rec["reason"])
    return agg


def build_hints(diffs: list) -> dict[str, MemoryHint]:
    """为一批 diff 预构建记忆提示：{diff_key: MemoryHint}。

    一次性加载聚合，按每个 diff 的指纹匹配，避免逐条重复读文件。
    diffs: DiffItem 列表（有 .key/.type/.plm/.orig/.changed_fields）。
    """
    agg = _aggregate()
    if not agg:
        return {}
    hints: dict[str, MemoryHint] = {}
    for d in diffs:
        ctx = _context_of(d.model_dump()) if hasattr(d, "model_dump") else _context_of(d)
        sig = signature(ctx)
        stat = agg.get(sig)
        if not stat:
            continue
        hints[d.key] = _to_hint(sig, stat)
    return hints


def recall(context: dict) -> Optional[MemoryHint]:
    """单条上下文的记忆读回（供离线/单点查询）。"""
    sig = signature(context)
    stat = _aggregate().get(sig)
    return _to_hint(sig, stat) if stat else None


def _to_hint(sig: str, stat: dict) -> MemoryHint:
    accepts, rejects = stat["accepts"], stat["rejects"]
    total = accepts + rejects
    dominant = ""
    if total:
        if rejects >= _MIN_STRONG and rejects > accepts:
            dominant = "reject"
        elif accepts >= _MIN_STRONG and accepts > rejects:
            dominant = "accept"
    return MemoryHint(
        signature=sig, accepts=accepts, rejects=rejects, total=total,
        dominant=dominant, last_verdict=stat.get("last_verdict", ""),
        last_reason=stat.get("last_reason", ""),
    )


# ---------------------------------------------------------------------------
# 炼：可供人工复核 / 沉淀规则
# ---------------------------------------------------------------------------
def mine_aliases(min_accepts: int = 1) -> list[dict]:
    """从反馈里挖掘"被人工确认为同一件"的名称别名对。accepts>=min 且 accepts>rejects。"""
    stat: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for rec in _iter_records():
        pair = rec.get("context", {}).get("pair")
        if not pair:
            continue
        k = (pair.get("orig_name", ""), pair.get("plm_name", ""))
        if not k[0] or not k[1]:
            continue
        if rec.get("verdict") == "accept":
            stat[k][0] += 1
        elif rec.get("verdict") in ("unpair", "reject"):
            stat[k][1] += 1
    out = []
    for (on, pn), (acc, rej) in stat.items():
        if acc >= min_accepts and acc > rej:
            out.append({"orig_name": on, "plm_name": pn, "accepts": acc, "rejects": rej})
    return out


def mine_reject_rules(min_rejects: int = 2) -> list[dict]:
    """挖掘"高频被否"的差异模式，供人工复核后沉淀为反向规则/预置忽略。

    返回按 rejects 降序：[{sig, 关键件名称, 型号, diff类型, changed_fields, rejects, accepts, reasons}]。
    仅返回 rejects>=min_rejects 且 rejects>accepts 的模式（明确倾向被否）。
    """
    # 指纹 → 统计 + 代表性上下文
    stat: dict[str, dict] = defaultdict(
        lambda: {"rejects": 0, "accepts": 0, "reasons": [], "ctx": {}}
    )
    for rec in _iter_records():
        sig = rec.get("sig") or (signature(rec.get("context", {})) if rec.get("context") else "")
        if not sig:
            continue
        s = stat[sig]
        v = rec.get("verdict", "")
        if v == "accept":
            s["accepts"] += 1
        elif v in ("reject", "unpair"):
            s["rejects"] += 1
        if rec.get("reason"):
            s["reasons"].append(rec["reason"])
        if not s["ctx"] and rec.get("context"):
            s["ctx"] = rec["context"]
    out = []
    for sig, s in stat.items():
        if s["rejects"] >= min_rejects and s["rejects"] > s["accepts"]:
            ctx = s["ctx"]
            out.append({
                "sig": sig,
                "关键件名称": ctx.get("关键件名称", ""),
                "型号": ctx.get("型号", ""),
                "diff类型": ctx.get("diff类型", ""),
                "changed_fields": ctx.get("changed_fields", []),
                "rejects": s["rejects"],
                "accepts": s["accepts"],
                "reasons": s["reasons"][-5:],
            })
    out.sort(key=lambda x: x["rejects"], reverse=True)
    return out


def search_similar(context: dict, limit: int = 3) -> list[dict]:
    """按指纹检索历史决策（升级：指纹匹配，回退件名匹配）。"""
    sig = signature(context)
    name = context.get("关键件名称", "")
    hits: list[dict] = []
    for rec in _iter_records():
        rec_sig = rec.get("sig") or (signature(rec.get("context", {})) if rec.get("context") else "")
        if (sig and rec_sig == sig) or (name and rec.get("context", {}).get("关键件名称") == name):
            hits.append(rec)
    return hits[-limit:]
