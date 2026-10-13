"""解密链路测试：magic bytes → 直接 parse → 解密 → 解密后 parse。用完可删。

用法：
    python test_decrypt.py "文件路径.docx"
Linux 上中文路径传参正常；Windows 上中文路径经命令行传参会乱码，
Windows 下如需本地测试，请直接把路径硬编码进 FILES 列表。
"""
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

NORMAL_DOCX_MAGIC = "504B0304"  # 正常未加密 .docx 的 zip 头


def test_one(p: Path) -> None:
    print("=" * 64)
    print(f"文件: {p}")
    if not p.exists():
        print("!! 文件不存在")
        return
    size = p.stat().st_size
    magic = p.read_bytes()[:8].hex().upper()
    flag = "<== 明文(正常docx)" if magic.startswith(NORMAL_DOCX_MAGIC) else "<== 密文/未知(需解密)"
    print(f"大小: {size} bytes")
    print(f"magic bytes: {magic}  {flag}")

    from compare_core.parser import parse_docx

    print("[1] 直接 parse_docx ...")
    try:
        rows = parse_docx(str(p))
        print(f"    成功：{len(rows)} 行（读到的是明文，无需解密）")
    except Exception as e:
        print(f"    失败：{type(e).__name__}: {str(e)[:150]}")

    print("[2] 调用解密服务 decrypt_file ...")
    from compare_core.decrypt import decrypt_file

    try:
        dec = decrypt_file(p)
        dec_magic = dec.read_bytes()[:8].hex().upper()
        print(f"    解密成功：{dec.name}  大小 {dec.stat().st_size} bytes")
        print(f"    解密后 magic bytes: {dec_magic}  "
              f"{'<== 明文' if dec_magic.startswith(NORMAL_DOCX_MAGIC) else '<== 仍是密文/异常'}")
    except Exception as e:
        print(f"    解密失败：{type(e).__name__}: {str(e)[:300]}")
        return

    print("[3] 解密后 parse_docx ...")
    try:
        rows = parse_docx(str(dec))
        print(f"    成功：{len(rows)} 行")
        if rows:
            r = rows[0]
            print(f"    首行: table={r.table} 分组={r.group!r} 名称={r.关键件名称!r} 型号={r.型号!r}")
    except Exception as e:
        print(f"    仍失败：{type(e).__name__}: {str(e)[:300]}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('用法: python test_decrypt.py "文件路径"')
        sys.exit(1)
    test_one(Path(sys.argv[1]))
