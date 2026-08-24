"""诊断：型号集合匹配（第 2.5 趟）是否导致 PLM 侧残余候选被清零、fuzzy 无活干。用完可删。"""
import copy
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from compare_core.parser import parse_docx
from compare_core.differ import run_diff
from compare_core.rules import load_rules

ORIG = r"C:\Users\likunyuan\Desktop\项目\AI智能体-认证原始清单与新品清单合并\输入--【原始清单，人工已整理docx】4720467-85Z970QF(东芝)_安全&EMC关键件清单.docx"
PLM = r"C:\Users\likunyuan\Desktop\项目\AI智能体-认证原始清单与新品清单合并\输入--【PLM导出清单-新品docx】85ZXSF(01)(东芝)_安全&EMC关键件清单 - 副本.docx"

orig = parse_docx(ORIG)
plm = parse_docx(PLM)
print(f"rows: orig={len(orig)} plm={len(plm)}")

rules = load_rules()
print("rules 里的 model_set_match 配置:", rules.get("model_set_match"))

# 默认（型号集合匹配启用）
d1 = run_diff(orig, plm, rules)
c1 = Counter(d.type.value for d in d1)
print(f"\n[默认/启用型号集合匹配] diff 总数={len(d1)} 分布={dict(c1)}")
print(f"  -> PLM未匹配(only_plm)={c1.get('only_plm', 0)}  orig未匹配(only_orig)={c1.get('only_orig', 0)}")

# 禁用型号集合匹配
rules_off = copy.deepcopy(rules)
rules_off.setdefault("model_set_match", {})["enabled"] = False
d2 = run_diff(orig, plm, rules_off)
c2 = Counter(d.type.value for d in d2)
print(f"\n[禁用型号集合匹配] diff 总数={len(d2)} 分布={dict(c2)}")
print(f"  -> PLM未匹配(only_plm)={c2.get('only_plm', 0)}  orig未匹配(only_orig)={c2.get('only_orig', 0)}")

print("\n===== 结论 =====")
print(f"启用型号集合匹配时，PLM 侧残余候选 = {c1.get('only_plm', 0)} 行")
print(f"禁用型号集合匹配时，PLM 侧残余候选 = {c2.get('only_plm', 0)} 行")
print("（fuzzy 第三趟要求 PLM 侧和 orig 侧都有残余才调 LLM）")
