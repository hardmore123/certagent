"""验证 core `MockSuggester.summarize_from_groups()` 与 tests 原型输出一致。

链路：`Row → run_group_diff → MockSuggester.summarize_from_groups → list[ChangeEntry]`
对比：`Row → build_group_summary → group_summarize_mock（tests 原型）`
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from compare_core.differ import run_group_diff  # noqa: E402
from compare_core.models import Row  # noqa: E402
from compare_core.suggester import get_suggester  # noqa: E402

from experiment_group_suggest import (  # noqa: E402
    EXPECTED_TEMPLATE, group_summarize_mock, match_expected,
)
from prototype_group_aggregation import build_group_summary  # noqa: E402

ORIG_JSON = ROOT / "runs" / "merge_folder" / "orig.json"
PLM_JSON = ROOT / "runs" / "merge_folder" / "plm.json"


def _load(path: Path) -> list[Row]:
    return [Row.model_validate(x) for x in json.loads(path.read_text(encoding="utf-8"))]


def main() -> None:
    orig = _load(ORIG_JSON)
    plm = _load(PLM_JSON)

    # core 版
    group_diffs = run_group_diff(orig, plm)
    mock = get_suggester("mock")
    core_entries = mock.summarize_from_groups(group_diffs, rules={})
    core_match = match_expected(core_entries, EXPECTED_TEMPLATE)

    # tests 原型
    summary = build_group_summary(orig, plm)
    proto_entries = group_summarize_mock(summary)
    proto_match = match_expected(proto_entries, EXPECTED_TEMPLATE)

    print(f"core  条目: {len(core_entries)}, 业务模板覆盖: {core_match['matched']}/{core_match['expected_total']}")
    print(f"proto 条目: {len(proto_entries)}, 业务模板覆盖: {proto_match['matched']}/{proto_match['expected_total']}")

    # 结构必须一致（条目数 + 变更项目字段）
    struct_ok = (
        len(core_entries) == len(proto_entries)
        and all(a.变更项目 == b.变更项目 for a, b in zip(core_entries, proto_entries))
    )
    assert struct_ok, f"结构不一致: core条目={len(core_entries)}, proto条目={len(proto_entries)}"
    assert core_match["matched"] == 5, f"core 未达 5/5 覆盖：{core_match}"

    # 展示层字符差异：core 保留原字符（PCB、ICX、53772-A），proto 全 normalize 后展示
    char_diffs = sum(1 for a, b in zip(core_entries, proto_entries) if a.变更后 != b.变更后)
    if char_diffs:
        print(f"ℹ️ {char_diffs} 条的'变更后'字符串有差异 —— core 保留原字符（大小写+全角标点），proto 全 lowercase")
    else:
        print("✅ 字符层也完全一致")

    print("SMOKE_GROUP_SUMMARY_DONE")


if __name__ == "__main__":
    main()
