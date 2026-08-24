"""数据守恒审计：校验输入 A/B 的每一行是否在整合结果中被保留或按决策处理。

在 LangGraph 流程 apply 之后运行，产出 AuditReport（不修改任何数据，纯只读校验）：

- 引擎层：每个 A/B 行是否被某个 diff 引用（未被引用 = 解析/比对阶段丢行，引擎 bug）
- 决策层：行归属 diff 被保留/拒绝；SAME/CHANGED 被拒会同时丢掉 A、B 双侧信息（预警）
- 物理层：回读生成的整合 docx，实际数据行数 vs 预期保留行数（catch writer/排序丢行或重复）

状态分级：
- critical：引擎丢行 或 物理少行 —— 触发 repair 补录
- warning ：SAME/CHANGED 被拒 或 物理多行（疑似重复）
- ok      ：A/B 全部行均已保留或按决策处理
"""
from __future__ import annotations

from collections import Counter

from ..models import AuditReport, DiffType, Row
from .normalize import normalize

# 行指纹字段。基础 4 列在表1(_T1_FIELDS)与表2(_T2_FIELDS)中列位相同（idx 1~4）：
#   idx1=位号, idx2=关键件名称, idx3=型号, idx4=规格材料
# 但仅这 4 列存在真实碰撞（实测"内部布线|/"39 行位号空+型号'/'，指纹完全相同），
# 一丢一重会在多重集相减时互相抵消而漏检。故再加**制造商**（两表 idx5 相同）参与指纹，
# 显著降低碰撞。证书号在两表列位不同（表1 idx8 / 表2 无此列），不纳入以保持列位统一。
_FP_FIELDS = ["位号", "关键件名称", "型号", "规格材料", "制造商"]
_FP_CELL_IDX = (1, 2, 3, 4, 5)


def _brief(r: Row) -> dict:
    """疑似丢失行的精简画像，用于报告与补录。

    注意：必须包含全部 `_FP_FIELDS`（指纹字段），否则补录到附录后
    重新审计时无法重建出相同指纹，会被误判为"仍然缺失"。
    """
    return {
        "source": r.source or "",
        "table": r.table,
        "group": r.group,
        "位号": r.位号,
        "关键件名称": r.关键件名称,
        "型号": r.型号,
        "规格材料": r.规格材料,
        "制造商": r.制造商,
        "证书号": r.证书号,
    }


def _display_row(d) -> Row | None:
    """与 writer 一致的展示行取值：ONLY_ORIG 取 orig 侧，其余取 PLM 侧。"""
    if d.type == DiffType.ONLY_ORIG:
        return d.orig or d.plm
    return d.plm or d.orig


def _row_fp(r: Row) -> str:
    """行指纹（源侧）：normalize 已内置繁→简 + 全半角 + 去空白，与回读侧一致。"""
    return "|".join(normalize(getattr(r, f, "") or "") for f in _FP_FIELDS)


def _cell_fp(cells) -> str:
    """行指纹（docx 回读侧）：用固定列位 cells[1..4]。"""
    vals = [cells[i].text if i < len(cells) else "" for i in _FP_CELL_IDX]
    return "|".join(normalize(v or "") for v in vals)


def _is_merged_title_row(row) -> bool:
    """判断是否为分组标题行——用**结构**判定（整行合并成一个单元格），而非文本比较。

    writer 用 `merge()` 生成标题行，合并后所有 cell 共享同一个 <w:tc> 元素。
    比"所有文本相同且首格非空"可靠：
    - 避免数据行恰好各列同值（如全为 '/'）被误杀
    - 避免空标题行未被识别而被计入数据行
    """
    try:
        cells = row.cells
        if len(cells) < 2:
            return False
        first_tc = cells[0]._tc
        return all(c._tc is first_tc for c in cells)
    except Exception:  # noqa: BLE001 - 结构判定失败则回退文本判定
        texts = [c.text for c in row.cells]
        return bool(texts) and len(set(texts)) == 1


