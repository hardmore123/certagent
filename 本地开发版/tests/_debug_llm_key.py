"""安全诊断脚本：只输出 key 的元信息（长度、前后缀），不 echo 实际内容。"""
import os
import sys
from pathlib import Path

TESTS = Path(__file__).parent
sys.path.insert(0, str(TESTS))
from experiment_group_llm import _load_env_file  # noqa: E402

loaded_from = _load_env_file()
print("=" * 60)
print(".env 加载来源:", loaded_from)

key = os.environ.get("LLM_API_KEY", "")
base = os.environ.get("LLM_BASE_URL", "")
model = os.environ.get("LLM_MODEL", "")

print(f"LLM_BASE_URL: {base!r}")
print(f"LLM_MODEL:    {model!r}")
print(f"LLM_API_KEY 长度: {len(key)}")
print(f"LLM_API_KEY 前 4 字符: {key[:4]!r}")
print(f"LLM_API_KEY 后 4 字符: {key[-4:]!r}" if len(key) >= 4 else "  (太短)")
print(f"LLM_API_KEY 是否以 'sk-' 开头: {key.startswith('sk-')}")
print(f"LLM_API_KEY 是否还是占位符: {'REPLACE_ME' in key}")
print(f"LLM_API_KEY 是否含首尾空格: {key != key.strip()}")
print(f"LLM_API_KEY 是否含双引号: {'\"' in key or chr(39) in key}")
print("=" * 60)

if loaded_from:
    # 再读一次原始 .env 的 LLM_API_KEY 那一行的 raw 表示（十六进制前 6 字节）
    lines = Path(loaded_from).read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines, 1):
        if line.strip().startswith("LLM_API_KEY"):
            print(f"原始 .env 第 {i} 行长度: {len(line)}")
            print(f"原始 .env 第 {i} 行前 20 字节的 hex: {line[:20].encode('utf-8').hex()}")
            print(f"原始 .env 第 {i} 行结尾字符是否为换行: {line != line.rstrip()}")
            break
