"""해설이 서로 겹치는지 전체를 한꺼번에 점검한다. 표준 라이브러리만 쓴다.

  python tools/dupcheck.py --report                          지금 plan.json 의 겹침 기준선(분포, 반복 구절, 비슷한 쌍)을 보여 준다
  python tools/dupcheck.py --check                           plan.json 전체가 기준을 지키는지 본다(시험이 같은 점검을 돈다)
  python tools/dupcheck.py --candidate F [--ledger L]        새로 쓴 '오늘' 단락(JSON: [{"day": n, "text": "..."}])을 기존 전체와 견줘 점검한다
  python tools/dupcheck.py --ledger-check L                  장면 장부의 짜임과 쿼터(범주 비중, 7일과 30일 창)를 점검한다

무엇을 어떻게 보나 (실험으로 정한 것)
  장면 필수어  장부(L)에서 날마다 배정된 장면의 필수어가 그 날 첫 두 문장에 있어야 하고, 새로 쓰는 다른 날의 필수어는 새 글에 없어야 한다.
               기존 1000일의 필수어는 새 글에서 막지 않는다(기존 글에서 고른 낱말이라 세례, 형상 같은 성경 낱말이 섞여 있다).
               기존 장면과 겹치는 것은 새 후보의 필수어가 기존 오늘 단락 어디에도 없다는 점검과 이름 비교가 막는다.
               글자 통계로는 겹친 장면을 못 잡는다. 이번에 겹친 29쌍에서 글자 3-gram 유사도는 무작위 쌍과 구별되지 않았다(0.02~0.07).
               그래서 장면은 '미리 배정하고 필수어로 확인'하는 것이 본체다.
  반복 구절    4어절이 여러 날에 나오면 안 된다(기준 max_df). 시편 표제 설명처럼 되풀이가 맞는 구절은 ALLOWED 에 둔다.
  복붙         가장 가까운 단락과의 글자 3-gram 유사도가 NEAR_COPY 를 넘으면 문구를 가져다 쓴 것으로 본다(기존 최대 0.15).
  분포         첫 어절, 둘째 문장의 첫 어절, 마지막 네 글자가 한쪽으로 쏠리지 않았는지 본다.
  훑어볼 목록  첫 문장에서 드문 낱말을 둘 이상 같이 쓰는 쌍을 뽑는다. 장면이 비슷할 수 있는 후보이며 사람이 훑는다(통과 기준이 아니다).
  창과 길      장면의 범주가 어느 7일, 30일, 길의 연속 10개 안에서 몰리지 않았는지 본다.
  장면 이름    장부의 장면 이름이 서로 비슷한 쌍(NAME_SIMILAR)을 찾는다. 본문 글자로는 못 잡는 같은 장면을 이름이 드러낸다.
"""
import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import planio  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# 기준(지금 plan.json 이 통과하는 값으로 잡았다. 새 파도는 같은 값이거나 더 엄격해야 한다)
MAX_DF = 4              # 4어절이 나올 수 있는 날(블록) 수의 상한
NEAR_COPY = 0.30        # 같은 라벨 단락끼리 글자 3-gram 코사인의 상한(기존 최대 0.154)
MIN_CHARS = 80          # 이보다 짧은 단락은 복붙 검사에서 뺀다(한 줄짜리는 형식이 같아서 유사도가 부풀려진다)
MAX_FIRST_WORD = 0.02   # 첫 어절 하나가 오늘 단락 전체에서 차지하는 비중의 상한
MAX_SECOND_WORD = 0.25  # 둘째 문장의 첫 어절 하나의 비중 상한
MAX_ENDING = 0.10       # 마지막 문장의 끝 네 글자 하나의 비중 상한
MIN_SAMPLES = 50        # 분포는 단락이 이보다 적으면 보지 않는다(표본이 작으면 비중이 의미가 없다)
CATEGORY_SHARE = 0.08   # 장면 범주 하나의 전체 비중
WINDOWS = ((7, 2), (30, 6))   # (연속 일수, 같은 범주가 나올 수 있는 최대 횟수)
ROUTE_RUN = (10, 7)     # 길을 따라 읽을 때 연속 10개에 서로 다른 범주 7개 이상
NAME_SIMILAR = 0.30     # 장면 이름 두 개의 글자 두 개씩 묶음 자카드가 이 값 이상이면 같은 장면일 수 있다
CATEGORIES = ["가정·육아", "직장·일", "학교·청년", "의료·건강", "이동·교통", "디지털·소통", "돈·살림", "이웃·관계",
              "농어촌·자연", "날씨·계절", "의례·행사", "노년·돌봄", "상가·서비스", "여가·취미", "재난·사고", "공공·제도"]
