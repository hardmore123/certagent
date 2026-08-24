"""真 LLM suggester：OpenAI 兼容接口，限定结构化 JSON 输出，强容错，失败回退 mock。

两条归纳路径：
- summarize_changes：老路径，喂行级 diff 让 LLM 按关键件聚合（PRD 早期设计）
- summarize_from_groups：新路径，喂组级 diff 让 LLM 按业务 5 类模板归纳（三.12 实验验证）
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from ..config import config
from ..differ import to_llm_payload
from ..models import ChangeEntry, DiffItem, DiffType, GroupDiff
from .mock_suggester import MockSuggester

_PROMPT_DIR = Path(__file__).parent / "prompts"
_PROMPT = (_PROMPT_DIR / "change_summary.txt").read_text(encoding="utf-8")
_GROUP_PROMPT = (_PROMPT_DIR / "group_summary.txt").read_text(encoding="utf-8")

# LLM 流式响应熔断参数：推理模型（deepseek-v4-flash）思考过程可能很长，
# 仅保留 wall-clock 总超时硬性截断，避免任务无限卡死。
_LLM_TOTAL_TIMEOUT = 120.0          # wall-clock 总超时（秒）


class _LLMAbort(Exception):
    """LLM 流式响应熔断（总超时 / 思考量膨胀）：不再重试，直接回退。"""


def _repair_json(text: str) -> str:
    """去掉 ```json 围栏、截取第一个 {...}。"""
    t = text.strip()
    t = re.sub(r"^```(?:json)?", "", t).strip()
    t = re.sub(r"```$", "", t).strip()
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end != -1 and end > start:
        t = t[start : end + 1]
    return t


def _parse_changes(text: str) -> list[ChangeEntry]:
    """多层容错解析 LLM 输出为 ChangeEntry 列表。"""
    for candidate in (text, _repair_json(text)):
        try:
            data = json.loads(candidate)
            items = data.get("changes", data) if isinstance(data, dict) else data
            out = []
            for it in items:
                out.append(ChangeEntry(
                    变更项目=str(it.get("变更项目", "")).strip(),
                    变更前=str(it.get("变更前", "见原报告")).strip() or "见原报告",
                    变更后=str(it.get("变更后", "")).strip(),
                ))
            if out:
                return out
        except Exception:  # noqa: BLE001
            continue
    raise ValueError("LLM 输出无法解析为 ChangeEntry")


