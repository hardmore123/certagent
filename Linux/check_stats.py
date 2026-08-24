"""一键查看使用统计（管理员用）。

用法：python check_stats.py
自动登录 → 拿 token → 查 /api/v1/analytics → 打印汇总。
"""
import json
import requests

BASE = "http://localhost:8000/api/v1"
USERNAME = "admin"
PASSWORD = "admin"  # 改成你的实际密码


def main():
    # 1. 登录拿 token
    r = requests.post(f"{BASE}/auth/login", json={"username": USERNAME, "password": PASSWORD})
    if r.status_code != 200:
        print(f"登录失败：{r.status_code} {r.text}")
        return
    token = r.json()["token"]

    # 2. 带 token 查统计
    r = requests.get(f"{BASE}/analytics", headers={"Authorization": f"Bearer {token}"})
    if r.status_code != 200:
        print(f"查询失败：{r.status_code} {r.text}")
        return

    data = r.json()
    print("=" * 50)
    print("📊 CertAgent 使用统计")
    print("=" * 50)
    print(f"总调用次数：{data.get('total_calls', 0)}")
    print(f"独立用户数：{data.get('unique_users', 0)}")
    print(f"用户列表：  {', '.join(data.get('user_list', []))}")
    print(f"平均响应：  {data.get('avg_elapsed_s', 0)}s")
    print(f"最大响应：  {data.get('max_elapsed_s', 0)}s")
    print(f"记录范围：  {data.get('first_record', '')} ~ {data.get('last_record', '')}")

    print("\n── 各用户调用次数 ──")
    for user, count in (data.get("user_calls") or {}).items():
        print(f"  {user:20s} {count}")

    print("\n── 接口排行 (Top 10) ──")
    for path, count in list((data.get("top_paths") or {}).items())[:10]:
        print(f"  {path:50s} {count}")

    print("\n── 每日统计 ──")
    print(f"  {'日期':12s} {'调用量':>8s} {'活跃用户':>8s}")
    for d in (data.get("daily") or []):
        print(f"  {d['date']:12s} {d['calls']:>8d} {d['active_users']:>8d}")

    print("\n完整 JSON 已保存到 runs/stats_latest.json")
    with open("runs/stats_latest.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