# 되풀이가 맞는 구절: 시편 표제 설명, 히브리어 시 형식 설명처럼 같은 사실을 같은 말로 쓰는 곳
ALLOWED = {"있다고 보는 견해가 많습니다", "히브리어 알파벳 순서를 따라", "표제에 따르면 다윗의 시이며"}


def words(t: str) -> list:
    return re.findall(r"[가-힣]+", t)


def sentences(t: str) -> list:
    return [s for s in re.split(r"(?<=[.!?])\s+", t.strip()) if s]


def grams(t: str, n: int = 4) -> set:
    w = words(t)
    return {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}


def blocks_of(plan: dict, label: str = None) -> list:
    """[(일차, 라벨, 글)]"""
    return [(d["day"], b["label"], b["text"]) for d in plan["days"] for b in d["blocks"] if label in (None, b["label"])]


# ---------- 반복 구절 ----------
def repeated_phrases(items: list, n: int = 4, max_df: int = MAX_DF, allowed=ALLOWED) -> list:
    """items: [(일차, 글)]. -> [(구절, [일차...])] 가 max_df 곳을 넘는 것"""
    where = defaultdict(set)
    for day, text in items:
        for a in allowed:            # 되풀이가 맞는 구절은 가리고 센다(옆 낱말과 이어진 4어절도 함께 빠진다)
            text = text.replace(a, " · ")
        for g in grams(text, n):
            where[g].add(day)
    return sorted(((g, sorted(ds)) for g, ds in where.items() if len(ds) > max_df), key=lambda x: -len(x[1]))


# ---------- 복붙: 글자 3-gram 코사인 ----------
def _vectors(texts: dict):
    raw = {k: Counter(re.sub(r"\s+", "", t)[i:i + 3] for i in range(max(0, len(re.sub(r"\s+", "", t)) - 2))) for k, t in texts.items()}
    n = len(raw)
    df = Counter()
    for v in raw.values():
        df.update(v.keys())
    idf = {g: math.log(n / c) for g, c in df.items()}
    vec = {}
    for k, v in raw.items():
        w = {g: (1 + math.log(c)) * idf[g] for g, c in v.items()}
        z = math.sqrt(sum(x * x for x in w.values())) or 1.0
        vec[k] = {g: x / z for g, x in w.items()}
    return vec, idf


def nearest(texts: dict) -> dict:
    """{키: (가장 가까운 이웃 키, 유사도)}"""
    vec, idf = _vectors(texts)
    floor = min(1.5, 0.4 * math.log(max(2, len(texts))))   # 흔한 3-gram 은 빼는데, 아주 작은 말뭉치에서는 기준을 낮춘다
    inv = defaultdict(list)
    for k, v in vec.items():
        for g, x in v.items():
            if idf[g] > floor:
                inv[g].append((k, x))
    out = {}
    for k, v in vec.items():
        acc = defaultdict(float)
        for g, x in v.items():
            if idf[g] > floor:
                for j, y in inv[g]:
                    if j != k:
                        acc[j] += x * y
        if acc:
            j = max(acc, key=acc.get)
            out[k] = (j, acc[j])
    return out


def near_copies(texts: dict, threshold: float = NEAR_COPY, only=None, min_chars: int = MIN_CHARS) -> list:
    """texts: {키: 글}. -> [(유사도, 키, 이웃)]. only 가 있으면 그 키들만 본다. min_chars 보다 짧은 글은 뺀다."""
    nn = nearest({k: t for k, t in texts.items() if len(t) >= min_chars})
    return sorted(((s, k, j) for k, (j, s) in nn.items() if s >= threshold and (only is None or k in only)), reverse=True)


# ---------- 분포 ----------
def distribution(texts: dict, max_first=MAX_FIRST_WORD, max_second=MAX_SECOND_WORD, max_end=MAX_ENDING) -> dict:
    """texts: {일차: 오늘 단락}. -> {'first': Counter, 'second': Counter, 'end': Counter, 'problems': [...]}"""
    first, second, end = Counter(), Counter(), Counter()
    for t in texts.values():
        ss = sentences(t)
        if not ss:
            continue
        first[t.split()[0]] += 1
        if len(ss) > 1:
            second[ss[1].split()[0]] += 1
        end[re.sub(r"[.!?]+$", "", ss[-1])[-4:]] += 1
    n = max(1, len(texts))
    problems = []
    if len(texts) < MIN_SAMPLES:
        return {"first": first, "second": second, "end": end, "problems": problems}
    for name, cnt, cap in (("첫 어절", first, max_first), ("둘째 문장의 첫 어절", second, max_second), ("마지막 네 글자", end, max_end)):
        for w, c in cnt.most_common(3):
            if c / n > cap:
                problems.append(f"{name} '{w}' 이 {c}/{n} = {c * 100 / n:.1f}% (상한 {cap * 100:.1f}%)")
    return {"first": first, "second": second, "end": end, "problems": problems}


