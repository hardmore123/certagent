"""生成 Word：整合清单 + 变更前后对照表。

问题①修复：按原始清单结构模板化重建——
- 表1(关键件主清单) 与 表2(备选件表) 分开输出，各自固定列 schema；
- 保留分组标题行（跨列合并）；
- 非重复/差异行标红加粗 + 来源列；
- 统一走输出规范化（繁→简 + 控制字符清洗）。
"""
from __future__ import annotations

import re

from ..config import config
from ..differ.normalize import to_simplified
from ..models import ChangeEntry, DiffItem, DiffType

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# 表1（关键件主清单）：表头 与 对应 Row 字段（末列为“来源”，单独填）
_T1_HEADERS = ["序号", "位号", "关键件名称", "型号", "规格/材料", "生产者(制造商)",
               "生产企业", "认证标准", "证书号", "来源"]
_T1_FIELDS = ["序号", "位号", "关键件名称", "型号", "规格材料", "制造商",
              "生产企业", "认证标准", "证书号"]

# 表2（备选件/电源单元表）
_T2_HEADERS = ["序号", "位号", "名称", "型号", "规格/材料", "制造商",
               "生产厂", "本次使用/备用", "备注", "来源"]
_T2_FIELDS = ["序号", "位号", "关键件名称", "型号", "规格材料", "制造商",
              "生产企业", "本次使用", "备注"]

_SOURCE_LABEL = {
    DiffType.ONLY_PLM: "新增(PLM新版本)",
    DiffType.ONLY_ORIG: "旧版本保留",
    DiffType.CHANGED: "两侧(差异)",
    DiffType.SAME: "两侧",
}


def _safe(text: str) -> str:
    """输出规范化：去控制字符（docx/XML 安全）+ 可选繁→简统一。"""
    s = _CTRL.sub("", text or "")
    if config.OUTPUT_SIMPLIFIED:
        s = to_simplified(s)
    return s


def _style_cell(cell, *, bold: bool = False, red: bool = False,
                font_name: str | None = None, size_emu: int | None = None):
    """统一单元格内所有 run 的字体（中英文一致）+ 字号 + 加粗/红色。

    font_name/size_emu 为空时回退到 config.OUTPUT_FONT / 不设字号（沿用旧行为）。
    """
    from docx.oxml.ns import qn
    from docx.shared import Emu, RGBColor

    font = font_name or config.OUTPUT_FONT
    for p in cell.paragraphs:
        for run in p.runs:
            run.font.name = font
            try:
                rpr = run._element.get_or_add_rPr()
                rpr.get_or_add_rFonts().set(qn("w:eastAsia"), font)  # 中文字体
            except Exception:  # noqa: BLE001
                pass
            if size_emu:
                try:
                    run.font.size = Emu(size_emu)
                except Exception:  # noqa: BLE001
                    pass
            if bold:
                run.bold = True
            if red:
                try:
                    run.font.color.rgb = RGBColor(0xFF, 0x00, 0x00)
                except Exception:  # noqa: BLE001
                    pass


def _set_doc_font(doc, font_name: str | None = None):
    """设置文档 Normal 样式的中英文字体，作为全局默认。"""
    from docx.oxml.ns import qn

    font = font_name or config.OUTPUT_FONT
    try:
        style = doc.styles["Normal"]
        style.font.name = font
        rpr = style.element.get_or_add_rPr()
        rpr.get_or_add_rFonts().set(qn("w:eastAsia"), font)
    except Exception:  # noqa: BLE001
        pass


def _apply_page_setup(doc, profile):
    """把画像的页面方向/纸张尺寸/页边距套到文档首个 section。"""
    if not profile or not doc.sections:
        return
    sec = doc.sections[0]
    try:
        if profile.page_width and profile.page_height:
            sec.page_width = profile.page_width
            sec.page_height = profile.page_height
        if profile.orientation is not None:
            sec.orientation = profile.orientation
        if profile.margins:
            l, r, t, b = profile.margins
            if l is not None:
                sec.left_margin = l
            if r is not None:
                sec.right_margin = r
            if t is not None:
                sec.top_margin = t
            if b is not None:
                sec.bottom_margin = b
    except Exception:  # noqa: BLE001
        pass


def _shade_cell(cell, fill: str = "FFFF00"):
    """给单元格加底纹（默认黄色），用于高亮 CHANGED 行里具体有差异的字段。"""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    try:
        tcPr = cell._tc.get_or_add_tcPr()
        shd = tcPr.find(qn("w:shd"))
        if shd is None:
            shd = OxmlElement("w:shd")
            tcPr.append(shd)
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), fill)
    except Exception:  # noqa: BLE001
        pass


