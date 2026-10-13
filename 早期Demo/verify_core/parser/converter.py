"""老 .doc → .docx 自动转换（多级策略，用完即退）。

复用自 list-merge-demo：
1. LibreOffice headless（跨平台，无需 Word）
2. Word COM 独立子进程（Windows 有 Word 时）
3. 都不可用 → 抛出明确错误
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _find_libreoffice() -> str | None:
    for name in ("soffice", "soffice.exe", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    candidates = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return None


def _convert_via_libreoffice(src: Path, out_dir: Path, soffice: str, timeout: int = 120) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        soffice, "--headless", "--norestore", "--convert-to", "docx",
        "--outdir", str(out_dir), str(src.resolve()),
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=timeout, text=True)
    target = out_dir / f"{src.stem}.docx"
    if not target.exists():
        raise RuntimeError(f"LibreOffice 转换失败：{result.stderr[:200] or result.stdout[:200]}")
    return target


_COM_CONVERT_SCRIPT = '''
import sys
import pythoncom
import win32com.client as win32

src, target = sys.argv[1], sys.argv[2]
pythoncom.CoInitialize()
word = None
doc = None
try:
    word = win32.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    doc = word.Documents.Open(src, ReadOnly=True, AddToRecentFiles=False)
    doc.SaveAs2(target, FileFormat=16)  # 16 = wdFormatXMLDocument (.docx)
finally:
    if doc is not None:
        try: doc.Close(False)
        except Exception: pass
    if word is not None:
        try: word.Quit()
        except Exception: pass
    pythoncom.CoUninitialize()
'''


def _convert_via_word_subprocess(src: Path, out_dir: Path, timeout: int = 120) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{src.stem}.docx"
    script_path = out_dir / "_com_convert.py"
    script_path.write_text(_COM_CONVERT_SCRIPT, encoding="utf-8")
    cmd = [sys.executable, str(script_path), str(src.resolve()), str(target.resolve())]
    result = subprocess.run(cmd, capture_output=True, timeout=timeout, text=True)
    if not target.exists():
        raise RuntimeError(f"Word COM 子进程转换失败：{result.stderr[:300] or result.stdout[:300]}")
    return target


def ensure_docx(path: str, work_dir: str | None = None) -> str:
    """确保返回一个 .docx 路径。.doc 自动转换，.docx 原样返回。"""
    src = Path(path)
    if src.suffix.lower() == ".docx":
        return str(src)

    out_dir = Path(work_dir) if work_dir else src.parent / "_converted"
    errors = []

    soffice = _find_libreoffice()
    if soffice:
        try:
            return str(_convert_via_libreoffice(src, out_dir, soffice))
        except Exception as e:  # noqa: BLE001
            errors.append(f"LibreOffice: {e}")

    if os.name == "nt":
        try:
            return str(_convert_via_word_subprocess(src, out_dir))
        except Exception as e:  # noqa: BLE001
            errors.append(f"Word COM: {e}")

    raise RuntimeError(
        "无法把 .doc 转换为 .docx。请安装 LibreOffice，或用 Word 手动另存为 .docx。\n"
        + "\n".join(errors)
    )