# ---------- 훑어볼 목록: 첫 문장에서 드문 낱말을 둘 이상 같이 쓰는 쌍 ----------
_PARTICLE = re.compile(r"(에서는|에서도|에서|에게|으로|까지|부터|처럼|보다|이라|이나|이며|하고|하는|하며|하면|한|할|인|이|가|은|는|을|를|의|에|도|만|과|와|로|들|께)$")
_COMMON = set("사람 때문 가운데 생각 처음 하나 모습 시간 마음 하루 이야기 일이 자기 우리".split())


def _terms(sentence: str) -> set:
    out = set()
    for w in re.findall(r"[가-힣]{2,}", sentence):
        w2 = _particle_free(w)
        if len(w2) >= 2 and w2 not in _COMMON:
            out.add(w2)
    return out


def _particle_free(w: str) -> str:
    return _PARTICLE.sub("", w) if len(w) > 2 else w


def scene_pairs(first_sentences: dict, max_df: int = 4, min_shared: int = 2) -> list:
    """{일차: 첫 문장}. -> [(일차, 일차, [같이 쓴 드문 낱말])]. 후보 목록이며 통과 기준이 아니다(글자 통계로는 장면을 다 못 잡는다)."""
    terms = {d: _terms(s) for d, s in first_sentences.items()}
    df = Counter()
    for s in terms.values():
        df.update(s)
    inv = defaultdict(list)
    for d, s in terms.items():
        for w in s:
            if 2 <= df[w] <= max_df:
                inv[w].append(d)
    shared = defaultdict(list)
    for w, ds in inv.items():
        for i in range(len(ds)):
            for j in range(i + 1, len(ds)):
                shared[(min(ds[i], ds[j]), max(ds[i], ds[j]))].append(w)
    return sorted(((a, b, sorted(ws)) for (a, b), ws in shared.items() if len(ws) >= min_shared), key=lambda x: -len(x[2]))


# ---------- 장면 장부 ----------
# 장부 짜임: {"scenes": {"<일차>": {"name": 장면 이름, "category": 범주, "words": [필수어 2~3개], "link": 본문과 장면이 이어지는 한 줄}}}
def ledger_shape_problems(ledger: dict, existing_texts: dict = None) -> list:
    """장부 자체의 문제. existing_texts({일차: 글})가 있으면 필수어가 다른 날의 글에 이미 있는지도 본다."""
    sc = ledger.get("scenes", {})
    out, names, owner = [], {}, {}
    for day, s in sc.items():
        for key in ("name", "category", "words", "link"):
            if not s.get(key):
                out.append(f"{day}일: '{key}' 가 비었습니다")
        if s.get("category") and s["category"] not in CATEGORIES:
            out.append(f"{day}일: 범주 '{s['category']}' 는 목록에 없습니다")
        ws = s.get("words") or []
        if not 2 <= len(ws) <= 3:
            out.append(f"{day}일: 필수어는 2~3개여야 합니다({len(ws)}개)")
        for w in ws:
            if len(w) < 2 or not re.fullmatch(r"[가-힣]+", w):
                out.append(f"{day}일: 필수어 '{w}' 는 두 글자 이상의 한글이어야 합니다")
            if w in owner and owner[w] != day:
                out.append(f"필수어 '{w}' 가 {owner[w]}일과 {day}일에 같이 있습니다")
            owner.setdefault(w, day)
        nm = re.sub(r"\s+", "", s.get("name", ""))
        if nm and nm in names:
            out.append(f"장면 이름 '{s['name']}' 이 {names[nm]}일과 {day}일에 겹칩니다")
        names.setdefault(nm, day)
    if existing_texts:
        for w, day in owner.items():
            hits = [d for d, t in existing_texts.items() if str(d) != str(day) and w in t]
            if hits:
                out.append(f"필수어 '{w}' ({day}일)가 다른 날 {len(hits)}곳({', '.join(map(str, hits[:4]))}…)에 이미 있습니다")
    return out


