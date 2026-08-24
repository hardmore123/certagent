"""透明加密文件解密 — 调用内网解密服务还原明文。

公司办公文件可能被透明加密：本地能正常打开，但原始字节是密文。上传到服务器后
python-docx 无法直接解析。此模块在解析失败时兜底：把文件发给内网解密服务
（http://10.18.87.51:8500/parse_file），拿回解密后的文件流再解析。

服务接口见《Decryptor Server API 开发文档》，format=file 返回解密后二进制流。
"""
from __future__ import annotations

from pathlib import Path

import requests

from .config import config


def decrypt_file(input_path: str | Path, output_path: str | Path | None = None) -> Path:
    """上传（可能加密的）文件到解密服务，返回解密后的文件路径。

    Args:
        input_path: 待解密文件路径
        output_path: 解密文件保存路径，默认同目录 <stem>_decrypted<suffix>

    Returns:
        解密后文件的 Path

    Raises:
        FileNotFoundError: 输入文件不存在
        requests.HTTPError: 解密服务返回错误（缺文件/解密失败/类型不支持）
    """
    input_file = Path(input_path)
    if not input_file.exists():
        raise FileNotFoundError(f"文件不存在: {input_path}")

    if output_path is None:
        output_path = input_file.with_name(f"{input_file.stem}_decrypted{input_file.suffix}")

    with open(input_file, "rb") as f:
        resp = requests.post(
            config.DECRYPT_URL,
            files={"file": (input_file.name, f)},
            data={"format": "file"},
            timeout=config.DECRYPT_TIMEOUT,
        )
    resp.raise_for_status()

    out = Path(output_path)
    out.write_bytes(resp.content)
    return out
