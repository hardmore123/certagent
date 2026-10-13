"""方案 1 原型：第三级"名称包含匹配"。

在 rich key / loose key 都未命中后，尝试 fuzzy name 匹配：
- 如果 PLM 行的关键件名称 **包含** orig 行的关键件名称（或反过来）
- 且同表
- 且 orig 的组为空 或 两者 group 相同
- 且名称长度差不超过 3 倍（防止 "Y电容" 匹配 "X电容Y组件" 这种误配）
→ 标为 CHANGED，置信度 VERY_LOW（实际用 LOW 标记 + changed_fields 加 "(名称变更)"）

只读实验：不改 diff_engine.py，复制一份逻辑加第三级，跑东芝样例对比。
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from compare_core.models import Confidence, DiffItem, DiffType, Row  # noqa: E402
from compare_core.differ.normalize import normalize  # noqa: E402
from compare_core.rules.loader import load_rules  # noqa: E402

ORIG_JSON = ROOT / "runs" / "merge_folder" / "orig.json"
PLM_JSON = ROOT / "runs" / "merge_folder" / "plm.json"
OUT_DIR = ROOT / "runs" / "prototype_fuzzy_name_2026-07-28"

_RICH_FIELDS = ["group", "关键件名称", "型号", "位号", "规格材料", "证书号"]
_LOOSE_FIELDS = ["group", "关键件名称", "型号"]


def _key(row: Row, fields: list[str]) -> str:
    return f"t{row.table}|" + "|".join(normalize(getattr(row, f, "")) for f in fields)


def _compare_fields(a: Row, b: Row, fields: list[str]) -> list[str]:
    return [f for f in fields if normalize(getattr(a, f, "")) != normalize(getattr(b, f, ""))]


def _name_contains(a_name: str, b_name: str) -> bool:
    """a 的关键件名称是否是 b 的前缀（且两者名称不完全相同）。
    
    只在名称不同时触发（名称相同的行应该已被 loose key 匹配，走到 fuzzy 说明是
    同名但跨组/已被消费的情况，不应在 fuzzy 层强行配对）。
    """
    na = normalize(a_name)
    nb = normalize(b_name)
    if not na or not nb or len(na) < 3 or len(nb) < 3:
        return False
    # 名称完全相同 → 不走 fuzzy（应该由 loose key 处理）
    if na == nb:
        return False
    # 前缀关系：短名是长名的前缀
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    return longer.startswith(shorter)


def _fuzzy_name_compatible(p: Row, o: Row) -> bool:
    """fuzzy name 匹配的全部条件（放宽版：不要求型号一致）。
    
    场景：orig 的"电线组件" HL-006L 应归入 PLM 的"电线组件(0.5平方毫米...)"组，
    虽然型号不同，但关键件名称有包含关系 → 判定为同组内的不同选型 → CHANGED。
    
    约束：
    - 同表
    - group 完全相同（都为空 或 都有值且相同）—— 不允许跨组配对
    - 名称不同且有前缀关系
    """
    if p.table != o.table:
        return False
    # group 必须完全相同（都为空 或 都有值且相同），不允许一方有 group 一方空
    pg = normalize(p.group, drop_space=False)
    og = normalize(o.group, drop_space=False)
    if pg != og:
        return False
    # 名称前缀关系（核心条件，名称完全相同的已被过滤）
    return _name_contains(p.关键件名称, o.关键件名称)


def run_diff_with_fuzzy(rows_orig: list[Row], rows_plm: list[Row], rules: dict) -> list[DiffItem]:
    """带第三级 fuzzy name 匹配的 diff（原型）。"""
    compare_fields = rules.get("compare_fields", ["规格材料", "制造商", "生产企业", "认证标准", "证书号"])

    orig_rich: dict[str, list[Row]] = defaultdict(list)
    orig_loose: dict[str, list[Row]] = defaultdict(list)
    for r in rows_orig:
        orig_rich[_key(r, _RICH_FIELDS)].append(r)
        orig_loose[_key(r, _LOOSE_FIELDS)].append(r)
    used: set[int] = set()

    # fuzzy name 池：按 table 索引，遍历时逐条检查名称包含
    orig_by_table: dict[int, list[Row]] = defaultdict(list)
    for r in rows_orig:
        orig_by_table[r.table].append(r)

    def take(pool: dict[str, list[Row]], k: str) -> Row | None:
        for r in pool.get(k, []):
            if id(r) not in used:
                used.add(id(r))
                return r
        return None

    def take_fuzzy(p: Row) -> Row | None:
        """第三级：从同 table 的 orig 行里找名称包含匹配。"""
        candidates = orig_by_table.get(p.table, [])
        for r in candidates:
            if id(r) not in used and _fuzzy_name_compatible(p, r):
                used.add(id(r))
                return r
        return None

    diffs: list[DiffItem] = []
    seq = 0
    fuzzy_hits: list[dict] = []

    def add(kind: str, dtype: DiffType, conf: Confidence, table: int,
            orig: Row | None = None, plm: Row | None = None, changed: list[str] | None = None):
        nonlocal seq
        seq += 1
        diffs.append(DiffItem(key=f"{kind}-{seq}", table=table, type=dtype, confidence=conf,
                              orig=orig, plm=plm, changed_fields=changed or []))

    for p in rows_plm:
        o = take(orig_rich, _key(p, _RICH_FIELDS))
        if o is not None:
            add("same", DiffType.SAME, Confidence.HIGH, p.table, orig=o, plm=p)
            continue
        o = take(orig_loose, _key(p, _LOOSE_FIELDS))
        if o is not None:
            changed = _compare_fields(o, p, compare_fields)
            add("changed", DiffType.CHANGED, Confidence.LOW, p.table, orig=o, plm=p,
                changed=changed or ["(整体)"])
            continue
        # 第三级：fuzzy name
        o = take_fuzzy(p)
        if o is not None:
            changed = _compare_fields(o, p, compare_fields)
            changed.insert(0, "(名称变更)")
            add("changed", DiffType.CHANGED, Confidence.LOW, p.table, orig=o, plm=p, changed=changed)
            fuzzy_hits.append({
                "plm_name": p.关键件名称,
                "orig_name": o.关键件名称,
                "plm_model": p.型号[:60],
                "orig_model": o.型号[:60],
            })
            continue
        add("only_plm", DiffType.ONLY_PLM, Confidence.MEDIUM, p.table, plm=p)

    for o in rows_orig:
        if id(o) not in used:
            add("only_orig", DiffType.ONLY_ORIG, Confidence.MEDIUM, o.table, orig=o)

    return diffs, fuzzy_hits


def _load(path: Path) -> list[Row]:
    return [Row.model_validate(x) for x in json.loads(path.read_text(encoding="utf-8"))]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    orig = _load(ORIG_JSON)
    plm = _load(PLM_JSON)
    rules = load_rules()

    # 原版 diff（无 fuzzy）
    from compare_core.differ.diff_engine import run_diff
    diffs_old = run_diff(orig, plm, rules)
    counts_old = Counter(d.type.value for d in diffs_old)

    # 新版 diff（带 fuzzy）
    diffs_new, fuzzy_hits = run_diff_with_fuzzy(orig, plm, rules)
    counts_new = Counter(d.type.value for d in diffs_new)

    result = {
        "old_counts": dict(counts_old),
        "new_counts": dict(counts_new),
        "old_total": len(diffs_old),
        "new_total": len(diffs_new),
        "fuzzy_hits_count": len(fuzzy_hits),
        "fuzzy_hits": fuzzy_hits,
        "delta": {
            "only_plm": counts_new.get("only_plm", 0) - counts_old.get("only_plm", 0),
            "only_orig": counts_new.get("only_orig", 0) - counts_old.get("only_orig", 0),
            "changed": counts_new.get("changed", 0) - counts_old.get("changed", 0),
            "same": counts_new.get("same", 0) - counts_old.get("same", 0),
        },
    }

    (OUT_DIR / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== 原版 diff ===")
    print(f"  总行: {len(diffs_old)}, 分类: {dict(counts_old)}")
    print("=== 新版 diff（+fuzzy name） ===")
    print(f"  总行: {len(diffs_new)}, 分类: {dict(counts_new)}")
    print(f"  fuzzy name 命中: {len(fuzzy_hits)} 条")
    for h in fuzzy_hits:
        print(f"    PLM: {h['plm_name'][:40]} | orig: {h['orig_name'][:40]} | 型号: {h['plm_model'][:40]}")
    print(f"\n变化量:")
    for k, v in result["delta"].items():
        print(f"  {k}: {'+' if v >= 0 else ''}{v}")
    print(f"\n产物: {OUT_DIR}")
    print("PROTOTYPE_FUZZY_NAME_DONE")


if __name__ == "__main__":
    main()
