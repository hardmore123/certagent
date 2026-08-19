"""实验 2：组级 diff → 真 LLM 归纳对照表（只读，环境未配时优雅降级）。

只读实验，不改主流程：
- 复用 `prototype_group_aggregation.build_group_summary()` 得到 43 组
- 复用 `LLMSuggester` 的 HTTP 调用与 JSON 解析
- 新 prompt：把组级 diff + 5 类业务模板一起塞给 LLM
- LLM 环境（`LLM_BASE_URL/LLM_API_KEY/LLM_MODEL`）未配置时明确报告并回退组级 Mock

产物：`runs/exp_group_llm_2026-07-28/`
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))


def _load_env_file() -> Path | None:
    """在导入 config 前手动加载 `list-merge-demo/.env`（避免 python-dotenv 依赖）。"""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return None
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:  # 已有的环境变量优先
            os.environ[key] = value
    return env_path


_ENV_LOADED_FROM = _load_env_file()

from compare_core.config import config  # noqa: E402
from compare_core.models import ChangeEntry  # noqa: E402
from compare_core.suggester.llm_suggester import LLMSuggester, _parse_changes  # noqa: E402

from experiment_group_suggest import (  # noqa: E402
    EXPECTED_TEMPLATE, group_summarize_mock, match_expected,
)
from prototype_group_aggregation import (  # noqa: E402
    ORIG_JSON, PLM_JSON, build_group_summary, load_rows,
)

DEFAULT_OUT_DIR = ROOT / "runs" / "exp_group_llm_2026-07-28"
OUT_DIR = DEFAULT_OUT_DIR  # 会在 main() 里按模型名重写

PROMPT_TEMPLATE = """你是产品认证工程师助手。以下是关键件清单在 CCC 变更-开发场景下的"关键件组级差异"，每组代表一个业务操作单元（同一表号 + 分组标题 + 关键件名称下的多款选型集合）。

## 任务
把这些组级差异归纳为"变更前后对照表"的业务变更项，**严格按下面 5 类业务模板输出，每一类都必须出现一条 entry，共必须 5 条**（即使某类没有对应的组，也要按下述规则输出）。

## 5 类业务模板

1. **增加产品型号规格**：表 2（本次机型主项表）的机型换型（显示屏/主板/机内电源单元/中央处理单元 等主项型号变化）。归纳所有 `table=2` 且 `status ≠ SAME_GROUP` 的组。
2. **增加机内电源单元备选件**：表 1 分组标题含"电源单元"下的子件变化。归纳所有 `table=1` 且 `group` 含 "电源单元" 且 `status ≠ SAME_GROUP` 的组，说明整机内电源单元换型和新增子件款数。
3. **增加主板（含网卡、调谐单元、天线隔离器）备选件**：表 1 顶层组（`group=""`）里名字含 主板/PCB/调谐/天线/网卡/显示屏 的组变化。归纳所有相关组。
4. **补充/更新供应商信息**：REPLACED_GROUP 且行数不变、少量替换供应商的组（同型号换生产企业）；或非主板/电源单元类的选型级替换。
5. **增加整机外观、内部结构、主板、电源板等照片**：本清单不可推导。**即使清单里没有对应数据，也必须输出这一条**，"变更后"字段固定填 `[外部输入] 需业务提供整机外观、内部结构、主板、电源板等照片`。

## 硬约束（违反视为失败）
- **总条目数必须等于 5**（每个模板对应一条，顺序按模板 1→5）
- **每个非 SAME_GROUP 组都必须出现在某一条 entry 的"变更后"里**（可以是聚合表达，不必逐行；但组的名字或子件类别必须被提及）
- **若某类无对应组**（如清单中确实没有对应主板变更），"变更后"字段填 `本次无相关组变更`；但类别 5 照片类除外，永远填 `[外部输入]` 占位
- 变更前统一填 `见原报告`
- 变更后描述"变更了什么"，可以列举子件类别和款数、供应商替换家数、机型换型对应关系（如"53772-A → 55431-F"），但不要罗列具体型号字符串
- 只依据给定组级差异，禁止编造清单中不存在的关键件
- 严格只输出 JSON，格式：`{{"changes": [{{"变更项目": "...", "变更前": "见原报告", "变更后": "..."}}]}}`

