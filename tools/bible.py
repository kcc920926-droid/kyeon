"""개역한글 본문 원본(build/krv.json)을 다루는 공용 모듈. 네트워크를 쓰지 않는다.

build/krv.json 은 위키문헌 개역한글판을 {책: {장: {절: 글}}} 로 정리한 파일이다. 본문의 법적 지위가 아직 정리되지 않아
저장소에 올리지 않는다(.gitignore 의 build/). 저장소에 있는 본문은 data/plan.json 에 들어간 절뿐이다.

plan.json 에 본문을 넣을 때 쓰는 손질은 normalize()와 resolve()에 모았다(README 의 '본문 출처'와 같은 규칙).
  - 위키문헌의 '침례'를 대한성서공회 표기인 '세례'로 되돌린다
  - &nbsp; 를 없애고, 조사가 틀린 곳 몇 개와 시편 83:6 의 이름을 고친다
  - 시편(과 하박국 3장) 첫 절 앞의 [표제]는 note 로 떼어 낸다
  - 사본에 없는 절 표시([없음])는 뺀다
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = ROOT / "build" / "krv.json"

BOOKS = """창세기 출애굽기 레위기 민수기 신명기 여호수아 사사기 룻기 사무엘상 사무엘하 열왕기상 열왕기하
역대상 역대하 에스라 느헤미야 에스더 욥기 시편 잠언 전도서 아가 이사야 예레미야 예레미야애가 에스겔 다니엘
호세아 요엘 아모스 오바댜 요나 미가 나훔 하박국 스바냐 학개 스가랴 말라기
마태복음 마가복음 누가복음 요한복음 사도행전 로마서 고린도전서 고린도후서 갈라디아서 에베소서 빌립보서
골로새서 데살로니가전서 데살로니가후서 디모데전서 디모데후서 디도서 빌레몬서 히브리서 야고보서 베드로전서
베드로후서 요한1서 요한2서 요한3서 유다서 요한계시록""".split()
assert len(BOOKS) == 66
BOOK_INDEX = {b: i for i, b in enumerate(BOOKS)}
_BY_LENGTH = sorted(BOOKS, key=len, reverse=True)   # '요한복음'과 '요한1서'처럼 앞부분이 같은 이름을 위해 긴 이름부터 맞춰 본다

# plan.json 의 갈래(section)와 같은 이름
_WISDOM = {"욥기", "잠언", "전도서", "아가"}
_PROPHETS = set(BOOKS[BOOKS.index("이사야"):BOOKS.index("마태복음")])
_GOSPELS = {"마태복음", "마가복음", "누가복음", "요한복음"}


def section_of(book: str) -> str:
    if book == "시편":
        return "시편"
    if book in _WISDOM or book in _PROPHETS:
        return "지혜서·선지서"
    if book in _GOSPELS:
        return "복음서"
    if book == "요한계시록":
        return "요한계시록"
    if BOOK_INDEX[book] >= BOOK_INDEX["사도행전"]:
        return "사도행전·서신서"
    return "구약 이야기"


def stream_of(book: str) -> str:
    """순서를 섞을 때 쓰는 여덟 줄기. 갈래보다 잘다."""
    i = BOOK_INDEX[book]
    if book == "시편":
        return "시편"
    if i <= BOOK_INDEX["신명기"]:
        return "율법"
    if i <= BOOK_INDEX["에스더"]:
        return "역사"
    if book in _WISDOM:
        return "지혜"
    if book in _PROPHETS:
        return "선지"
    if book in _GOSPELS:
        return "복음"
    if book == "사도행전":
        return "행전"
    if book == "요한계시록":
        return "계시"
    return "서신"


def book_of(ref: str) -> str:
    """'요한1서 1:5–2:2', '시편 3편' 같은 참조에서 책 이름을 뽑는다."""
    for b in _BY_LENGTH:
        if ref.startswith(b):
            return b
    raise ValueError(f"책 이름을 알 수 없습니다: {ref}")


def load_db(path=None) -> dict:
    """{책: {장(int): {절(int): 글}}}"""
    path = Path(path) if path else DEFAULT_SOURCE
    if not path.is_file():
        raise FileNotFoundError(f"본문 원본이 없습니다: {path}. 저장소에는 올리지 않는 파일입니다(build/ 는 .gitignore).")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {b: {int(c): {int(v): t for v, t in vs.items()} for c, vs in chs.items()} for b, chs in raw.items()}


# 판본 정리: 문법상 분명한 조사 오타와 시편 83:6 의 이름 입력 실수
TEXT_FIXES = [("비밀를", "비밀을"), ("아킴를", "아킴을"), ("비유들를", "비유들을"), ("이스라엘 인과 모압", "이스마엘 인과 모압")]


def normalize(t: str) -> str:
    t = t.replace("&nbsp;", " ").replace("침례", "세례")
    for a, b in TEXT_FIXES:
        t = t.replace(a, b)
    return re.sub(r"\s+", " ", t).strip()


SUPER = re.compile(r"^\[([^\]]+)\]\s*")
RANGE = re.compile(r"^(\d+):(\d+)-(?:(\d+):)?(\d+)$")
ABSENT = "[없음]"   # 사본에 없는 절 표시


def parse_range(rng: str):
    m = RANGE.match(rng)
    if not m:
        raise ValueError(f"범위 형식 오류: {rng}")
    c1, v1 = int(m[1]), int(m[2])
    c2, v2 = int(m[3] or m[1]), int(m[4])
    return c1, v1, c2, v2


def is_absent(text: str) -> bool:
    return normalize(text) == ABSENT


def resolve(db: dict, book: str, rng: str):
    """'c:v-v' 또는 'c:v-c:v' 범위를 plan.json 의 verses([[장, 절, 글], ...])로 바꾼다. -> (verses, 시편 표제 note)"""
    c1, v1, c2, v2 = parse_range(rng)
    out, note = [], None
    for c in range(c1, c2 + 1):
        vs = db[book][c]
        lo = v1 if c == c1 else 1
        hi = v2 if c == c2 else max(vs)
        for v in range(lo, hi + 1):
            if v not in vs:
                raise KeyError(f"{book} {c}:{v} 없음")
            t = normalize(vs[v])
            if v == 1 and (book == "시편" or (book == "하박국" and c == 3)):
                sm = SUPER.match(t)
                if sm:
                    if c == c1 and v == v1:
                        note = sm[1].strip()
                    t = t[sm.end():]
            if t == ABSENT:
                continue
            out.append([c, v, t])
    joined = "".join(x[2] for x in out)
    if joined.count("]") > joined.count("["):   # 범위 밖에서 열린 괄호의 짝 제거
        out[-1][2] = re.sub(r"\]\s*$", "", out[-1][2])
    elif joined.count("[") > joined.count("]"):
        out[0][2] = re.sub(r"^\[", "", out[0][2])
    return out, note


def ref_label(db: dict, book: str, verses) -> str:
    c1, v1 = verses[0][0], verses[0][1]
    c2, v2 = verses[-1][0], verses[-1][1]
    whole = (c1 == c2 and v1 == 1 and v2 == max(db[book][c2]))
    if book == "시편" and whole:
        return f"시편 {c1}편"
    if c1 == c2:
        return f"{book} {c1}:{v1}–{v2}" if v1 != v2 else f"{book} {c1}:{v1}"
    return f"{book} {c1}:{v1}–{c2}:{v2}"


def covered(plan: dict) -> set:
    """plan.json 의 날들이 이미 담은 절 {(책, 장, 절)}"""
    out = set()
    for d in plan["days"]:
        b = book_of(d["ref"])
        out.update((b, c, v) for c, v, _t in d["verses"])
    return out
