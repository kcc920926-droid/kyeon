"""해 폴더의 해설에서 아무 블록이든 정확히 한 군데를 바꾼다(rp.py apply 는 '오늘'만 바꾼다).
python -X utf8 blockfix.py DIR FIX.json     FIX = {"일차": [["옛 문장", "새 문장"], ...]}"""
import json
import sys
from pathlib import Path

d = Path(sys.argv[1])
fix = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
done, miss = 0, []
for cp in sorted(d.glob("commentary_*.json")):
    cs = json.loads(cp.read_text(encoding="utf-8"))
    changed = False
    for c in cs:
        for old, new in fix.get(str(c["day"]), []):
            hits = [b for b in c["blocks"] if old in b["text"]]
            n = sum(b["text"].count(old) for b in c["blocks"])
            if n != 1:
                miss.append(f"{c['day']}: '{old}' 가 {n}번")
                continue
            hits[0]["text"] = hits[0]["text"].replace(old, new)
            done += 1
            changed = True
    if changed:
        cp.write_text(json.dumps(cs, ensure_ascii=False, indent=1), encoding="utf-8")
print("바꾼 곳", done)
for m in miss:
    print("문제:", m)