## 组级差异字段说明
- `table`：1=主清单，2=机型主项表
- `group`：分组标题（例如 "55431-F 内电源单元上元器件"；空串表示顶层组）
- `name`：关键件名称
- `status`：SAME_GROUP / REPLACED_GROUP / EXTENDED_BY_PLM / SHRUNK_BY_PLM / ONLY_ORIG_GROUP / ONLY_PLM_GROUP
- `orig_selections` / `plm_selections`：原报告 / PLM 各自的选型数
- `common / only_orig / only_plm`：选型多重集的交集与两侧独有数

## 输出前的自检
1. `changes` 数组长度是否等于 5？
2. 类别 5（照片）的"变更后"是否为 `[外部输入] ...`？
3. 检查输入里所有 `status ≠ SAME_GROUP` 的组：每一个是否都被至少一条 entry 覆盖了？

## 组级差异（JSON）
{groups_json}
"""


def _pack_groups(summary: list[dict]) -> list[dict]:
    """给 LLM 的最小载荷：非 SAME_GROUP 组 + 必要字段。"""
    return [
        {
            "table": g["table"],
            "group": g["group"],
            "name": g["name"],
            "status": g["status"],
            "orig_selections": g["orig_selections"],
            "plm_selections": g["plm_selections"],
            "common": g["common_selections"],
            "only_orig": g["only_orig_selections"],
            "only_plm": g["only_plm_selections"],
        }
        for g in summary if g["status"] != "SAME_GROUP"
    ]


def _llm_available() -> bool:
    return bool(config.LLM_BASE_URL and config.LLM_API_KEY and config.LLM_MODEL)


def _preflight_check() -> dict:
    """打 /chat/completions 用最小 payload 探测认证方式。

    同时尝试三种常见 header：
    - Authorization: Bearer <key>（OpenAI 兼容）
    - apikey: <key>（APISIX key-auth 默认）
    - X-API-Key: <key>
    把每种方式的 status_code + 服务器响应片段都记录下来，用户可以对着看哪种通。
    """
    import requests

    key = config.LLM_API_KEY or ""
    info: dict = {
        "attempted": True,
        "local_key_length": len(key),
        "local_key_tail4": key[-4:] if len(key) >= 4 else "",
        "local_key_prefix4": key[:4] if len(key) >= 4 else "",
        "auth_variants": [],
    }

    url = config.LLM_BASE_URL.rstrip("/") + "/chat/completions"
    body = {
        "model": config.LLM_MODEL,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 4,
        "temperature": 0,
    }
    variants = [
        ("Authorization: Bearer", {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}),
        ("apikey", {"apikey": key, "Content-Type": "application/json"}),
        ("X-API-Key", {"X-API-Key": key, "Content-Type": "application/json"}),
    ]
    for label, headers in variants:
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=6)
            info["auth_variants"].append({
                "auth_style": label,
                "status_code": resp.status_code,
                "ok": resp.ok,
                "body_head": resp.text[:400],
            })
        except Exception as e:  # noqa: BLE001
            info["auth_variants"].append({"auth_style": label, "error": str(e)[:200]})

    # 任一 variant 通就算 ok
    info["ok"] = any(v.get("ok") for v in info["auth_variants"])
    return info


def summarize_via_llm(summary: list[dict], skip_preflight: bool = False) -> tuple[list[ChangeEntry], dict]:
    """调 LLM 归纳；返回 (entries, diagnostic)。"""
    payload = _pack_groups(summary)
    prompt = PROMPT_TEMPLATE.format(groups_json=json.dumps(payload, ensure_ascii=False, indent=2))
    diag = {
        "llm_available": _llm_available(),
        "prompt_chars": len(prompt),
        "payload_groups": len(payload),
        "model": config.LLM_MODEL,
        "base_url": config.LLM_BASE_URL,
        "env_loaded_from": str(_ENV_LOADED_FROM) if _ENV_LOADED_FROM else None,
        "skip_preflight": skip_preflight,
    }
    if not _llm_available():
        diag["status"] = "skipped_no_env"
        return [], diag

    if not skip_preflight:
        diag["preflight"] = _preflight_check()
        if not diag["preflight"].get("ok"):
            diag["status"] = "preflight_failed"
            return [], diag

    try:
        llm = LLMSuggester()
        print(f"[step] calling {config.LLM_MODEL}...", flush=True)
        raw = llm._call_llm(prompt)  # 复用现成的 HTTP + 重试 + JSON mode
        diag["status"] = "ok"
        diag["raw_chars"] = len(raw)
        entries = _parse_changes(raw)
        diag["parsed_entries"] = len(entries)
        return entries, diag
    except Exception as e:  # noqa: BLE001
        diag["status"] = "error"
        diag["error"] = str(e)[:300]
        return [], diag


def main() -> None:
    parser = argparse.ArgumentParser(description="组级 diff → LLM 归纳实验")
    parser.add_argument("--model", default=None,
                        help="覆盖 .env 里的 LLM_MODEL（如 deepseek-v4-pro）")
    parser.add_argument("--out-dir", default=None,
                        help="产物目录（默认按模型名命名）")
    parser.add_argument("--skip-preflight", action="store_true",
                        help="跳过三种认证方式探测（Flash 已经验证过时可用）")
    args = parser.parse_args()

    if args.model:
        os.environ["LLM_MODEL"] = args.model
        # 反射到 config 单例
        from compare_core.config import config as _cfg
        _cfg.LLM_MODEL = args.model

    model_slug = (args.model or config.LLM_MODEL or "unknown").replace(":", "_").replace("/", "_")
    global OUT_DIR
    OUT_DIR = Path(args.out_dir) if args.out_dir else (ROOT / "runs" / f"exp_group_llm_2026-07-28_{model_slug}")

    print(f"[step] main start (model={config.LLM_MODEL}, out={OUT_DIR})", flush=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("[step] loading orig/plm", flush=True)
    orig = load_rows(ORIG_JSON)
    plm = load_rows(PLM_JSON)
    summary = build_group_summary(orig, plm)

    print("[step] preflight & llm call...", flush=True)
    llm_entries, llm_diag = summarize_via_llm(summary, skip_preflight=args.skip_preflight)
    print(f"[step] llm done: status={llm_diag.get('status')}", flush=True)
    llm_match = match_expected(llm_entries, EXPECTED_TEMPLATE) if llm_entries else None

    mock_entries = group_summarize_mock(summary)
    mock_match = match_expected(mock_entries, EXPECTED_TEMPLATE)

    result = {
        "llm_diagnostic": llm_diag,
        "expected_template": EXPECTED_TEMPLATE,
        "group_based_llm": {
            "count": len(llm_entries),
            "coverage": llm_match,
            "entries": [e.model_dump() for e in llm_entries],
        },
        "group_based_mock_baseline": {
            "count": len(mock_entries),
            "coverage": mock_match,
            "entries": [e.model_dump() for e in mock_entries],
        },
    }
    (OUT_DIR / "experiment.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT_DIR / "prompt.txt").write_text(
        PROMPT_TEMPLATE.format(groups_json=json.dumps(_pack_groups(summary), ensure_ascii=False, indent=2)),
        encoding="utf-8",
    )

    lines = [
        "# 实验 2：组级 diff → 真 LLM 归纳对照表（只读）",
        "",
        "> 输入：`runs/merge_folder/orig.json` + `plm.json`；LLM prompt 见同目录 `prompt.txt`。",
        "",
        "## LLM 调用诊断",
        "",
        f"- 环境可用：{llm_diag['llm_available']}",
        f"- Base URL：`{llm_diag['base_url'] or '(未配置)'}`",
        f"- 模型：`{llm_diag['model'] or '(未配置)'}`",
        f"- `.env` 加载来源：`{llm_diag['env_loaded_from'] or '(未加载)'}`",
        f"- Prompt 字数：{llm_diag['prompt_chars']}",
        f"- 输入组数：{llm_diag['payload_groups']}",
        f"- 执行状态：`{llm_diag['status']}`",
    ]
    if "error" in llm_diag:
        lines.append(f"- 错误：{llm_diag['error']}")
    if "preflight" in llm_diag:
        pf = llm_diag["preflight"]
        lines.append(f"- **预检查（三种认证方式）**：整体 ok={pf.get('ok')}")
        for v in pf.get("auth_variants", []):
            style = v.get("auth_style")
            if v.get("error"):
                lines.append(f"  - `{style}`：异常 {v['error']}")
            else:
                lines.append(f"  - `{style}`：status={v.get('status_code')} ok={v.get('ok')}")
    if "raw_chars" in llm_diag:
        lines.append(f"- 返回字数：{llm_diag['raw_chars']}")
    if "parsed_entries" in llm_diag:
        lines.append(f"- 解析条目：{llm_diag['parsed_entries']}")
    lines.append("")

    if llm_diag["status"] == "skipped_no_env":
        lines += [
            "## LLM 未配置 · 使用说明",
            "",
            "本次未调用 LLM。请按下列步骤配置后重跑：",
            "",
            "1. 复制 `.env.example` 为 `.env`",
            "2. 填入 `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`",
            "3. 在同一 shell 里加载环境变量（PowerShell 用 `Get-Content .env | ForEach-Object { ... }`，"
            "或用 `python-dotenv` 自动加载）",
            "4. 重跑：`python tests\\experiment_group_llm.py`",
            "",
            "**当前脚本已把完整 prompt 输出到 `prompt.txt`**，如需人工在其他 LLM UI 上试跑，"
            "可直接复制粘贴该 prompt。",
            "",
        ]

    if llm_entries:
        lines += [
            "## LLM 归纳条目",
            "",
        ]
        for i, e in enumerate(llm_entries, 1):
            lines += [
                f"### {i}. {e.变更项目}",
                "",
                f"- 变更前：{e.变更前}",
                f"- 变更后：{e.变更后}",
                "",
            ]
        lines.append("### LLM 归纳的业务模板覆盖")
        lines.append("")
        for m in (llm_match["detail"] if llm_match else []):
            icon = "✓" if m["matched_entry"] else "✗"
            lines.append(f"- {icon} `{m['expected']}` → `{m['matched_entry']}`")
        lines.append("")

    lines += [
        "## 组级 Mock 基线（同样输入下的规则归纳）",
        "",
        f"- 条目数：{len(mock_entries)}",
        f"- 业务模板覆盖：{mock_match['matched']}/{mock_match['expected_total']}",
        "",
    ]
    for i, e in enumerate(mock_entries, 1):
        lines += [
            f"{i}. **{e.变更项目}**",
            f"   - 变更后：{e.变更后}",
        ]

    (OUT_DIR / "experiment.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("LLM 环境可用:", llm_diag["llm_available"])
    print("LLM 状态:", llm_diag["status"])
    if llm_entries:
        print(f"LLM 归纳: {len(llm_entries)} 条，覆盖 {llm_match['matched']}/{llm_match['expected_total']}")
    print(f"Mock 基线: {len(mock_entries)} 条，覆盖 {mock_match['matched']}/{mock_match['expected_total']}")
    print("产物:", OUT_DIR)
    print("EXP_GROUP_LLM_DONE")


if __name__ == "__main__":
    main()
