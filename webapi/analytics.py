"""后台使用统计：记录每次 API 调用，提供汇总查询。

记录内容：谁、什么时间、调了什么接口、耗时多少、状态码。
落盘文件：runs/analytics.jsonl（每行一条 JSON，追加写入）。
管理接口：GET /api/v1/analytics（仅 admin）查看汇总。

统计指标：
- 总调用次数
- 独立用户数（去重）
- 各用户调用次数
- 各接口调用次数
- 平均/最大响应时间
- 按天统计（调用量 + 活跃用户）
"""
from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from .settings import settings

# 落盘文件路径（与 feedback.jsonl 同目录）
_LOG_DIR = Path(settings.DATA_DIR if hasattr(settings, 'DATA_DIR') else "runs")
_LOG_FILE = _LOG_DIR / "analytics.jsonl"

# 不记录的路径前缀（静态资源、健康探针等）
_SKIP = {"/health", "/assets", "/favicon.ico"}


class AnalyticsMiddleware(BaseHTTPMiddleware):
    """请求级埋点中间件：自动记录每次 API 调用。"""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        # 跳过不需要记录的路径
        if any(path.startswith(s) for s in _SKIP):
            return await call_next(request)

        start = time.time()
        response = await call_next(request)
        elapsed = round(time.time() - start, 3)

        # 提取用户名（从 Authorization header 解析 JWT sub；失败则匿名）
        username = _extract_user(request)

        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "user": username,
            "method": request.method,
            "path": path,
            "status": response.status_code,
            "elapsed_s": elapsed,
        }

        # 异步写入（不阻塞响应）
        _append(record)
        return response


def _extract_user(request: Request) -> str:
    """从 JWT token 提取用户名（轻量解析，不验证签名——签名已在 auth 层验证）。"""
    try:
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            return "anonymous"
        token = auth[7:]
        import base64
        # JWT 结构：header.payload.signature
        payload_b64 = token.split(".")[1]
        # 补 padding
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return payload.get("sub", "unknown")
    except Exception:  # noqa: BLE001
        return "anonymous"


def _append(record: dict):
    """追加一条记录到 JSONL 文件。"""
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        with _LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 - 统计不影响主流程
        pass


# ============================================================
# 汇总查询
# ============================================================
def get_summary() -> dict:
    """汇总统计数据。"""
    if not _LOG_FILE.exists():
        return {"total_calls": 0, "unique_users": 0, "message": "暂无使用记录"}

    records: list[dict] = []
    for line in _LOG_FILE.read_text(encoding="utf-8").splitlines():
        try:
            records.append(json.loads(line))
        except Exception:  # noqa: BLE001
            continue

    if not records:
        return {"total_calls": 0, "unique_users": 0, "message": "暂无使用记录"}

    total = len(records)
    users = set(r.get("user", "") for r in records) - {"anonymous", ""}
    user_calls = Counter(r.get("user", "anonymous") for r in records)
    path_calls = Counter(r.get("path", "") for r in records)
    elapsed_list = [r.get("elapsed_s", 0) for r in records if r.get("elapsed_s")]

    # 按天统计
    daily: dict[str, dict] = defaultdict(lambda: {"calls": 0, "users": set()})
    for r in records:
        day = r.get("ts", "")[:10]
        if day:
            daily[day]["calls"] += 1
            u = r.get("user", "")
            if u and u != "anonymous":
                daily[day]["users"].add(u)
    daily_summary = [
        {"date": d, "calls": v["calls"], "active_users": len(v["users"])}
        for d, v in sorted(daily.items(), reverse=True)
    ][:30]  # 最近 30 天

    return {
        "total_calls": total,
        "unique_users": len(users),
        "user_list": sorted(users),
        "user_calls": dict(user_calls.most_common(50)),
        "top_paths": dict(path_calls.most_common(20)),
        "avg_elapsed_s": round(sum(elapsed_list) / len(elapsed_list), 3) if elapsed_list else 0,
        "max_elapsed_s": round(max(elapsed_list), 3) if elapsed_list else 0,
        "daily": daily_summary,
        "first_record": records[0].get("ts", ""),
        "last_record": records[-1].get("ts", ""),
    }