class LLMSuggester:
    def summarize_changes(self, diffs: list[DiffItem], rules: dict) -> list[ChangeEntry]:
        payload = [
            {"类型": d.type.value, "关键件名称": (d.plm or d.orig).关键件名称,
             "型号": (d.plm or d.orig).型号, "规格材料": (d.plm or d.orig).规格材料,
             "生产企业": (d.plm or d.orig).生产企业, "制造商": (d.plm or d.orig).制造商,
             "变更字段": d.changed_fields}
            for d in diffs if d.type in (DiffType.ONLY_PLM, DiffType.CHANGED) and (d.plm or d.orig)
        ]
        if not payload:
            return []
        prompt = _PROMPT.format(
            categories="\n".join(rules.get("change_categories", [])),
            diffs=json.dumps(payload, ensure_ascii=False),
        )
        try:
            raw = self._call_llm(prompt)
            from ..trace import dump

            dump("suggest_llm_raw", {"prompt": prompt, "raw": raw})
            return _parse_changes(raw)
        except Exception as e:  # noqa: BLE001 - LLM 不可信，回退 mock
            print(f"[llm] 失败回退 mock：{e}")
            return MockSuggester().summarize_changes(diffs, rules)

    def summarize_from_groups(self, group_diffs: list[GroupDiff], rules: dict) -> list[ChangeEntry]:
        """组级 diff → 业务 5 类模板归纳（三.12 实验路径，5/5 覆盖）。"""
        payload = to_llm_payload(group_diffs, drop_same=True)
        if not payload:
            return []
        prompt = _GROUP_PROMPT.format(groups_json=json.dumps(payload, ensure_ascii=False, indent=2))
        try:
            raw = self._call_llm(prompt)
            from ..trace import dump

            dump("suggest_group_llm_raw", {"prompt_chars": len(prompt), "raw": raw})
            return _parse_changes(raw)
        except Exception as e:  # noqa: BLE001
            print(f"[llm][group] 失败回退 mock：{e}")
            return MockSuggester().summarize_from_groups(group_diffs, rules)

    def propose_fuzzy_pairs(self, unmatched_orig, unmatched_plm):
        """fuzzy 候选提名：对两级匹配后的残余候选池，让 LLM 提名"疑似同一件"的配对。

        返回 [(orig_index, plm_index, confidence, reason), ...]；LLM 只提名不决策，
        最终由 diff_engine 守恒护栏过滤 + 人工确认页确认。失败返回 []（不影响主流程）。
        """
        if not unmatched_orig or not unmatched_plm:
            return []

        def _brief(rows):
            out = []
            for i, r in enumerate(rows):
                out.append({"index": i, "表": r.table, "分组": r.group,
                            "关键件名称": r.关键件名称, "型号": r.型号, "规格材料": r.规格材料})
            return out

        prompt = (
            "你是认证关键件清单比对助手。下面是两份清单里【规则未能配对】的残余行：\n"
            "A（旧版本/原始清单）候选：\n" + json.dumps(_brief(unmatched_orig), ensure_ascii=False) + "\n"
            "B（新版本/PLM导出）候选：\n" + json.dumps(_brief(unmatched_plm), ensure_ascii=False) + "\n\n"
            "任务：判断 A、B 中是否存在【指同一个物料】的行对（可能是详略写法/同义词/缩写全称"
            "/参数顺序不同，如『电线组件』与『电线组件(0.5平方毫米线径…)』）。\n"
            "严格要求：\n"
            "1. 只在【同一表号且同一分组】内配对；不确定就不要配。\n"
            "2. 只输出你有把握是同一物料的配对，宁缺毋滥。\n"
            "3. 每个 A、B 行最多出现在一个配对里。\n"
            '输出 JSON：{"pairs":[{"orig_index":整数,"plm_index":整数,'
            '"confidence":0到1的小数,"reason":"简短理由"}]}，无配对则 {"pairs":[]}。'
        )
        try:
            raw = self._call_llm(prompt)
            from ..trace import dump
            dump("fuzzy_propose_raw", {"n_orig": len(unmatched_orig), "n_plm": len(unmatched_plm), "raw": raw})
            data = json.loads(_repair_json(raw))
            pairs = data.get("pairs", []) if isinstance(data, dict) else []
            out = []
            for it in pairs:
                try:
                    out.append((int(it["orig_index"]), int(it["plm_index"]),
                                float(it.get("confidence", 0)), str(it.get("reason", ""))))
                except Exception:  # noqa: BLE001
                    continue
            return out
        except Exception as e:  # noqa: BLE001
            print(f"[llm][fuzzy] 提名失败：{e}")
            return []

    def _call_llm(self, prompt: str) -> str:
        """调用 OpenAI 兼容接口。

        聚好看 higpt 网关特性：
        - 需要 user_key 作为 query 参数（?user_key=...）
        - 强制流式返回，故统一 stream=True 并累积 delta 内容
        JSON 约束靠 prompt + _parse_changes/_repair_json 保证（网关不一定支持 response_format）。
        """
        import requests  # 延迟导入

        if not (config.LLM_BASE_URL and config.LLM_API_KEY and config.LLM_MODEL):
            raise RuntimeError("LLM 环境变量未配置（LLM_BASE_URL/LLM_API_KEY/LLM_MODEL）")
        url = config.LLM_BASE_URL.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {config.LLM_API_KEY}", "Content-Type": "application/json"}
        params = {"user_key": config.LLM_USER_KEY} if config.LLM_USER_KEY else {}
        body = {
            "model": config.LLM_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "stream": True,
        }
        last = None
        for attempt in range(config.LLM_MAX_RETRY + 1):
            try:
                resp = requests.post(url, headers=headers, params=params, json=body,
                                     timeout=config.LLM_TIMEOUT, stream=True)
                resp.raise_for_status()
                content = _read_sse_stream(resp, deadline=time.time() + _LLM_TOTAL_TIMEOUT)
                if content:
                    return content
                raise RuntimeError("LLM 流式响应为空")
            except _LLMAbort as e:
                # 熔断（总超时/思考量膨胀）说明模型处于异常状态，重试大概率同样异常，直接放弃回退
                last = e
                break
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(3 * (attempt + 1))
        raise RuntimeError(f"LLM 调用失败：{last}")


def _read_sse_stream(resp, deadline: float) -> str:
    """累积 OpenAI 兼容的流式响应内容。

    兼容两种返回：
    - SSE 流：逐行 `data: {json}`，取 choices[0].delta.content 累积，遇 [DONE] 结束
    - 非流式 JSON（网关未真正流式时）：整体解析，取 choices[0].message.content

    熔断保护：仅 wall-clock 总超时（超过 deadline 抛 _LLMAbort）。
    reasoning_content 不再限长——推理模型思考过程长是正常的，宁可等它想完，
    由 120s 墙钟超时兜底即可。
    """
    parts: list[str] = []
    for line in resp.iter_lines(decode_unicode=True):
        if time.time() > deadline:
            raise _LLMAbort(f"LLM 流式响应超过总超时 {_LLM_TOTAL_TIMEOUT:.0f}s")
        if not line:
            continue
        data = line[5:].strip() if line.startswith("data:") else line.strip()
        if data == "[DONE]":
            break
        try:
            obj = json.loads(data)
        except Exception:  # noqa: BLE001
            continue
        choices = obj.get("choices") or []
        if not choices:
            continue
        ch = choices[0]
        delta = ch.get("delta") or {}
        piece = delta.get("content") or (ch.get("message") or {}).get("content")
        if piece:
            parts.append(piece)
    return "".join(parts)