def _apply_run_font(run, font_name=None, size_emu=None, *, red=False, bold=False):
    """设置单个 run 的中英文字体/字号/红色/加粗。"""
    from docx.oxml.ns import qn
    from docx.shared import Emu, RGBColor

    font = font_name or config.OUTPUT_FONT
    run.font.name = font
    try:
        rpr = run._element.get_or_add_rPr()
        rpr.get_or_add_rFonts().set(qn("w:eastAsia"), font)
    except Exception:  # noqa: BLE001
        pass
    if size_emu:
        try:
            run.font.size = Emu(size_emu)
        except Exception:  # noqa: BLE001
            pass
    if red:
        try:
            run.font.color.rgb = RGBColor(0xFF, 0x00, 0x00)
        except Exception:  # noqa: BLE001
            pass
    if bold:
        run.bold = True


def _tokenize(s: str) -> list[str]:
    """按分隔符切 token（保留分隔符），供词级 diff 对齐。"""
    return re.findall(r"[^、,;；/／\s]+|[、,;；/／\s]+", s or "")


def _fill_diff_cell(cell, old_val: str, new_val: str, *, font_name=None, size_emu=None):
    """按词级 diff 填充变更字段单元格：新增/变更的 token 加黄色荧光高亮，其余仅红字。

    只高亮"实际变动的词"，而非整个单元格。旧侧独有 token 在新版本里不显示。
    """
    import difflib

    from docx.enum.text import WD_COLOR_INDEX

    old_t = _tokenize(_safe(old_val))
    new_t = _tokenize(_safe(new_val))
    p = cell.paragraphs[0]
    for r in list(p.runs):  # 清空既有 run
        r._element.getparent().remove(r._element)

    sm = difflib.SequenceMatcher(None, old_t, new_t)
    for tag, _i1, _i2, j1, j2 in sm.get_opcodes():
        if tag == "delete":
            continue  # 旧侧独有，新版本不显示
        seg = "".join(new_t[j1:j2])
        if not seg:
            continue
        run = p.add_run(seg)
        _apply_run_font(run, font_name, size_emu, red=True)
        if tag in ("replace", "insert"):  # 变动部分高亮
            try:
                run.font.highlight_color = WD_COLOR_INDEX.YELLOW
            except Exception:  # noqa: BLE001
                pass


def _apply_table_borders(table):
    """显式给整表加单线边框（不依赖表格样式）。

    套用输入表格样式(如 'Normal Table')时其本身无边框，输入文件的边框是显式
    tblBorders 而非来自样式；新建表只套样式拿不到边框，故这里显式写入。
    """
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    try:
        tblPr = table._tbl.tblPr
        borders = tblPr.find(qn("w:tblBorders"))
        if borders is None:
            borders = OxmlElement("w:tblBorders")
            tblPr.append(borders)
        for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
            el = borders.find(qn("w:" + edge))
            if el is None:
                el = OxmlElement("w:" + edge)
                borders.append(el)
            el.set(qn("w:val"), "single")
            el.set(qn("w:sz"), "4")
            el.set(qn("w:space"), "0")
            el.set(qn("w:color"), "auto")
    except Exception:  # noqa: BLE001
        pass


def _apply_col_widths(table, widths_emu):
    """按画像列宽设置每列宽度。

    需三管齐下才在各渲染器一致生效：
    - 关闭 autofit（tblLayout=fixed）
    - 逐单元格设 tcW（Word 固定布局按此渲染）
    - 同步 tblGrid 的 gridCol（部分渲染器依赖它）
    """
    from docx.oxml.ns import qn
    from docx.shared import Emu

    if not widths_emu or not any(widths_emu):
        return
    try:
        table.autofit = False
        for row in table.rows:
            for idx, w in enumerate(widths_emu):
                if w and idx < len(row.cells):
                    row.cells[idx].width = Emu(w)
        # 同步 tblGrid（twips = EMU/635）
        grid = table._tbl.tblGrid
        cols = grid.findall(qn("w:gridCol"))
        for idx, g in enumerate(cols):
            if idx < len(widths_emu) and widths_emu[idx]:
                g.set(qn("w:w"), str(int(widths_emu[idx] / 635)))
    except Exception:  # noqa: BLE001
        pass


def _source_comment_text(d: DiffItem) -> str:
    """构造挂在行上的“来源/差异”批注文本。"""
    parts = ["来源：" + _SOURCE_LABEL.get(d.type, "")]
    if d.type == DiffType.CHANGED and d.changed_fields:
        parts.append("差异：" + "、".join(str(x) for x in d.changed_fields))
    if getattr(d, "pair_reason", ""):
        conf = getattr(d, "pair_confidence", 0.0)
        parts.append(f"配对说明（置信度{conf:.2f}）：{d.pair_reason}")
    return "　".join(parts)


