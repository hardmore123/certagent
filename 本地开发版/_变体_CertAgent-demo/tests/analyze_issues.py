"""量化两个问题：① 按(名称+型号)去重导致的行丢失；② 繁体字出现情况。"""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compare_core.differ.normalize import normalize
from compare_core.parser import load_rows_json

BASE = Path(__file__).resolve().parent.parent / "runs" / "parse_real"

# 少量常见繁体字（够确认是否存在，非完整表）
TRAD = set("電廠產認證導線灣溫濕標準檢測過壓器機關聯結構開關電網絡類無線")


def main():
    for tag in ["orig", "plm"]:
        rows = load_rows_json(str(BASE / f"{tag}.json"))
        t1 = [r for r in rows if r.table == 1]
        # ① 去重丢失量
        keys = [f"{normalize(r.关键件名称)}|{normalize(r.型号)}" for r in t1]
        c = Counter(keys)
        uniq = len(c)
        dup_rows = sum(v - 1 for v in c.values() if v > 1)
        dup_keys = sum(1 for v in c.values() if v > 1)
        print(f"\n[{tag}] 表1行数={len(t1)}  唯一(名称+型号)键={uniq}  "
              f"→ 当前逻辑会丢失 {dup_rows} 行（{dup_keys} 个键出现重复）")
        # 举例最重复的键
        for k, v in c.most_common(3):
            if v > 1:
                print(f"    重复键 x{v}: {k[:50]}")
        # ② 繁体字扫描
        trad_hits = []
        for r in t1:
            for f in ["关键件名称", "型号", "规格材料", "制造商", "生产企业"]:
                val = getattr(r, f, "") or ""
                found = TRAD & set(val)
                if found:
                    trad_hits.append((f, "".join(found), val[:30]))
        print(f"[{tag}] 繁体字命中行次: {len(trad_hits)}")
        for f, chars, sample in trad_hits[:5]:
            print(f"    {f} 含[{chars}]: {sample}")
    print("\nANALYZE_DONE")


if __name__ == "__main__":
    main()
