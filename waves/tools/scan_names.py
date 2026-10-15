"""python -X utf8 scan_names.py DIR [최소자카드=0.2]  ->  DIR/scan_names.txt
새 해(DIR/wave_days_ledger.json)의 장면 이름을 (1) 지금까지의 모든 장면 이름과 견주어 비슷한 쌍, (2) 범주·주제별로 묶어 보여 준다.
조립이 막는 기준(자카드 0.30)보다 낮은 쌍과 같은 주제 묶음을 눈으로 읽어 비슷한 장면을 찾는 용도다(다시 쓸 날을 고를 때 쓴다)."""
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

S = Path(__file__).resolve().parent
REPO = Path(os.environ.get("KYEON_REPO") or S / "kyeon-tools-wt")      # 저장소 위치(환경 변수 KYEON_REPO, 없으면 작업 폴더 안의 kyeon-tools-wt)
sys.path.insert(0, str(REPO / "tools"))
import dupcheck

d = S / sys.argv[1]
low = float(sys.argv[2]) if len(sys.argv) > 2 else 0.2
new = json.loads((d / "wave_days_ledger.json").read_text(encoding="utf-8"))
old = json.loads((S / "ledger_all.json").read_text(encoding="utf-8"))["scenes"]
old = {k: v for k, v in old.items() if k not in new}
new_names = {k: v["name"] for k, v in new.items()}
all_names = {k: v["name"] for k, v in old.items()} | new_names
rows = []
for j, a, b in dupcheck.similar_names(all_names, min_jaccard=low):
    if a in new or b in new:
        rows.append((j, a, b))
rows.sort(key=lambda r: -r[0])
out = [f"## 비슷한 이름 (자카드 {low} 이상)"]
for j, a, b in rows:
    out.append(f"{j:.2f} {a} {all_names[a]} | {b} {all_names[b]}")
groups = defaultdict(list)
for k, v in new.items():
    groups[(v["category"], v.get("theme") or "")].append(int(k))
for (c, t), ds in sorted(groups.items()):
    if len(ds) < 2:
        continue
    out.append(f"## {c} / {t}")
    for k in sorted(ds):
        out.append(f"   {k} {new_names[str(k)]}")
(d / "scan_names.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
print("쌍", len(rows), "묶음", sum(1 for v in groups.values() if len(v) >= 2))
