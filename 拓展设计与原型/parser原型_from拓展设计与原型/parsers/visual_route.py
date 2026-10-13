"""Route 3: Word -> PDF/pages plus visual-parser availability preflight.

This module never sends project documents outside the machine. It renders local
pages and reports whether a locally configured MinerU/Marker/Qwen-VL route is
available. Without explicit configuration the result is blocked, not a parse.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any


def export_pdf(source: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{source.stem}.pdf"
    try:
        import win32com.client as win32  # type: ignore
    except Exception as exc:
        raise RuntimeError("PDF 渲染需要本机 Microsoft Word/pywin32") from exc

    word = win32.DispatchEx("Word.Application")
    word.Visible = False
    doc = None
    try:
        doc = word.Documents.Open(
            str(source.resolve()), ReadOnly=True, AddToRecentFiles=False
        )
        try:
            # SaveAs2 with PDF format is usually more stable for complex legacy
            # tables; ExportAsFixedFormat remains the fallback for Word versions
            # that reject PDF SaveAs2.
            doc.SaveAs2(str(target), FileFormat=17)
        except Exception:
            doc.ExportAsFixedFormat(str(target), ExportFormat=17)
    finally:
        if doc is not None:
            try:
                doc.Close(False)
            except Exception:
                pass
        try:
            word.Quit()
        except Exception:
            pass
    if not target.exists():
        raise RuntimeError(f"Word PDF 导出未生成文件: {target}")
    return target


def render_pages(pdf_path: Path, output_dir: Path) -> list[str]:
    try:
        import fitz  # type: ignore
    except Exception as exc:
        raise RuntimeError("未安装 PyMuPDF，无法把 PDF 渲染为页面图片") from exc
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    document = fitz.open(str(pdf_path))
    try:
        for index, page in enumerate(document, start=1):
            pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            target = output_dir / f"page-{index:04d}.png"
            pixmap.save(str(target))
            paths.append(str(target))
    finally:
        document.close()
    return paths


def _availability() -> dict[str, Any]:
    mineru = os.getenv("MINERU_CMD") or shutil.which("mineru")
    marker = os.getenv("MARKER_CMD") or shutil.which("marker")
    qwen = bool(os.getenv("QWEN_VL_API_BASE") and os.getenv("QWEN_VL_MODEL"))
    return {
        "mineru": mineru or "",
        "marker": marker or "",
        "qwen_vl_configured": qwen,
        "remote_calls_enabled": False,
    }


def run_visual_route(source_path: str, work_dir: str) -> dict[str, Any]:
    source = Path(source_path).resolve()
    work = Path(work_dir).resolve()
    pdf = export_pdf(source, work / "pdf")
    pages = render_pages(pdf, work / "pages")
    availability = _availability()
    configured = bool(
        availability["mineru"] or availability["marker"] or availability["qwen_vl_configured"]
    )
    if not configured:
        status = "blocked_missing_config"
        reason = (
            "已完成本地 PDF/图片渲染，但未配置 MinerU、Marker 本地命令或 Qwen-VL 模型/API；"
            "因此不执行视觉解析，也不把预检结果当作准确率。"
        )
    else:
        status = "blocked_parser_invocation"
        reason = (
            "检测到视觉路线配置，但本基准不会自动调用模型或向外部服务发送文档；"
            "请显式接入经授权的本地命令/API 适配器后再评测。"
        )
    return {
        "status": status,
        "rows": [],
        "metadata": {
            "source": str(source),
            "pdf": str(pdf),
            "pdf_pages": len(pages),
            "page_images": pages,
            "availability": availability,
            "reason": reason,
        },
    }