def name_grams(name: str) -> frozenset:
    s = re.sub(r"\s+", "", name)
    return frozenset(s[i:i + 2] for i in range(len(s) - 1))


def similar_names(names: dict, others: dict = None, min_jaccard: float = NAME_SIMILAR) -> list:
    """장면 이름이 비슷한 쌍. names={키: 이름}. others 가 있으면 names 와 others 사이만, 없으면 names 안에서만 본다.
    글자 두 개씩 묶은 집합의 자카드 값이 min_jaccard 이상인 쌍을 큰 순서로 [(값, 키, 키)] 로 준다.
    본문 글자로는 못 잡는 같은 장면을 이름으로는 잡는다(기존 1000일 이름에서 0.3 이상 11쌍, 대부분 같은 장면)."""
    a = {k: name_grams(v) for k, v in names.items()}
    b = {k: name_grams(v) for k, v in others.items()} if others is not None else a
    index = defaultdict(set)                       # 글자 묶음 -> b 의 키: 아무것도 안 겹치는 쌍은 아예 보지 않는다
    for k, g in b.items():
        for x in g:
            index[x].add(k)
    def order(k):                                  # 일차 문자열은 숫자 순서로
        return (0, int(k), "") if str(k).isdigit() else (1, 0, str(k))
    out = []
    for ka, ga in a.items():
        near = Counter(k for x in ga for k in index.get(x, ()))
        for kb, shared in near.items():
            if others is None and order(kb) <= order(ka):
                continue
            union = len(ga) + len(b[kb]) - shared
            j = shared / union if union else 0.0
            if j >= min_jaccard:
                out.append((round(j, 3), ka, kb))
    return sorted(out, key=lambda t: (-t[0], order(t[1]), order(t[2])))


def scene_problems(ledger: dict, texts: dict) -> list:
    """texts: {일차: 오늘 단락}. 장부에 있는 날은 자기 필수어를 첫 두 문장에 쓰고, 다른 날의 필수어는 쓰지 않아야 한다."""
    sc = ledger.get("scenes", {})
    all_words = {w: str(day) for day, s in sc.items() for w in s.get("words", [])}
    out = []
    for day, t in texts.items():
        mine = sc.get(str(day))
        if mine:
            head = " ".join(sentences(t)[:2])
            need = max(1, math.ceil(len(mine["words"]) / 2))
            got = [w for w in mine["words"] if w in head]
            if len(got) < need:
                out.append(f"{day}일: 배정된 장면 '{mine['name']}' 의 필수어({', '.join(mine['words'])})가 첫 두 문장에 {len(got)}개뿐입니다(필요 {need}개)")
        for w, owner in all_words.items():
            if owner != str(day) and w in t:
                out.append(f"{day}일: {owner}일의 필수어 '{w}' 를 썼습니다")
    return out


def window_problems(ledger: dict, order: list, windows=WINDOWS, share: float = CATEGORY_SHARE) -> list:
    """order: 읽는 순서대로의 일차 목록. 같은 범주가 7일, 30일 창과 전체 비중을 넘지 않는지 본다."""
    cats = [ledger["scenes"].get(str(d), {}).get("category") for d in order]
    out = []
    for size, cap in windows:
        for i in range(0, max(1, len(cats) - size + 1)):
            cnt = Counter(c for c in cats[i:i + size] if c)
            for c, n in cnt.items():
                if n > cap:
                    out.append(f"{order[i]}일부터 {size}일 안에 범주 '{c}' 가 {n}번입니다(상한 {cap})")
                    break
            else:
                continue
            break   # 창마다 첫 위반만 알린다
    total = Counter(c for c in cats if c)
    for c, n in total.items():
        if n / max(1, len(order)) > share:
            out.append(f"범주 '{c}' 가 전체의 {n * 100 / len(order):.1f}%입니다(상한 {share * 100:.0f}%)")
    return out


def route_problems(ledger: dict, orders: dict, run: tuple = ROUTE_RUN) -> list:
    """orders: {길 이름: 그 길의 일차 순서}. 길을 따라 읽을 때 연속 run[0]개 안에 서로 다른 범주가 run[1]개 이상이어야 한다."""
    size, need = run
    out = []
    for name, days in orders.items():
        cats = [ledger["scenes"].get(str(d), {}).get("category") for d in days]
        for i in range(0, len(cats) - size + 1):
            seg = [c for c in cats[i:i + size] if c]
            if len(seg) == size and len(set(seg)) < need:
                out.append(f"길 '{name}' 의 {days[i]}일부터 {size}개에 서로 다른 범주가 {len(set(seg))}개뿐입니다(필요 {need}개)")
                break
    return out


