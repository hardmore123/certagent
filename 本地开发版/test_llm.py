"""临时诊断：验证服务器 CertAgent 的 LLM 网关 + 模型是否正常返回。用完可删。"""
import os
import sys
import time
import json
from pathlib import Path

# 手动加载 .env（等效 source .env），避免依赖 shell 注入
_env = Path(__file__).resolve().parent / ".env"
if _env.exists():
    for line in _env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

import requests  # noqa: E402
from compare_core.config import config  # noqa: E402

print("=== LLM 配置 ===")
print("BASE_URL:", config.LLM_BASE_URL)
print("MODEL:", config.LLM_MODEL)
print("API_KEY:", "已配置" if config.LLM_API_KEY else "未配置")
print("USER_KEY:", "已配置" if config.LLM_USER_KEY else "未配置")

if not (config.LLM_BASE_URL and config.LLM_API_KEY and config.LLM_MODEL):
    print("!! LLM 环境变量未配置，.env 可能缺失或格式异常")
    sys.exit(1)

url = config.LLM_BASE_URL.rstrip("/") + "/chat/completions"
headers = {"Authorization": f"Bearer {config.LLM_API_KEY}", "Content-Type": "application/json"}
params = {"user_key": config.LLM_USER_KEY} if config.LLM_USER_KEY else {}
body = {"model": config.LLM_MODEL,
        "messages": [{"role": "user", "content": "只回答一个数字：1+1等于几？"}],
        "temperature": 0, "stream": True}

print("\n=== 调用 LLM ===")
t0 = time.time()
try:
    resp = requests.post(url, headers=headers, params=params, json=body, timeout=60, stream=True)
    print("HTTP", resp.status_code)
    resp.raise_for_status()
    parts, reasoning_total = [], 0
    for line in resp.iter_lines(decode_unicode=True):
        if time.time() - t0 > 60:
            print("!! 60s 未完成，模型疑似抽风（熔断会在此兜底）")
            break
        if not line:
            continue
        data = line[5:].strip() if line.startswith("data:") else line.strip()
        if data == "[DONE]":
            break
        try:
            obj = json.loads(data)
        except Exception:
            continue
        ch = (obj.get("choices") or [{}])[0]
        delta = ch.get("delta") or {}
        rc = delta.get("reasoning_content") or ""
        if rc:
            reasoning_total += len(rc)
        piece = delta.get("content") or (ch.get("message") or {}).get("content")
        if piece:
            parts.append(piece)
    elapsed = time.time() - t0
    answer = "".join(parts)
    print(f"耗时={elapsed:.1f}s  思考字数={reasoning_total}  回答字数={len(answer)}")
    print("ANSWER:", answer[:300] if answer else "(空)")
except Exception as e:
    print(f"调用异常（{time.time()-t0:.1f}s）: {type(e).__name__}: {e}")
