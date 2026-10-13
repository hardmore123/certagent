"""大模型网关连通性诊断（ReportVerify 版，脱敏）。

验证 .env 配置的 higpt 网关 + 模型能否正常返回。只打印是否配置、HTTP 状态、
耗时与简短回答，**绝不打印 api_key / user_key 的值**。

用法（项目根目录）：
    python scripts/ping_llm.py

退出码：0 成功拿到非空回答；1 配置缺失或调用失败。

注意：
- 不依赖 CertAgent 的 compare_core，直接读 report_verify.llm 的配置。
- 内网外运行通常会 SSLError / WRONG_VERSION_NUMBER（来源准入），属环境问题。
- 本脚本只做连通性探测，不替代 release_gate 门禁，也不改变生产 mode。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from report_verify.env_bootstrap import load_project_env  # noqa: E402


def main() -> int:
    load_project_env()
    from report_verify.llm.config import LLMSettings

    s = LLMSettings.from_env()

    print("=== LLM 配置（脱敏）===")
    print("BASE_URL host:", (s.base_url.split("/")[2] if "//" in s.base_url else "(未设置)"))
    print("MODEL        :", s.model or "(未设置)")
    print("API_KEY      :", "已配置" if s.api_key else "未配置")
    print("USER_KEY     :", "已配置" if s.user_key else "未配置")

    if not (s.base_url and s.api_key and s.model):
        print("\n!! 配置不完整（需要 BASE_URL / API_KEY / MODEL），请检查 .env")
        return 1

    try:
        import requests
    except ImportError:
        print("\n!! 未安装 requests（pip install -r requirements.txt）")
        return 1

    url = s.base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {s.api_key}", "Content-Type": "application/json"}
    params = {"user_key": s.user_key} if s.user_key else {}
    body = {
        "model": s.model,
        "messages": [{"role": "user", "content": "只回答一个数字：1+1等于几？"}],
        "temperature": 0,
        "stream": True,
    }

    print("\n=== 调用网关 ===")
    t0 = time.time()
    try:
        resp = requests.post(
            url, headers=headers, params=params, json=body,
            timeout=min(s.timeout_seconds, 60), stream=True,
        )
        print("HTTP", resp.status_code)
        resp.raise_for_status()
        parts: list[str] = []
        for line in resp.iter_lines(decode_unicode=True):
            if time.time() - t0 > 60:
                print("!! 60s 未完成，提前结束探测")
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
            piece = delta.get("content") or (ch.get("message") or {}).get("content")
            if piece:
                parts.append(piece)
        answer = "".join(parts)
        print(f"耗时={time.time() - t0:.1f}s  回答字数={len(answer)}")
        print("ANSWER:", answer[:200] if answer else "(空)")
        return 0 if answer else 1
    except Exception as exc:  # noqa: BLE001
        print(f"调用异常（{time.time() - t0:.1f}s）: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