def _add_comment(doc, cell, text: str):
    """把批注锚定到单元格首个 run（python-docx≥1.2 原生批注）。失败静默降级。"""
    try:
        para = cell.paragraphs[0]
        run = para.runs[0] if para.runs else para.add_run("")
        doc.add_comment(run, text=text, author=config.OUTPUT_COMMENT_AUTHOR, initials="AI")
    except Exception:  # noqa: BLE001 - 批注非核心，失败不影响清单生成
        pass


def _add_group_row(table, text: str, *, font_name=None, size_emu=None):
    """插入一行跨列合并的分组标题行。"""
    cells = table.add_row().cells
    merged = cells[0]
    for c in cells[1:]:
        merged = merged.merge(c)
    merged.text = _safe(text)
    _style_cell(merged, bold=True, font_name=font_name, size_emu=size_emu)


def _emit_table(doc, title: str, diffs, headers, fields, profile=None, tfmt=None):
    # 来源呈现方式：批注模式去掉末列“来源”，列结构贴近标准模板；否则保留来源文本列。
    as_comment = config.OUTPUT_SOURCE_AS_COMMENT
    use_headers = headers[:-1] if as_comment else headers
    # 关键件名称在 fields 中的列下标（批注锚点，通常非空）
    name_idx = fields.index("关键件名称") if "关键件名称" in fields else 0

    # 画像字体/字号（无画像时回退默认）
    font_name = profile.font_name if profile else None
    data_size = profile.data_size_emu if profile else None
    header_size = (profile.header_size_emu or profile.data_size_emu) if profile else None

    doc.add_heading(title, level=2)
    table = doc.add_table(rows=1, cols=len(use_headers))
    table.style = (profile.table_style if profile and profile.table_style else "Table Grid")
    _apply_table_borders(table)  # 显式边框，避免套用无边框样式(如 Normal Table)后表格无框线
    for i, h in enumerate(use_headers):
        table.rows[0].cells[i].text = h
        _style_cell(table.rows[0].cells[i], bold=True, font_name=font_name, size_emu=header_size)

    cur_group = None
    for d in diffs:
        # PLM(新版本)为输出骨架：SAME/CHANGED/ONLY_PLM 都优先取 PLM 侧展示；
        # ONLY_ORIG(旧版本独有保留项) 取 orig 侧
        if d.type == DiffType.ONLY_ORIG:
            row = d.orig or d.plm
        else:
            row = d.plm or d.orig
        if row is None:
            continue
        # 分组标题行（组变化时插入一次）
        if row.group and row.group != cur_group:
            cur_group = row.group
            _add_group_row(table, row.group, font_name=font_name, size_emu=header_size)
        values = [getattr(row, f, "") or "" for f in fields]
        if not as_comment:
            values = values + [_SOURCE_LABEL.get(d.type, "")]
        cells = table.add_row().cells
        # 标记策略：
        # - ONLY_PLM（新增项）：整行标红（不加粗）
        # - CHANGED（内容变更）：只标记具体有差异的字段单元格（红字 + 黄色底纹），其余单元格正常
        # - ONLY_ORIG（旧版本保留）/SAME：不标记
        whole_red = d.type == DiffType.ONLY_PLM
        changed_cols: set[str] = set()
        if d.type == DiffType.CHANGED:
            for cf in d.changed_fields:
                if not isinstance(cf, str):
                    continue
                changed_cols.add(cf)
                if cf.startswith("(型号集合"):  # 型号集合差异 → 高亮型号列
                    changed_cols.add("型号")
        for i, v in enumerate(values):
            fld = fields[i] if i < len(fields) else None  # 末列"来源"(非批注模式) 无对应字段
            is_changed_cell = bool(fld and fld in changed_cols)
            if is_changed_cell and d.orig is not None:
                # 变更字段：词级 diff，仅高亮实际变动的 token（红字 + 黄色荧光）
                cells[i].text = ""
                _fill_diff_cell(cells[i], getattr(d.orig, fld, "") or "", v,
                                font_name=font_name, size_emu=data_size)
            else:
                cells[i].text = _safe(v)
                _style_cell(cells[i], bold=False, red=whole_red,
                            font_name=font_name, size_emu=data_size)
        # 批注模式：非 SAME 行把来源/差异挂成 Word 批注
        if as_comment and d.type != DiffType.SAME:
            _add_comment(doc, cells[name_idx], _source_comment_text(d))

    # 套用输入列宽（表头别名匹配）
    if profile and tfmt is not None:
        from .format_profile import map_widths
        _apply_col_widths(table, map_widths(use_headers, tfmt))


