"""python -X utf8 setup_workspace.py 작업폴더 [--repo 저장소]
해마다 글을 쓰고 점검하던 작업 폴더를 저장소에서 다시 만든다.
- 이 폴더의 도구(점검, 수리, 풀 정리)와 waves/guides 의 지침, waves/wordcheck 의 낱말 점검 자료를 작업 폴더로 복사한다.
- 지금까지 쓴 3650일을 plan_all/data(plan.json 과 plan-<첫 날>.json)로, 장면 장부를 ledger_all.json 으로 합쳐 둔다.
도구는 환경 변수 KYEON_REPO(없으면 작업 폴더 안의 kyeon-tools-wt)에서 저장소의 tools/ 를 읽는다.
본문 원본(build/krv.json)은 저장소에 없으니 따로 두어야 한다."""
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
args = sys.argv[1:]
repo = HERE.parent.parent
if "--repo" in args:
    i = args.index("--repo")
    repo = Path(args[i + 1])
    del args[i:i + 2]
if len(args) != 1:
    sys.exit(__doc__)
work = Path(args[0])
work.mkdir(parents=True, exist_ok=True)

for p in HERE.glob("*.py"):
    if p.name != Path(__file__).name:
        shutil.copy2(p, work / p.name)
for p in (repo / "waves" / "guides").glob("*"):
    shutil.copy2(p, work / p.name)
shutil.copytree(repo / "waves" / "wordcheck", work / "wordcheck", dirs_exist_ok=True)
shutil.copy2(repo / "waves" / "categories_all_waves.json", work / "cats_plan_all_years.json")

# 조각 폴더(시범, 첫 해 … 마지막 95일)를 날 순서로 이어 붙인다
parts = [repo / "waves" / "pilot"] + [repo / "waves" / f"year{n}" for n in range(1, 9)]
data = work / "plan_all" / "data"
data.mkdir(parents=True, exist_ok=True)
shutil.copy2(repo / "data" / "plan.json", data / "plan.json")
ledger = json.loads((repo / "ledger" / "scenes.json").read_text(encoding="utf-8"))
last = len(json.loads((repo / "data" / "plan.json").read_text(encoding="utf-8"))["days"])
for part in parts:
    days = json.loads((part / "days.json").read_text(encoding="utf-8"))
    first = days["days"][0]["day"]
    if first != last + 1:
        sys.exit(f"{part.name}: 첫 날이 {first} 입니다({last + 1} 이어야 합니다)")
    last = days["days"][-1]["day"]
    shutil.copy2(part / "days.json", data / f"plan-{first}.json")
    new = json.loads((part / "ledger.json").read_text(encoding="utf-8"))
    dup = set(new) & set(ledger["scenes"])
    if dup:
        sys.exit(f"{part.name}: 장부에 이미 있는 날 {sorted(dup)[:3]}")
    ledger["scenes"].update(new)
(work / "ledger_all.json").write_text(json.dumps(ledger, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"작업 폴더 {work}: {last}일, 장부 {len(ledger['scenes'])}개")
print("도구를 쓰기 전에 환경 변수 KYEON_REPO 를 저장소 위치로 정하세요(예: set KYEON_REPO=" + str(repo) + ").")
