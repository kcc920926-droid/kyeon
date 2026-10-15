"""장면 후보 점검(주제 태그판): python -X utf8 pool_check2.py <일 폴더> <파일 이름>
<일 폴더>/jobs.json 에서 이 파일의 일을 찾아 짜임, 주제, 주제마다의 개수, 필수어의 배타성(지금까지 쓴 모든 오늘 단락과 장부, 저장소 풀, 같은 때에 쓰는 다른 파일),
이름이 비슷한 쌍을 점검한다."""
import json
import os
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path(os.environ.get("KYEON_REPO") or HERE / "kyeon-tools-wt")      # 저장소 위치(환경 변수 KYEON_REPO, 없으면 작업 폴더 안의 kyeon-tools-wt)
sys.path.insert(0, str(REPO / "tools"))
import assign  # noqa: E402
import dupcheck  # noqa: E402
import planio  # noqa: E402

directory = HERE / sys.argv[1]
path = directory / "out" / sys.argv[2]
job = next((j for j in json.loads((directory / "jobs.json").read_text(encoding="utf-8")) if j["file"] == path.name), None)
if not job:
    print("jobs.json 에 없는 파일 이름입니다:", path.name)
    sys.exit(2)
try:
    pool = json.loads(path.read_text(encoding="utf-8"))
except (OSError, ValueError) as e:
    print("출력 파일을 읽지 못했습니다:", e)
    sys.exit(2)

plan = planio.read_plan(HERE / "plan_all" / "data" / "plan.json")
ledger = json.loads((HERE / "ledger_all.json").read_text(encoding="utf-8"))
texts = {d: t for d, _l, t in dupcheck.blocks_of(plan, "오늘")}
words = {w for s in ledger["scenes"].values() for w in s.get("words", [])}
names = {d: s["name"] for d, s in ledger["scenes"].items()}
others = []
repo_pool = REPO / "waves" / "pool.json"
if repo_pool.is_file():
    others += json.loads(repo_pool.read_text(encoding="utf-8"))
for f in sorted((directory / "out").glob("*.json")):
    if f.name != path.name:
        try:
            others += json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
seen = set()
for x in others:
    if isinstance(x, dict) and x.get("id") not in seen:
        seen.add(x.get("id"))
        words.update(x.get("words", []))
        names["풀 " + str(x.get("id"))] = x.get("name", "")

errs = []
parts = {p["prefix"]: p for p in job["parts"]}
for x in pool:
    pref = str(x.get("id", "")).split("-")[0]
    p = parts.get(pref)
    if not p:
        errs.append(f"{x.get('id')}: id 는 일의 prefix({', '.join(parts)})로 시작해야 합니다")
        continue
    if x.get("category") != p["category"]:
        errs.append(f"{x.get('id')}: prefix {pref} 의 범주는 '{p['category']}' 입니다('{x.get('category')}')")
    if set(x) != {"id", "name", "category", "words", "theme"}:
        errs.append(f"{x.get('id')}: 키는 id, name, category, words, theme 다섯 개여야 합니다")
    if x.get("theme") not in p["themes"]:
        errs.append(f"{x.get('id')}: 주제 '{x.get('theme')}' 는 prefix {pref} 일의 주제 목록에 없습니다")
have = Counter((str(x.get("id", "")).split("-")[0], x.get("theme")) for x in pool)
for pref, p in parts.items():
    for th in p["themes"]:
        if have[(pref, th)] < p["per_theme"]:
            errs.append(f"prefix {pref}({p['category']}) 주제 '{th}' 는 {p['per_theme']}개가 필요한데 {have[(pref, th)]}개입니다")
errs += assign.pool_problems(pool, texts, words, names)
# 필수어끼리 한쪽이 다른 쪽의 일부가 되면 조립에서 서로 막는다(미역과 미역국). 다른 후보, 1001일 이후 장부의 필수어와도 본다
owned = [(w, x.get("id")) for x in others if isinstance(x, dict) for w in x.get("words", [])]
owned += [(w, "장부 " + d) for d, s in ledger["scenes"].items() if int(d) >= 1001 for w in s.get("words", [])]
mine = [(w, x.get("id")) for x in pool for w in x.get("words", [])]
for i, (w, xid) in enumerate(mine):
    for v, o in owned + mine[:i]:
        if o != xid and (w in v or v in w) and w != v:
            errs.append(f"{xid}: 필수어 '{w}' 와 {o} 의 '{v}' 는 한쪽이 다른 쪽의 일부입니다")
            break
print("\n".join(errs[:40]) + (f"\n… 문제 {len(errs)}개" if len(errs) > 40 else "") if errs else f"풀 점검: 통과 ({len(pool)}개)")
sys.exit(1 if errs else 0)
