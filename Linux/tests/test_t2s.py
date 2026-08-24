"""验证繁→简：匹配层折叠 + 输出层统一简体。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compare_core.differ import run_diff
from compare_core.differ.normalize import normalize, to_simplified
from compare_core.models import Row


def main():
    # 1) 基础转换
    assert to_simplified("電線廠產認證標準") == "电线厂产认证标准", to_simplified("電線廠產認證標準")
    print("1) to_simplified OK:", to_simplified("電線廠產認證標準"))

    # 2) 匹配层折叠：繁/简写法归一
    assert normalize("電線組件") == normalize("电线组件"), (normalize("電線組件"), normalize("电线组件"))
    print("2) normalize 折叠繁简 OK")

    # 3) 两侧仅繁/简差异 → 应判为 SAME（而非 CHANGED/新增）
    orig = [Row(table=1, 关键件名称="電線組件", 型号="HL-007", 证书号="123", 制造商="威海泓淋")]
    plm = [Row(table=1, 关键件名称="电线组件", 型号="HL-007", 证书号="123", 制造商="威海泓淋")]
    diffs = run_diff(orig, plm, {})
    types = [d.type.value for d in diffs]
    print("3) 繁/简同件比对结果:", types)
    assert types == ["same"], types

    print("T2S_TEST_OK")


if __name__ == "__main__":
    main()