def _read_output(path: str):
    """回读整合 docx。返回 (数据行指纹 Counter, 数据行总数, 读取错误信息)。

    排除每表表头行与分组标题行（按合并单元格结构判定）。
    读取失败返回 (None, -1, 原因) —— 调用方必须据此把状态降级，不可静默跳过校验。
    """
    try:
        from docx import Document
    except Exception as e:  # noqa: BLE001
        return None, -1, f"缺少 python-docx 依赖：{e}"
    try:
        doc = Document(path)
    except Exception as e:  # noqa: BLE001
        return None, -1, f"无法打开输出文档（可能被占用或已损坏）：{e}"
    fps: Counter = Counter()
    total = 0
    for t in doc.tables:
        for i, row in enumerate(t.rows):
            if i == 0:
                continue  # 表头
            if _is_merged_title_row(row):
                continue  # 分组标题行
            fps[_cell_fp(row.cells)] += 1
            total += 1
    return fps, total, ""


def run_audit(rows_orig: list[Row], rows_plm: list[Row], diffs, decisions=None,
              out_merged: str | None = None) -> AuditReport:
    decisions = decisions or {}

    # === 引擎层：行是否被任何 diff 引用 ===
    ref_orig: set[int] = set()
    ref_plm: set[int] = set()
    for d in diffs:
        if d.orig is not None:
            ref_orig.add(id(d.orig))
        if d.plm is not None:
            ref_plm.add(id(d.plm))
    lost_orig = [r for r in rows_orig if id(r) not in ref_orig]
    lost_plm = [r for r in rows_plm if id(r) not in ref_plm]

    # 按类型计数（全量 diff，用于守恒等式）
    type_counts = {t.value: 0 for t in (DiffType.SAME, DiffType.CHANGED,
                                        DiffType.ONLY_PLM, DiffType.ONLY_ORIG)}
    for d in diffs:
        type_counts[d.type.value] = type_counts.get(d.type.value, 0) + 1
    n_same = type_counts[DiffType.SAME.value]
    n_changed = type_counts[DiffType.CHANGED.value]
    n_only_plm = type_counts[DiffType.ONLY_PLM.value]
    n_only_orig = type_counts[DiffType.ONLY_ORIG.value]
    # 守恒等式：A = same+changed+only_orig；B = same+changed+only_plm
    a_conserved = (len(rows_orig) == n_same + n_changed + n_only_orig)
    b_conserved = (len(rows_plm) == n_same + n_changed + n_only_plm)

    # === 决策层：拒绝统计 ===
    from .resolve import resolve_effective_diffs, verdict_of

    def _verdict(d) -> str:
        return verdict_of(decisions, d.key)

    # 有效输出行：与 writer 同口径（普通 reject 丢弃；配对/纠正类保留或重分类）
    kept = resolve_effective_diffs(diffs, decisions)
    rejected_rows = 0
    same_changed_rejected = 0
    for d in diffs:
        v = _verdict(d)
        # 仅"纯丢弃"(reject/ignore 且非配对行) 才算真正丢行；
        # 手动匹配/差异纠正(reject_dup/pair/same/split) 不丢信息，不计入。
        if v in ("reject", "ignore") and not d.pair_reason:
            rejected_rows += (1 if d.orig else 0) + (1 if d.plm else 0)
            if d.type in (DiffType.SAME, DiffType.CHANGED):
                same_changed_rejected += 1

    # === 物理层：回读输出 docx，按指纹多重集比对定位 writer 丢行 ===
    expected_kept = len(kept)
    if out_merged:
        output_fps, output_rows, read_err = _read_output(out_merged)
    else:
        output_fps, output_rows, read_err = None, -1, "未提供输出文档路径"
    output_mismatch = (expected_kept - output_rows) if output_rows >= 0 else 0

    missing_rows: list[Row] = []
    if output_fps is not None:
        # 期望展示行指纹多重集（按 kept 的展示行）
        expected_fps: Counter = Counter()
        fp_to_rows: dict[str, list[Row]] = {}
        for d in kept:
            row = _display_row(d)
            if row is None:
                continue
            fp = _row_fp(row)
            expected_fps[fp] += 1
            fp_to_rows.setdefault(fp, []).append(row)
        # 多重集差：期望里有、输出里缺的指纹（正数=缺失份数）
        missing_counter = expected_fps - output_fps
        for fp, cnt in missing_counter.items():
            for row in fp_to_rows.get(fp, [])[:cnt]:
                missing_rows.append(row)

    # === 定级 + 建议 ===
    status = "ok"
    recs: list[str] = []
    details: list[str] = []

    if lost_orig or lost_plm:
        status = "critical"
        recs.append(
            f"检测到 A {len(lost_orig)} 行 + B {len(lost_plm)} 行 未进入任何差异项，"
            f"疑似解析或比对阶段丢行。已触发补录到文档末尾附录，请人工核对 diff 引擎。"
        )
        for r in (lost_orig + lost_plm)[:20]:
            details.append(f"[引擎丢行] 表{r.table} {r.group}/{r.关键件名称} {r.型号}")

    if missing_rows:
        status = "critical"
        recs.append(
            f"整合文档缺失 {len(missing_rows)} 行（保留项但输出里按指纹未找到），"
            f"疑似 writer 排序/归组阶段丢行。已按指纹定位并触发补录，请检查 _reorder_by_group。"
        )
        for r in missing_rows[:20]:
            details.append(f"[输出丢行] 表{r.table} {r.group}/{r.关键件名称} {r.型号}")
    elif output_rows >= 0 and output_mismatch > 0:
        # 计数少但指纹没定位到（例如同指纹行被合并计数），仍给 critical 提示
        status = "critical"
        recs.append(
            f"整合文档实际数据行 {output_rows} < 预期保留 {expected_kept}（少 {output_mismatch} 行），"
            f"疑似 writer 丢行但指纹未能逐行定位，请人工复核 _reorder_by_group。"
        )

    if output_rows >= 0 and output_mismatch < 0:
        if status != "critical":
            status = "warning"
        recs.append(
            f"整合文档实际数据行 {output_rows} > 预期保留 {expected_kept}（多 {-output_mismatch} 行），"
            f"疑似重复输出，请检查排序归组是否重复插入。"
        )

    if same_changed_rejected:
        if status == "ok":
            status = "warning"
        recs.append(
            f"有 {same_changed_rejected} 条两侧都有(SAME/CHANGED)的项被拒绝，"
            f"A、B 双侧信息都不会进入整合清单，请确认是否符合预期（对照表仍会保留该变更记录）。"
        )

    # 物理层未能校验（文档读不到）→ 必须降级并明示，不可静默判 ok，
    # 否则会给出"守恒通过"的虚假结论（实际上物理层根本没验）。
    if output_rows < 0:
        if status == "ok":
            status = "warning"
        recs.append(f"物理层未校验：{read_err or '输出文档不可读'}。"
                    f"本次仅完成引擎层与决策层校验，请确认输出文档是否正常生成。")
        details.append(f"[物理层跳过] {read_err}")

    # 守恒等式（人类可读交叉校验）写进 details
    a_mark = "✓" if a_conserved else "✗"
    b_mark = "✓" if b_conserved else "✗"
    details.insert(0, f"输入 B {len(rows_plm)} 行 = 相同 {n_same} + 内容不同 {n_changed} + B独有 {n_only_plm} {b_mark}")
    details.insert(0, f"输入 A {len(rows_orig)} 行 = 相同 {n_same} + 内容不同 {n_changed} + A独有 {n_only_orig} {a_mark}")

    if status == "ok":
        recs.append("数据守恒校验通过：A/B 全部行均已保留或按用户决策处理，无意外丢失。")

    return AuditReport(
        status=status,
        input_orig_rows=len(rows_orig),
        input_plm_rows=len(rows_plm),
        diff_count=len(diffs),
        type_counts=type_counts,
        a_conserved=a_conserved,
        b_conserved=b_conserved,
        kept_count=expected_kept,
        output_rows=output_rows,
        output_mismatch=output_mismatch,
        lost_orig=[_brief(r) for r in lost_orig],
        lost_plm=[_brief(r) for r in lost_plm],
        missing_in_output=[_brief(r) for r in missing_rows],
        rejected_rows=rejected_rows,
        same_changed_rejected=same_changed_rejected,
        recommendations=recs,
        details=details,
    )
