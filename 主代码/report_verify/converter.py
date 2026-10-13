"""复用 donor 的 .doc -> .docx 转换边界，转换失败时明确报错。"""
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
    for candidate in (
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ):
        if Path(candidate).exists():
            return candidate
    return None


def _via_libreoffice(src: Path, out_dir: Path, executable: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [executable, "--headless", "--norestore", "--convert-to", "docx",
         "--outdir", str(out_dir), str(src.resolve())],
        check=False, capture_output=True, text=True, timeout=120,
    )
    target = out_dir / f"{src.stem}.docx"
    if not target.exists():
        raise RuntimeError("LibreOffice 未生成目标 docx")
    return target


def ensure_docx(path: str, work_dir: str | None = None) -> str:
    src = Path(path)
    if src.suffix.lower() == ".docx":
        return str(src)
    out_dir = Path(work_dir) if work_dir else src.parent / "_converted"
    executable = _find_libreoffice()
    if executable:
        try:
            return str(_via_libreoffice(src, out_dir, executable))
        except Exception as exc:
            lo_error = str(exc)
    else:
        lo_error = "未找到 LibreOffice"
    if os.name == "nt":
        raise RuntimeError(f".doc 转换失败：{lo_error}；请先手动另存为 .docx")
    raise RuntimeError(f".doc 转换失败：{lo_error}")