def write_merged_list(diffs: list[DiffItem], decisions: dict[str, str], out_path: str,
                      template_docx: str | None = None) -> str:
    """按原始结构重建整合清单。decisions: diff_key -> accept/reject（reject 不并入）。

    输出顺序：以 A（orig）为骨架，B 独有（ONLY_PLM）按 group 插入对应组的末尾。
    template_docx: 若提供且开关开启，则以该输入文件为格式模板（字体/字号/页面/列宽）。
    """
    from docx import Document

    # 格式画像：从输入模板提取排版属性（失败为 None，回退默认）
    profile = None
    if template_docx and config.OUTPUT_USE_INPUT_TEMPLATE:
        from .format_profile import extract_profile
        profile = extract_profile(template_docx)

    doc = Document()
    _set_doc_font(doc, profile.font_name if profile else None)
    _apply_page_setup(doc, profile)
    doc.add_heading("整合版 安全&EMC关键件清单", level=1)
    if config.OUTPUT_SOURCE_AS_COMMENT:
        doc.add_paragraph("说明：新增/差异项以红色加粗标注，资料来源与差异说明见单元格批注；重复项已合并保留一份。")
    else:
        doc.add_paragraph("说明：新增/差异项以红色加粗标注，末列注明资料来源；重复项已合并保留一份。")

    # 决策解析 + 关键件组排序：复用 differ.ordering（与差异确认页共用同一顺序）
    from ..differ.ordering import split_tables

    # 画像里 tables[0]=输入表1，tables[1]=输入表2（用于列宽映射）
    ptabs = profile.tables if profile else []
    tfmt1 = ptabs[0] if len(ptabs) > 0 else None
    tfmt2 = ptabs[1] if len(ptabs) > 1 else None

    t1, t2 = split_tables(diffs, decisions)
    if t1:
        _emit_table(doc, "表一 关键件主清单", t1, _T1_HEADERS, _T1_FIELDS, profile=profile, tfmt=tfmt1)
    if t2:
        _emit_table(doc, "表二 备选件/电源单元清单", t2, _T2_HEADERS, _T2_FIELDS, profile=profile, tfmt=tfmt2)
    doc.save(out_path)
    return out_path


def append_audit_supplement(out_path: str, lost_rows: list[dict]) -> str:
    """把审计判定为疑似丢失的行补录到整合文档末尾的附录表，保证零物理丢失。

    lost_rows: audit._brief 产出的精简画像列表（source/table/group/关键件名称/型号/规格材料/证书号）。
    """
    from docx import Document

    if not lost_rows:
        return out_path
    doc = Document(out_path)
    doc.add_heading("⚠ 审计补录（疑似丢失，需人工复核）", level=2)
    doc.add_paragraph("以下行经数据守恒审计判定未进入正文，系统自动补录以保证信息不丢失，请人工核对。")
    # 列位 1~5（位号/关键件名称/型号/规格材料/制造商）必须与正文表及
    # 审计指纹 `audit._FP_CELL_IDX` 严格一致，否则补录后重新审计
    # 无法重建相同指纹，会被误判为"仍然缺失"。改指纹字段时必须同步改这里。
    headers = ["来源", "位号", "关键件名称", "型号", "规格/材料", "生产者(制造商)", "分组", "证书号"]
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    for i, h in enumerate(headers):
        table.rows[0].cells[i].text = h
        _style_cell(table.rows[0].cells[i], bold=True)
    for r in lost_rows:
        vals = [r.get("source", ""), r.get("位号", ""), r.get("关键件名称", ""),
                r.get("型号", ""), r.get("规格材料", ""), r.get("制造商", ""),
                r.get("group", ""), r.get("证书号", "")]
        cells = table.add_row().cells
        for i, v in enumerate(vals):
            cells[i].text = _safe(v)
            _style_cell(cells[i], red=True)
    doc.save(out_path)
    return out_path


def write_compare_table(changes: list[ChangeEntry], out_path: str) -> str:
    from docx import Document

    doc = Document()
    _set_doc_font(doc)
    doc.add_heading("变更前后对照表", level=1)
    table = doc.add_table(rows=1, cols=3)
    table.style = "Table Grid"
    for i, h in enumerate(["变更项目", "变更前", "变更后"]):
        table.rows[0].cells[i].text = h
        _style_cell(table.rows[0].cells[i], bold=True)
    for ce in changes:
        cells = table.add_row().cells
        cells[0].text = _safe(ce.变更项目)
        cells[1].text = _safe(ce.变更前)
        cells[2].text = _safe(ce.变更后)
        for c in cells:
            _style_cell(c)
    doc.save(out_path)
    return out_path