# ---------- 합치기 ----------
def corpus_problems(plan: dict, max_df: int = MAX_DF) -> list:
    """plan.json 전체의 문제 목록: 반복 구절, 복붙, 분포"""
    items = blocks_of(plan)
    out = [f"4어절 '{g}' 이 {len(ds)}곳에 있습니다(상한 {max_df}): {ds[:5]}" for g, ds in repeated_phrases([(d, t) for d, _l, t in items], max_df=max_df)]
    for label in {l for _d, l, _t in items}:
        if label.startswith("한 단어"):
            continue
        texts = {d: t for d, l, t in items if l == label}
        out += [f"'{label}' {a}일과 {b}일이 거의 같은 글입니다(유사도 {s:.2f})" for s, a, b in near_copies(texts)]
    today = {d: t for d, l, t in items if l == "오늘"}
    out += distribution(today)["problems"]
    return out


def candidate_problems(plan: dict, candidate: list, ledger: dict = None, max_df: int = MAX_DF) -> list:
    """새로 쓴 '오늘' 단락(candidate: [{"day": n, "text": "..."}])을 기존 plan 과 합쳐서 점검한다. 새 글이 관련된 문제만 돌려준다."""
    new = {c["day"]: c["text"] for c in candidate}
    base = {d: t for d, l, t in blocks_of(plan, "오늘") if d not in new}
    out = []
    items = [(d, t) for d, _l, t in blocks_of(plan) if d not in new] + list(new.items())
    for g, ds in repeated_phrases(items, max_df=max_df):
        if set(ds) & set(new):
            out.append(f"4어절 '{g}' 이 {len(ds)}곳에 있습니다(상한 {max_df}): {ds[:5]}")
    out += [f"{k}일이 {j}일과 거의 같은 글입니다(유사도 {s:.2f})" for s, k, j in near_copies({**base, **new}, only=set(new))]
    out += distribution({**base, **new})["problems"]
    if ledger:
        out += scene_problems(ledger, new)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", default=str(ROOT / "data" / "plan.json"))
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--candidate")
    ap.add_argument("--ledger")
    ap.add_argument("--ledger-check")
    a = ap.parse_args(argv)
    plan = planio.read_plan(a.plan)
    if a.report:
        items = blocks_of(plan)
        today = {d: t for d, l, t in items if l == "오늘"}
        dist = distribution(today)
        print(f"블록 {len(items)}개, 오늘 단락 {len(today)}개")
        for name in ("first", "second", "end"):
            print({"first": "첫 어절", "second": "둘째 문장 첫 어절", "end": "마지막 네 글자"}[name], dist[name].most_common(6))
        rep = repeated_phrases([(d, t) for d, _l, t in items], max_df=2)
        print(f"4어절이 3곳 이상: {len(rep)}개", [(g, len(ds)) for g, ds in rep[:5]])
        nn = sorted((s for _k, (_j, s) in nearest(today).items()), reverse=True)
        print(f"가장 가까운 이웃 유사도: 최대 {nn[0]:.3f}, 99% {nn[len(nn) // 100]:.3f}, 중앙 {nn[len(nn) // 2]:.3f}")
        firsts = {d: sentences(t)[0] for d, t in today.items()}
        pairs = scene_pairs(firsts)
        print(f"첫 문장에서 드문 낱말을 둘 이상 같이 쓴 쌍(훑어볼 목록): {len(pairs)}쌍", [(x, y, w) for x, y, w in pairs[:5]])
        return 0
    if a.candidate:
        ledger = json.loads(Path(a.ledger).read_text(encoding="utf-8")) if a.ledger else None
        errs = candidate_problems(plan, json.loads(Path(a.candidate).read_text(encoding="utf-8")), ledger)
        print("\n".join(errs[:40]) if errs else "새 단락 점검: 통과")
        return 1 if errs else 0
    if a.ledger_check:
        ledger = json.loads(Path(a.ledger_check).read_text(encoding="utf-8"))
        texts = {d: t for d, l, t in blocks_of(plan, "오늘")}
        errs = ledger_shape_problems(ledger) + window_problems(ledger, sorted(int(d) for d in ledger["scenes"]))
        print("\n".join(errs[:40]) if errs else f"장부 점검: 통과 ({len(ledger['scenes'])}일)")
        return 1 if errs else 0
    errs = corpus_problems(plan)
    print("\n".join(errs[:40]) if errs else "전체 점검: 통과")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
