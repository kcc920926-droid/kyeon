"""아직 안 쓴 풀 후보를 지금까지 쓴 글과 장부에 견줘 쓸 수 있는 것만 남긴다.
python -X utf8 curate_pool.py [--merge DIR ...]     --merge 로 새 후보 폴더(DIR/out/*.json)를 저장소 풀에 먼저 합친다
-> free_pool.json, 범주와 주제별 개수 출력.
뺄 것: 필수어가 어느 오늘 단락에 들어 있는 것, 1001일 이후 장부의 필수어와 같거나 서로 포함하는 것, 이름이 장부와 비슷한 것,
후보끼리 필수어가 서로 포함하거나 이름이 비슷하면 뒤의 것."""
import json, os, sys
from collections import Counter, defaultdict
from pathlib import Path
S = Path(__file__).resolve().parent
REPO = Path(os.environ.get("KYEON_REPO") or S / "kyeon-tools-wt")      # 저장소 위치(환경 변수 KYEON_REPO, 없으면 작업 폴더 안의 kyeon-tools-wt)
sys.path.insert(0, str(REPO / "tools"))
import dupcheck, planio, themes
poolp = REPO / "waves" / "pool.json"
pool = json.loads(poolp.read_text(encoding="utf-8"))
if "--merge" in sys.argv:
    ids = {x["id"] for x in pool}
    for d in sys.argv[sys.argv.index("--merge") + 1:]:
        for f in sorted((S / d / "out").glob("*.json")):
            for x in json.loads(f.read_text(encoding="utf-8")):
                if x["id"] in ids:
                    continue
                assert not themes.problems_of(x), x
                pool.append(x); ids.add(x["id"])
    poolp.write_text(json.dumps(pool, ensure_ascii=False, indent=1), encoding="utf-8")
    print("저장소 풀", len(pool), "개")
chosen = set()
for pat in ("wave*/commentary_*.json", "y*/commentary_*.json"):
    for f in sorted(S.glob(pat)):
        if "backup" in str(f): continue
        for c in json.loads(f.read_text(encoding="utf-8")):
            chosen.add(c["scene"])
plan = planio.read_plan(S / "plan_all" / "data" / "plan.json")
joined = "\n".join(t for d, l, t in dupcheck.blocks_of(plan, "오늘"))
led = json.loads((S / "ledger_all.json").read_text(encoding="utf-8"))["scenes"]
recent_words = [w for d, s in led.items() if int(d) >= 1001 for w in s.get("words", [])]
lnames = {d: s["name"] for d, s in led.items()}
free = [x for x in pool if x["id"] not in chosen]
drop = Counter()
keep = []
badp = S / "wordcheck" / "bad_words.json"
badw = set(json.loads(badp.read_text(encoding="utf-8"))) if badp.exists() else set()
rejp = S / "wordcheck" / "rejected_scenes.json"          # 앞선 날과 장면이 비슷해서 다시 쓰며 버린 후보(해가 끝나면 풀로 돌아가므로 따로 막는다)
rejected = set(json.loads(rejp.read_text(encoding="utf-8"))) if rejp.exists() else set()
if badw or rejected:
    n0 = len(pool)
    pool = [x for x in pool if x["id"] in chosen or (x["id"] not in rejected and not any(w in badw for w in x["words"]))]
    if len(pool) < n0:
        poolp.write_text(json.dumps(pool, ensure_ascii=False, indent=1), encoding="utf-8")
        print("어색한 필수어로 저장소 풀에서 뺌", n0 - len(pool), "개")
    free = [x for x in pool if x["id"] not in chosen]
for x in free:
    if any(w in joined for w in x["words"]):
        drop["글에 있는 필수어"] += 1; continue
    if any(w == v or w in v or v in w for w in x["words"] for v in recent_words):
        drop["장부 필수어와 겹침"] += 1; continue
    keep.append(x)
bad = {b for j, a, b in dupcheck.similar_names({x["id"]: x["name"] for x in keep}, lnames, min_jaccard=dupcheck.NAME_SIMILAR)} \
    | {a for j, a, b in dupcheck.similar_names({x["id"]: x["name"] for x in keep}, lnames, min_jaccard=dupcheck.NAME_SIMILAR)}
keep2 = []
for x in keep:
    if x["id"] in bad: drop["이름이 장부와 비슷"] += 1
    else: keep2.append(x)
names = {x["id"]: x["name"] for x in keep2}
order = {x["id"]: i for i, x in enumerate(keep2)}
later = set()
for j, a, b in dupcheck.similar_names(names, min_jaccard=dupcheck.NAME_SIMILAR):
    later.add(a if order[a] > order[b] else b)
keep3 = []
for x in keep2:
    if x["id"] in later: drop["후보끼리 이름이 비슷"] += 1
    else: keep3.append(x)
owned = []                      # (낱말, id)
final = []
for x in keep3:
    clash = False
    for w in x["words"]:
        for v, o in owned:
            if w == v or w in v or v in w:
                clash = True; break
        if clash: break
    if clash:
        drop["후보끼리 필수어가 겹침"] += 1; continue
    owned += [(w, x["id"]) for w in x["words"]]
    final.append(x)
(S / "free_pool.json").write_text(json.dumps(final, ensure_ascii=False, indent=1), encoding="utf-8")
print("선택된 장면", len(chosen), "| 안 쓴 후보", len(free), "| 남김", len(final), "| 뺌", dict(drop))
by = defaultdict(Counter)
for x in final: by[x["category"]][x.get("theme")] += 1
for c, cnt in sorted(by.items(), key=lambda kv: -sum(kv[1].values())):
    print(f"  {c} {sum(cnt.values())}개 (주제 {len(cnt)}종: {dict(cnt.most_common(4))} …)")
