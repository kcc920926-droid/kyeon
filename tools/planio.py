"""계획표 읽기. data/plan.json 과 같은 폴더의 data/plan-<첫 일차>.json 들을 이어 붙여 하나의 plan 으로 읽는다.

kyeon.py 의 load_plan 과 같은 규칙이다(plan.json 이 머리말과 길 정의를 가진 첫 묶음, 나머지는 날만, 번호는 숫자 순서).
도구들이 tkinter 를 불러오지 않으려고 따로 둔 짧은 복사본이며, tests/test_planio.py 가 둘이 같은 결과를 내는지 본다.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / "data" / "plan.json"
PART_RE = re.compile(r"plan-(\d+)\.json")


def part_files(path: Path = PLAN) -> list:
    found = []
    for p in Path(path).parent.glob("plan-*.json"):
        m = PART_RE.fullmatch(p.name)
        if m:
            found.append((int(m.group(1)), p))
    return [p for _n, p in sorted(found)]


def read_plan(path=PLAN) -> dict:
    """머리말은 plan.json 의 것이고 days 는 plan.json 뒤에 나뉜 파일들의 날을 일차 순서로 이어 붙인 것이다."""
    path = Path(path)
    plan = json.loads(path.read_text(encoding="utf-8"))
    days = list(plan["days"])
    for p in part_files(path):
        days += json.loads(p.read_text(encoding="utf-8"))["days"]
    plan["days"] = days
    return plan
