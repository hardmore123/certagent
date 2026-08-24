"""Web 端到端验证：登录 → 上传两份真实东芝 doc → 轮询 → 取 diffs → 提交决策 → 下载。

验证三.23 定稿策略在 Web 链路生效：
- 来源标签（新增(PLM新版本)/旧版本保留/两侧(差异)/两侧）
- 电线组件组 ONLY_ORIG 保留、聚组
"""
import io
import time
from collections import Counter

import requests

BASE = "http://127.0.0.1:8000"
FOLDER = r"c:\Users\likunyuan\Desktop\项目\AI智能体-认证原始清单与新品清单合并"
ORIG = FOLDER + r"\输入--【原始清单，人工已整理docx】4720467-85Z970QF(东芝)_安全&EMC关键件清单.docx"
PLM = FOLDER + r"\输入--【PLM导出清单-新品docx】85ZXSF(01)(东芝)_安全&EMC关键件清单 - 副本.docx"


def main():
    s = requests.Session()

    # 1) 登录
    r = s.post(f"{BASE}/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    r.raise_for_status()
    token = r.json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    print("[1] 登录成功, token 长度", len(token))

    # 2) 上传
    with open(ORIG, "rb") as fo, open(PLM, "rb") as fp:
        files = {
            "file_orig": ("orig.docx", fo, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            "file_plm": ("plm.docx", fp, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        }
        r = s.post(f"{BASE}/api/v1/jobs", files=files, headers=h)
    r.raise_for_status()
    job_id = r.json()["job_id"]
    print("[2] 任务创建", job_id)

    # 3) 轮询到 review
    for _ in range(60):
        r = s.get(f"{BASE}/api/v1/jobs/{job_id}", headers=h)
        r.raise_for_status()
        st = r.json()
        if st["status"] in ("review", "failed", "done"):
            break
        time.sleep(1)
    print("[3] 状态", st["status"], "stage", st.get("stage"), "diff_count", st.get("diff_count"), "error", st.get("error"))
    if st["status"] == "failed":
        print("FAILED:", st.get("error"))
        return

    # 4) 取 diffs
    r = s.get(f"{BASE}/api/v1/jobs/{job_id}/diffs", headers=h)
    r.raise_for_status()
    diffs = r.json()
    print("[4] diffs 总数", len(diffs))
    print("    类型分布", dict(Counter(d["type"] for d in diffs)))
    print("    来源标签分布", dict(Counter(d["source_label"] for d in diffs)))

    # 电线组件相关
    wire = [d for d in diffs if "电线组件" in (d.get("关键件名称") or "")]
    print("    电线组件相关行:", len(wire))
    for d in wire[:15]:
        print(f"      {d['type']:<10} | {d['source_label']:<14} | {(d.get('关键件名称') or '')[:24]}")

    # CHANGED 样例（A/B 对比数据）
    changed = [d for d in diffs if d["type"] == "changed"]
    print("    CHANGED 行数:", len(changed))
    if changed:
        c = changed[0]
        print("      样例 orig_data:", c.get("orig_data"))
        print("      样例 plm_data :", c.get("plm_data"))
        print("      changed_fields:", c.get("changed_fields"))

    # 5) 全部接受，提交决策
    decisions = {d["key"]: "accept" for d in diffs}
    r = s.post(f"{BASE}/api/v1/jobs/{job_id}/decisions", json={"decisions": decisions}, headers=h)
    r.raise_for_status()
    res = r.json()
    print("[5] 提交决策后状态", res["status"])

    # 6) 下载
    r = s.get(f"{BASE}/api/v1/jobs/{job_id}/result/merged", headers=h)
    print("[6] 下载整合清单 HTTP", r.status_code, "字节", len(r.content))
    r2 = s.get(f"{BASE}/api/v1/jobs/{job_id}/result/compare", headers=h)
    print("    下载对照表 HTTP", r2.status_code, "字节", len(r2.content))

    # 7) 审计报告（/result 的 audit 字段）
    r3 = s.get(f"{BASE}/api/v1/jobs/{job_id}/result", headers=h)
    r3.raise_for_status()
    audit = r3.json().get("audit")
    print("[7] 审计报告 audit:", "无" if audit is None else "")
    if audit:
        print(f"    status={audit['status']} 输入A={audit['input_orig_rows']} 输入B={audit['input_plm_rows']}"
              f" 保留={audit['kept_count']} 输出={audit['output_rows']} mismatch={audit['output_mismatch']}")
        print(f"    引擎丢行={len(audit['lost_orig'])+len(audit['lost_plm'])}"
              f" 输出缺失={len(audit['missing_in_output'])} repaired={audit['repaired']}")
        print("    建议:", audit['recommendations'][0] if audit['recommendations'] else "")

    print("WEB_E2E_DONE")


if __name__ == "__main__":
    main()
