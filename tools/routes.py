"""읽는 길(시기, 테마)의 정의와 시기 규칙표. data/plan.json 에 길 정보를 붙이고 점검한다.

  python tools/routes.py --check            plan.json 의 길 정보를 점검한다(시기 규칙표와 같은지, 테마 개수 등)
  python tools/routes.py --stamp-eras       규칙표대로 plan.json 의 날마다 era 를 쓰고 머리말에 routes 를 쓴다
  python tools/routes.py --stamp-themes F   F(JSON: {"일차": ["테마 id", ...]})대로 날마다 themes 를 쓴다
  python tools/routes.py --summary          시기와 테마마다 며칠인지 보여 준다

길은 다섯 가지다. 전체 순서(원래 3650일), 시기별, 테마별, 갈래별(section 값 그대로), 그리고 이 파일이 정하는 시기와 테마.
  - 시기: 책 이름으로 나눈 읽기 길잡이다. 학자마다 책의 연대를 다르게 보므로 연대를 단정하지 않고, 열왕기상·역대하만 장으로 가른다.
  - 테마: AI 가 본문과 해설을 보고 날마다 1~2개를 붙였다(사람이 검토한 것은 아니다).
각 길 안에서는 원래 3650일의 순서를 따른다.
plan.json 의 날은 한 줄에 하나씩이고(줄바꿈은 파일에 있는 그대로), 이 도구는 era·themes 와 머리말의 routes 외에는 건드리지 않는다.
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

PLAN = Path(__file__).resolve().parent.parent / "data" / "plan.json"

ERAS = [
    {"id": "beginnings", "name": "창조와 족장", "about": "세상의 시작과 아브라함, 이삭, 야곱, 요셉"},
    {"id": "exodus", "name": "출애굽과 광야", "about": "노예에서 풀려나 광야를 지나며 율법을 받던 때"},
    {"id": "settling", "name": "정착과 사사", "about": "가나안 땅에 정착하고 사사들이 일어서던 때"},
    {"id": "kingdom", "name": "다윗과 솔로몬", "about": "왕이 세워지고 성전이 지어지던 때"},
    {"id": "prophets", "name": "갈라진 나라와 선지자", "about": "나라가 둘로 갈라진 뒤 선지자들이 말하던 때"},
    {"id": "exile", "name": "포로와 귀환", "about": "나라가 무너져 끌려갔다가 돌아오던 때"},
    {"id": "jesus", "name": "예수님의 생애", "about": "네 복음서가 전하는 예수님의 말씀과 행하심"},
    {"id": "church", "name": "초대 교회", "about": "사도행전과 교회들에게 보낸 편지"},
    {"id": "revelation", "name": "마지막 날의 환상", "about": "요한계시록"},
    {"id": "timeless", "name": "시대를 넘는 노래와 지혜", "about": "시편과 지혜서처럼 때를 정하기 어려운 글"},
]
THEMES = [
    {"id": "comfort", "name": "위로와 쉼", "about": "지치고 마음이 무거운 날"},
    {"id": "fear", "name": "두려움과 불안", "about": "겁이 나고 앞이 막막한 날"},
    {"id": "thanks", "name": "감사와 찬양", "about": "고마움을 말하고 싶은 날"},
    {"id": "repent", "name": "회개와 용서", "about": "잘못을 돌아보고 새로 시작하고 싶은 날"},
    {"id": "love", "name": "사랑과 이웃", "about": "가까운 사람과 이웃, 사랑을 생각하는 날"},
    {"id": "wisdom", "name": "지혜와 일상", "about": "일과 돈과 말, 날마다 하는 선택"},
    {"id": "suffering", "name": "고난과 견딤", "about": "아프고 억울하고 오래 기다리는 날"},
    {"id": "prayer", "name": "기도와 부르짖음", "about": "하나님께 솔직하게 말하고 싶은 날"},
    {"id": "hope", "name": "소망과 회복", "about": "무너진 자리에서 다시 일어서는 이야기"},
    {"id": "justice", "name": "공의와 정의", "about": "약한 사람 편에 서시는 하나님과 우리의 몫"},
    {"id": "faith", "name": "믿음과 순종", "about": "믿고 따라 나서는 결단"},
    {"id": "god", "name": "하나님을 알아 가기", "about": "창조하시고 다스리시고 찾아오시는 분"},
    {"id": "community", "name": "공동체와 가정", "about": "교회와 가정, 관계 속에서 사는 법"},
]
MIN_ERA_DAYS = 10
MIN_THEME_PER_1000, MAX_THEME_PER_1000 = 35, 400   # 테마 하나가 차지하는 일수의 한도(1000일당). 계획 길이에 비례해 늘어난다

_BEG, _EXO, _SET, _KIN, _PRO, _EXI, _JES, _CHU, _REV, _TIM = (e["id"] for e in ERAS)
BOOK_ERA = {
    "창세기": _BEG,
    "출애굽기": _EXO, "레위기": _EXO, "민수기": _EXO, "신명기": _EXO,
    "여호수아": _SET, "사사기": _SET, "룻기": _SET,
    "사무엘상": _KIN, "사무엘하": _KIN, "역대상": _KIN, "열왕기상": _KIN, "역대하": _KIN,   # 열왕기상·역대하는 장으로 가른다
    "열왕기하": _PRO, "이사야": _PRO, "호세아": _PRO, "요엘": _PRO, "아모스": _PRO, "요나": _PRO, "미가": _PRO,
    "나훔": _PRO, "하박국": _PRO, "스바냐": _PRO,
    "예레미야": _EXI, "예레미야애가": _EXI, "에스겔": _EXI, "다니엘": _EXI, "에스라": _EXI, "느헤미야": _EXI,
    "에스더": _EXI, "학개": _EXI, "스가랴": _EXI, "말라기": _EXI, "오바댜": _EXI,
    "마태복음": _JES, "마가복음": _JES, "누가복음": _JES, "요한복음": _JES,
    "사도행전": _CHU, "로마서": _CHU, "고린도전서": _CHU, "고린도후서": _CHU, "갈라디아서": _CHU, "에베소서": _CHU,
    "빌립보서": _CHU, "골로새서": _CHU, "데살로니가전서": _CHU, "데살로니가후서": _CHU, "디모데전서": _CHU,
    "디모데후서": _CHU, "디도서": _CHU, "빌레몬서": _CHU, "히브리서": _CHU, "야고보서": _CHU, "베드로전서": _CHU,
    "베드로후서": _CHU, "요한1서": _CHU, "요한2서": _CHU, "요한3서": _CHU, "유다서": _CHU,
    "요한계시록": _REV,
    "시편": _TIM, "욥기": _TIM, "잠언": _TIM, "전도서": _TIM, "아가": _TIM,
}
# 장으로 가르는 책: (책, 이 장까지는 앞의 시기, 그 뒤는 다음 시기)
SPLIT_BOOKS = {"열왕기상": (11, _KIN, _PRO), "역대하": (9, _KIN, _PRO)}


def book_and_chapter(ref: str) -> tuple[str, int]:
    m = re.match(r"(.+?)\s+(\d+)", ref)
    if not m:
        raise ValueError(f"본문 위치를 읽지 못했습니다: {ref}")
    return m.group(1).strip(), int(m.group(2))


def era_of(ref: str) -> str:
    book, chapter = book_and_chapter(ref)
    if book not in BOOK_ERA:
        raise KeyError(f"시기 규칙표에 없는 책: {book} ({ref})")
    if book in SPLIT_BOOKS:
        upto, before, after = SPLIT_BOOKS[book]
        return before if chapter <= upto else after
    return BOOK_ERA[book]


def routes_meta() -> dict:
    return {"era": ERAS, "theme": THEMES}


# ---- plan.json 읽고 쓰기(한 날 한 줄, 줄바꿈 그대로) ----
def _lines(path: Path):
    raw = path.read_bytes().decode("utf-8")
    eol = "\r\n" if "\r\n" in raw else "\n"
    return raw.split(eol), eol


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _rewrite_days(path: Path, fn, meta: dict | None = None) -> int:
    """날마다 fn(day dict) -> 새 day dict. meta 가 있으면 머리말의 routes 줄을 쓰거나 바꾼다. 바뀐 날 수를 돌려준다."""
    lines, eol = _lines(path)
    out, changed = [], 0
    for ln in lines:
        if meta is not None and ln.startswith('"routes":'):
            continue   # 있던 줄은 아래에서 새로 넣는다
        if ln.startswith('{"day":'):
            comma = "," if ln.endswith(",") else ""
            d = json.loads(ln[:-1] if comma else ln)
            new = fn(d)
            line = _dump(new) + comma
            changed += line != ln
            out.append(line)
            continue
        if meta is not None and ln.startswith('"days":'):
            out.append('"routes": ' + _dump(meta) + ",")
        out.append(ln)
    path.write_bytes(eol.join(out).encode("utf-8"))
    return changed


def _put(d: dict, key: str, value, after: str = "title") -> dict:
    """key 를 (있으면 그 자리에, 없으면 after 키 바로 뒤에) 넣는다."""
    if key in d:
        d[key] = value
        return d
    new = {}
    for k, v in d.items():
        new[k] = v
        if k == after:
            new[key] = value
    return new


def stamp_eras(path: Path = PLAN) -> int:
    meta = dict(json.loads(path.read_text(encoding="utf-8")).get("routes", {}), era=ERAS, theme=THEMES)   # 정의는 둘 다 갱신
    return _rewrite_days(path, lambda d: _put(d, "era", era_of(d["ref"])), meta)


def stamp_themes(tags: dict, path: Path = PLAN) -> int:
    ids = {t["id"] for t in THEMES}
    for day, ts in tags.items():
        if not (1 <= len(ts) <= 2) or len(set(ts)) != len(ts) or not set(ts) <= ids:
            raise ValueError(f"{day}일의 테마가 올바르지 않습니다: {ts}")
    meta = dict(json.loads(path.read_text(encoding="utf-8")).get("routes", {}), theme=THEMES)
    meta.setdefault("era", ERAS)
    return _rewrite_days(path, lambda d: _put(d, "themes", list(tags[str(d["day"])]), after="era"), meta)


def check(plan: dict) -> list[str]:
    """plan 의 길 정보를 점검한다. 문제 목록(비어 있으면 통과)."""
    errs = []
    days = plan["days"]
    routes = plan.get("routes") or {}
    if routes.get("era") != ERAS:
        errs.append("머리말의 routes.era 가 규칙표(ERAS)와 다릅니다")
    if routes.get("theme") != THEMES:
        errs.append("머리말의 routes.theme 가 THEMES 와 다릅니다")
    theme_ids = {t["id"] for t in THEMES}
    eras, themes = Counter(), Counter()
    for d in days:
        want = era_of(d["ref"])
        if d.get("era") != want:
            errs.append(f"{d['day']}일: era {d.get('era')!r} (규칙표는 {want})")
        ts = d.get("themes")
        if not isinstance(ts, list) or not 1 <= len(ts) <= 2 or len(set(ts)) != len(ts) or not set(ts) <= theme_ids:
            errs.append(f"{d['day']}일: themes 가 올바르지 않습니다 {ts!r}")
            continue
        eras[want] += 1
        themes.update(ts)
    for e in ERAS:
        if eras[e["id"]] < MIN_ERA_DAYS:
            errs.append(f"시기 '{e['name']}' 이 {eras[e['id']]}일뿐입니다(최소 {MIN_ERA_DAYS}일)")
    lo, hi = MIN_THEME_PER_1000 * len(days) // 1000, -(-MAX_THEME_PER_1000 * len(days) // 1000)
    for t in THEMES:
        n = themes[t["id"]]
        if not lo <= n <= hi:
            errs.append(f"테마 '{t['name']}' 이 {n}일입니다({lo}~{hi}일이어야 함)")
    return errs


def summary(plan: dict) -> str:
    eras = Counter(d.get("era") for d in plan["days"])
    themes = Counter(t for d in plan["days"] for t in d.get("themes", []))
    rows = [f"시기 {e['name']}: {eras[e['id']]}일" for e in ERAS] + [f"테마 {t['name']}: {themes[t['id']]}일" for t in THEMES]
    return "\n".join(rows)


def main(argv: list[str]) -> int:
    if "--stamp-eras" in argv:
        print("바뀐 날:", stamp_eras())
        return 0
    if "--stamp-themes" in argv:
        tags = json.loads(Path(argv[argv.index("--stamp-themes") + 1]).read_text(encoding="utf-8"))
        print("바뀐 날:", stamp_themes({str(k): v for k, v in tags.items()}))
        return 0
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import planio
    plan = planio.read_plan(PLAN)
    if "--summary" in argv:
        print(summary(plan))
        return 0
    errs = check(plan)
    for e in errs[:30]:
        print(e)
    print("길 정보 점검:", "통과" if not errs else f"문제 {len(errs)}개")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
