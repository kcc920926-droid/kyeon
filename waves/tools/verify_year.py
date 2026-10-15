"""python -X utf8 verify_year.py FIRST LAST     예: verify_year.py 1366 1730
plan_all/data 와 ledger_all.json 이 FIRST~LAST 일까지 갱신된 뒤, 새 날들을 점검한다."""
import json, os, sys
from collections import Counter
from pathlib import Path
S = Path(__file__).resolve().parent
REPO = Path(os.environ.get("KYEON_REPO") or S / "kyeon-tools-wt")      # 저장소 위치(환경 변수 KYEON_REPO, 없으면 작업 폴더 안의 kyeon-tools-wt)
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO))
import planio, dupcheck, ledger as ledger_tool, kyeon, bible, themes
first, last = int(sys.argv[1]), int(sys.argv[2])
plan = planio.read_plan(S / "plan_all" / "data" / "plan.json")
days = plan["days"]
nums = [d["day"] for d in days]
print("일수", len(days), "연속", nums == list(range(1, len(days) + 1)), "마지막", nums[-1])
print("day_ok 실패", [d["day"] for d in days if not kyeon.day_ok(d)][:5])
loaded = kyeon.load_plan(S / "plan_all" / "data" / "plan.json")
print("앱 load_plan", len(loaded["days"]))
led = json.loads((S / "ledger_all.json").read_text(encoding="utf-8"))
new = {d: s for d, s in led["scenes"].items() if first <= int(d) <= last}
print("새 장부", len(new), "(기대", last - first + 1, ")")
print("새 장부 모양 문제", dupcheck.ledger_shape_problems({"scenes": new})[:5])
texts = {d: t for d, _l, t in dupcheck.blocks_of(plan, "오늘")}
print("새 장부 필수어 대 모든 글", dupcheck.ledger_shape_problems({"scenes": new}, texts)[:5])
print("장면 필수어 첫 두 문장", dupcheck.scene_problems({"scenes": new}, {d: texts[d] for d in range(first, last + 1)})[:5])
order = list(range(1, last + 1))
print("창 문제(share 상한 해제)", dupcheck.window_problems(led, order, share=1.0)[:8])
th = themes.window_problems(led["scenes"])
print("주제 몰림(전체, 상한 3)", len(th))
for p in th[:20]:
    print("  ", p)
tot = Counter(s["category"] for s in led["scenes"].values())
print("전체 범주 비중:", {c: f"{n*100/len(led['scenes']):.1f}%" for c, n in tot.most_common()})
newc = Counter(s["category"] for s in new.values())
print("새 날 범주:", dict(newc.most_common()))
orders = ledger_tool.route_orders(plan)
print("길 순서 문제", len(dupcheck.route_problems(led, orders)))
before = {**plan, "days": days[:first - 1]}
old_orders = ledger_tool.route_orders(before)
print("길 순서 문제(새 날 이전)", len(dupcheck.route_problems({"scenes": {d: s for d, s in led["scenes"].items() if int(d) < first}}, old_orders)))
names = {d: s["name"] for d, s in led["scenes"].items()}
sim = dupcheck.similar_names({d: names[d] for d in new}, names, min_jaccard=dupcheck.NAME_SIMILAR)
sim = [x for x in sim if x[1] != x[2]]
print("새 이름과 비슷한 쌍", len(sim))
for x in sim[:10]:
    print("  ", x)
cov = bible.covered({"days": days[first - 1:last]}) & bible.covered({"days": days[:first - 1]})
print("새 날과 기존 날의 겹친 절", len(cov))
print("섹션", Counter(d["section"] for d in days[first - 1:last]).most_common())
print("형식", Counter(d["format"] for d in days[first - 1:last]).most_common())
print("lv 길이 합리", all(len(d["lv"]) == len(d["verses"]) for d in days[first - 1:last]))
