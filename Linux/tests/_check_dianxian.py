import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from compare_core.differ.normalize import normalize

orig = json.loads((ROOT/"runs/merge_folder/orig.json").read_text(encoding="utf-8"))
plm = json.loads((ROOT/"runs/merge_folder/plm.json").read_text(encoding="utf-8"))

print("=== orig 中含'电线组件'的行 ===")
for r in orig:
    if "电线组件" in r.get("关键件名称", ""):
        print(f"  group={r['group']!r}")
        print(f"  name={r['关键件名称']!r}")
        print(f"  model={r['型号'][:80]!r}")
        print(f"  norm_name={normalize(r['关键件名称'])!r}")
        print()

print("=== plm 中含'电线组件'的行（前3条）===")
count = 0
for r in plm:
    if "电线组件" in r.get("关键件名称", ""):
        count += 1
        if count <= 3:
            print(f"  group={r['group']!r}")
            print(f"  name={r['关键件名称']!r}")
            print(f"  model={r['型号'][:80]!r}")
            print(f"  norm_name={normalize(r['关键件名称'])!r}")
            print()
print(f"  (plm 电线组件总行数: {count})")

# 检查包含关系
orig_name = [r["关键件名称"] for r in orig if "电线组件" in r.get("关键件名称", "")]
plm_name = [r["关键件名称"] for r in plm if "电线组件" in r.get("关键件名称", "")]
if orig_name and plm_name:
    na = normalize(orig_name[0])
    nb = normalize(plm_name[0])
    print(f"\nnorm orig: {na!r}")
    print(f"norm plm:  {nb!r}")
    print(f"orig in plm: {na in nb}")
    print(f"plm in orig: {nb in na}")
    print(f"len ratio: {len(na)}/{len(nb)} = {len(na)/len(nb):.2f}")
