"""새 날 해설 점검: python -X utf8 wave_check.py <해 폴더> NN      예: python -X utf8 wave_check.py y2 03
<해 폴더>/items_NN.json 과 <해 폴더>/commentary_NN.json 을 견준다.
형식, 라벨, 글자 수, 번역투, 쓰지 않는 표현, 장면 규칙(메뉴 안인가, 필수어가 첫 두 문장에 있는가, 그 날 메뉴의 다른 후보 낱말을 섞지 않았는가)과
지금까지 쓴 모든 날(plan_all: 기존 1000일 + 앞선 해들)과의 반복 구절, 복붙을 본다."""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path(os.environ.get("KYEON_REPO") or HERE / "kyeon-tools-wt")      # 저장소 위치(환경 변수 KYEON_REPO, 없으면 작업 폴더 안의 kyeon-tools-wt)
sys.path.insert(0, str(REPO / "tools"))
import assemble  # noqa: E402
import dupcheck  # noqa: E402
import planio  # noqa: E402
import themes  # noqa: E402
import tlint  # noqa: E402

directory = HERE / sys.argv[1]
nn = sys.argv[2]
items = json.loads((directory / f"items_{nn}.json").read_text(encoding="utf-8"))
try:
    comments = json.loads((directory / f"commentary_{nn}.json").read_text(encoding="utf-8"))
except (OSError, ValueError) as e:
    print("출력 파일을 읽지 못했습니다:", e)
    sys.exit(2)
if not isinstance(comments, list) or [c.get("day") if isinstance(c, dict) else None for c in comments] != [i["day"] for i in items]:
    print("출력의 일차 순서와 개수가 입력과 다릅니다. 입력:", [i["day"] for i in items][:3], "…", len(items), "일")
    sys.exit(1)

errs = []
notes = []
for it, c in zip(items, comments):
    errs += assemble.check_commentary(c, it)
if not errs:
    scenes = {}
    for it, c in zip(items, comments):
        m = next((x for x in it.get("menu", []) if x["id"] == c.get("scene")), None)
        if m and m.get("theme"):
            scenes[str(it["day"])] = {"category": it["category"], "theme": m["theme"]}
    errs += [f"이 조각 안에서 {p}" for p in themes.window_problems(scenes, cap=2)]     # 이웃한 조각과 합쳐 상한 3을 지키도록 조각 안에서는 2번까지
if not errs:
    # 번역투 틀이 한 조각에 몰리지 않게 본다. 전체 상한(tlint.QUOTA)을 이 조각의 블록 수에 맞춰 반올림한 값이 허용량이다
    labels = {rid: label for rid, _rx, _cap, label, _fix in tlint.COMPILED}
    flat = [(c["day"], b["text"]) for c in comments for b in c["blocks"]]
    for rid, q in sorted(tlint.QUOTA.items()):
        hit = [flat[k][0] for k in tlint.blocks_with(rid, [t for _d, t in flat])]
        allow = max(1, round(len(flat) * q))
        if len(hit) > allow:
            errs.append(f"이 조각에서 {rid}({labels[rid]}) 틀이 {len(hit)}블록에 있습니다(허용 {allow}블록): {', '.join(map(str, hit))}일. 몇 곳은 다른 말로 바꾸거나 단정을 빼세요")
if not errs:
    # 같은 해의 다른 조각 메뉴에 오른 후보 낱말(어느 것이든)이 이 조각 글에 섞였는지 본다. 조립 때 필수어 충돌이 가장 많이 나는 곳이라 참고로만 알린다(막지는 않는다)
    others = {}
    for ip in sorted(directory.glob("items_*.json")):
        if ip.name == f"items_{nn}.json":
            continue
        for it2 in json.loads(ip.read_text(encoding="utf-8")):
            for m in it2.get("menu", []):
                for w in m["words"]:
                    others.setdefault(w, it2["day"])
    for c in comments:
        text = " ".join(b["text"] for b in c["blocks"])
        hit = sorted(w for w in others if w in text)
        if hit:
            notes.append(f"참고 {c['day']}일: 같은 해 다른 날의 후보 낱말 {', '.join(hit[:4])}(각각 {', '.join(str(others[w]) for w in hit[:4])}일 메뉴)이 글에 있습니다. 그 날이 그 후보를 고르면 조립에서 충돌합니다. 쉽게 바꿀 수 있으면 바꾸세요(필수는 아닙니다)")
if not errs:
    plan = planio.read_plan(HERE / "plan_all" / "data" / "plan.json")
    cand = [{"day": c["day"], "text": c["blocks"][-1]["text"]} for c in comments]
    errs += dupcheck.candidate_problems(plan, cand)
if notes:
    print("\n".join(notes[:20]))
print("\n".join(errs[:40]) + (f"\n… 문제 {len(errs)}개" if len(errs) > 40 else "") if errs else f"해설 점검: 통과 ({len(comments)}일)")
sys.exit(1 if errs else 0)
