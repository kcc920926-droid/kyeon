"""암송 모드용 가림 단계(lv)를 계산한다. 새 날을 plan.json 에 넣을 때 쓴다.

글자마다 단계 코드를 붙인다.
  0 = 가리지 않음(공백, 문장부호)
  1 = 핵심 단어(구절마다 1~3개, 그 구절의 대표 단어)
  2 = 뜻이 중요한 명사·형용사(성경에서 드물게 나오는 낱말, 그날 제목에 든 낱말)
  3 = 그 밖의 내용어(명사, 대명사, 수사, 동사, 부사, 관형사 등)
  4 = 조사, 어미, 접사 등(어느 단계에서도 안 가림)
n 단계에서는 코드 1..n 인 글자를 가린다. 단계가 올라갈수록 더 많이 가려진다.
결과는 날마다 구절 수만큼의 숫자 문자열 목록이고, 각 문자열은 구절 본문과 길이가 같다.

계산은 두 걸음이다. 먼저 옛 방식(0 가리지 않음, 1 핵심, 2 내용어 전부, 3 나머지)으로 나누고(base_levels),
다음에 2를 '중요한 낱말이면 2, 아니면 3'으로 가르고 3을 4로 옮긴다(migrate_verse). 이 둘을 합친 것이 build_day 다.

  python tools/make_lv.py --days build/days.json --out build/lv.json    days.json: [{"day", "title", "verses": [[장, 절, 글], ...]}]
  python tools/make_lv.py --verify [--all]                               plan.json 의 날을 다시 계산해 지금 값과 같은지 본다

재현 시험(kiwipiepy 0.24.0, T=2.5): lv 가 있는 1000일 가운데 998일이 지금 값과 정확히 같다. 낱말 빈도(df)는 예전 계산과 10,913개 전부 같았다.
같지 않은 2일(780, 977일)은 핵심 단어로 뽑힌 낱말만 다르다. 핵심 단어를 고르는 점수에 제목이 들어가는데, 처음 계산할 때는 제목이
아직 없었거나(시편 198일은 빈 제목) 지금과 다른 임시 제목이었다. --verify 는 제목 없이 계산한 값과 같아도 같은 것으로 친다.

kiwipiepy(Kiwi 형태소 분석기, LGPL-2.1)가 필요하다. 계산할 때만 쓰고 이 저장소와 배포물에는 넣지 않는다.
임시 가상환경에서 `pip install kiwipiepy` 한 뒤 그 파이썬으로 실행한다. 핵심 키워드는 성경 전체에서 낱말이 나온 구절 수(df)로
고르는데, 이 값은 build/krv.json 에서 한 번 계산해 build/lv_df.json 에 저장해 둔다(저장소에 올리지 않는다).
"""
import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bible  # noqa: E402
import planio  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DF_CACHE = ROOT / "build" / "lv_df.json"
IMPORTANCE = 2.5                          # 중요한 낱말의 문턱: 성경에서 낱말이 나온 구절 수의 로그 역수(idf)가 이 값 이상이면 중요하다. 지금 plan.json 의 lv 를 재현하는 값(2.48~2.58)

CONTENT = {"NNG", "NNP", "NNB", "NR", "NP", "VV", "VA", "VX", "MM", "MAG", "XR", "IC", "SN", "SL", "SH"}
KEY_TAGS = {"NNG", "NNP", "XR"}          # 핵심 키워드 후보(명사류)
KEY_FALLBACK = {"VV", "VA", "MAG"}        # 명사가 하나도 없는 구절에서만
CAND = {"NNG", "NNP", "XR", "VA"}         # 중요한 낱말 후보: 명사류와 형용사. 대명사, 의존명사, 수사, 동사, 부사는 중요 낱말로 치지 않는다
NOUNISH = {"NNG", "NNP", "XR", "XPN", "XSN"}   # 붙어 있으면 한 낱말처럼 다룰 명사류(두령 = 두 + 령)
PUNCT_PREFIX = "S"                        # SF SP SS SSO SSC SE SO SW … 는 가리지 않는다

# 개역한글 인쇄본에 실제로 있는 표기: 앞 구절에 내용이 합쳐진 자리에 '(앞절과 동일)', '12절과 상동', '상동' 이 찍혀 있다.
# 본문은 그대로 보여 주되 암송 모드에서도 가리지 않는다.
MERGED = re.compile(r"[(\[]?\s*(?:\d+절과 (?:상동|같음)|앞절과 동일|상동)\s*[)\]]?")


def base_tag(t: str) -> str:
    return t.split("-")[0]


def level_of(tag: str) -> int:
    t = base_tag(tag)
    if t in CONTENT:
        return 2
    if t.startswith(PUNCT_PREFIX):
        return 0
    return 3


def kiwi_tokenizer():
    """-> (tokenize(text) -> [(형태, 품사, 시작, 길이)], tokenize_many(texts) -> [[...]])"""
    from kiwipiepy import Kiwi   # 계산할 때만 필요하다
    kiwi = Kiwi()

    def one(text):
        return [(x.form, base_tag(x.tag), x.start, x.len) for x in kiwi.tokenize(text) if x.len > 0]

    def many(texts):
        return [[(x.form, base_tag(x.tag), x.start, x.len) for x in toks if x.len > 0] for toks in kiwi.tokenize(texts)]
    return one, many


def verse_frequency(db: dict, tokenize_many) -> dict:
    """성경 전체(31,102절)에서 낱말이 나온 구절 수. df 는 낱말만으로, dft 는 '낱말|품사'로 센다."""
    verses = [bible.normalize(t) for b in db.values() for c in b.values() for t in c.values()]
    df, dft = Counter(), Counter()
    for toks in tokenize_many(verses):
        df.update({f for f, tg, _s, _l in toks if tg in KEY_TAGS})
        dft.update({f"{f}|{tg}" for f, tg, _s, _l in toks if tg in CAND})
    return {"n": len(verses), "df": dict(df), "dft": dict(dft)}


def load_frequency(db: dict, tokenize_many, cache: Path = DF_CACHE) -> dict:
    if cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))
    freq = verse_frequency(db, tokenize_many)
    cache.parent.mkdir(exist_ok=True)
    cache.write_text(json.dumps(freq, ensure_ascii=False), encoding="utf-8")
    return freq


def key_score(form, tag, title, in_passage, picked, freq):
    n = freq["n"]
    cap = math.log(n / 8)
    s = min(math.log(n / max(freq["df"].get(form, 1), 1)), cap)
    if len(form) == 1:
        s -= 2.0            # 한 글자(해, 주, 일 …)는 키워드로 약함
    if title and form in title:
        s += 2.0
    s += 1.0 * min(in_passage[form] - 1, 2)   # 본문 안에서 거듭 나오는 낱말은 주제어
    if picked[form] >= 2:
        s -= 3.0            # 같은 낱말만 계속 가리지 않게
    if tag == "XR":
        s -= 0.5
    return s


def base_levels(item: dict, tokenize, freq: dict, title=None):
    """옛 방식의 0~3 코드. item: {"title", "verses": [[장, 절, 글], ...]}. -> (구절마다 단계 문자열 목록, 구절마다 핵심 키워드 목록)
    title 을 따로 주면 핵심 단어를 고를 때 item 의 제목 대신 그것을 쓴다(제목 없이 계산하던 때를 재현할 때)."""
    verses = item["verses"]
    title = (item.get("title") or "") if title is None else title
    toks_by_verse = [tokenize(t) for _c, _v, t in verses]
    in_passage = Counter(f for toks in toks_by_verse for f, tg, _s, _l in toks if tg in KEY_TAGS)
    picked = Counter()
    out, keywords = [], []
    for (c, v, text), toks in zip(verses, toks_by_verse):
        if MERGED.fullmatch(text):
            out.append("0" * len(text))
            keywords.append([])
            continue
        lv = [0] * len(text)
        has = [False] * len(text)
        for form, tg, st, ln in toks:
            lvl = level_of(tg)
            for i in range(st, min(st + ln, len(text))):
                if text[i] == " ":
                    continue
                # 한 글자에 형태소가 겹치면(잘 = 자+ㄹ) 내용어 쪽(작은 단계)을 따른다
                lv[i] = lvl if not has[i] else min(lv[i], lvl)
                has[i] = True
        for i, ch in enumerate(text):  # 형태소로 덮이지 않은 글자 처리
            if ch == " ":
                lv[i] = 0
            elif not has[i]:
                lv[i] = 3 if "가" <= ch <= "힣" else 0
        k = max(1, min(3, round(len(text) / 70)))
        cands = [(key_score(f, tg, title, in_passage, picked, freq), st, ln, f) for f, tg, st, ln in toks if tg in KEY_TAGS]
        if not cands:
            cands = [(0.0, st, ln, f) for f, tg, st, ln in toks if tg in KEY_FALLBACK]
        cands.sort(key=lambda x: (-x[0], x[1]))
        seen, chosen = set(), []
        for _sc, st, ln, f in cands:
            if f in seen:
                continue
            seen.add(f)
            chosen.append((st, ln, f))
            picked[f] += 1
            if len(chosen) >= k:
                break
        for st, ln, f in chosen:
            for i in range(st, st + ln):
                if text[i] != " ":
                    lv[i] = 1
        keywords.append([f for _st, _ln, f in sorted(chosen)])
        out.append("".join(str(x) for x in lv))
    return out, keywords


def _important(form, tag, title, freq, T=IMPORTANCE):
    """뜻이 중요한 명사·형용사인가: 성경에서 드물게 나올수록 중요하다. 한 글자 낱말은 더 드물어야 한다. 그날 제목에 든 낱말은 중요하다."""
    if tag not in CAND:
        return False
    if title and len(form) >= 2 and form in title:
        return True
    need = T + (1.0 if len(form) == 1 else 0.0)
    return math.log(freq["n"] / max(freq["dft"].get(f"{form}|{tag}", 0), 1)) >= need


def migrate_verse(text: str, old: str, title: str, tokenize, freq: dict, T=IMPORTANCE) -> str:
    """옛 0~3 코드를 0~4 코드로 옮긴다. 옛 2(내용어)는 중요하면 2, 아니면 3, 옛 3(조사, 어미)은 4가 된다."""
    toks = tokenize(text)
    imp = [False] * len(text)
    spans, cur = [], []
    for tok in toks:   # 사이에 공백 없이 이어진 명사류는 한 덩어리로 묶는다(낱말의 일부만 가려지지 않게)
        if tok[1] in NOUNISH and cur and tok[2] == cur[-1][2] + cur[-1][3]:
            cur.append(tok)
            continue
        if cur:
            spans.append(cur)
        cur = [tok] if tok[1] in NOUNISH else []
    if cur:
        spans.append(cur)
    for span in spans:
        if any(_important(f, tg, title, freq, T) for f, tg, _s, _l in span):
            for _f, _tg, st, ln in span:
                for i in range(st, min(st + ln, len(text))):
                    imp[i] = True
    for form, tag, st, ln in toks:
        if tag == "VA" and _important(form, tag, title, freq, T):   # 형용사는 어간만(어미는 남는다)
            for i in range(st, min(st + ln, len(text))):
                imp[i] = True
    out = []
    for i, c in enumerate(old):
        if c == "2":
            out.append("2" if imp[i] else "3")
        elif c == "3":
            out.append("4")
        else:
            out.append(c)
    return "".join(out)


def build_day(item: dict, tokenize, freq: dict, T=IMPORTANCE, base_title=None):
    """item 의 lv(0~4 코드)와 구절마다 핵심 단어를 계산한다. -> (구절마다 단계 문자열 목록, 구절마다 핵심 단어 목록)
    base_title 은 base_levels 의 title 인자다(보통은 쓰지 않는다)."""
    old, keywords = base_levels(item, tokenize, freq, base_title)
    title = item.get("title") or ""
    out = [s if MERGED.fullmatch(v[2]) else migrate_verse(v[2], s, title, tokenize, freq, T) for v, s in zip(item["verses"], old)]
    return out, keywords


def check_lv(item: dict, lv: list) -> list:
    """계산 결과의 짜임을 점검한다(분석기와 무관). 문제 목록."""
    problems = []
    if len(lv) != len(item["verses"]):
        return [f"구절 수가 다릅니다: lv {len(lv)}, 본문 {len(item['verses'])}"]
    for (c, v, t), s in zip(item["verses"], lv):
        if len(s) != len(t):
            problems.append(f"{c}:{v} 길이가 다릅니다({len(s)} != {len(t)})")
        elif not set(s) <= set("01234"):
            problems.append(f"{c}:{v} 에 0~4 가 아닌 코드가 있습니다")
        elif any(ch == " " and code != "0" for ch, code in zip(t, s)):
            problems.append(f"{c}:{v} 의 공백에 0 이 아닌 코드가 있습니다")
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bible", default=str(bible.DEFAULT_SOURCE))
    ap.add_argument("--plan", default=str(ROOT / "data" / "plan.json"))
    ap.add_argument("--days")
    ap.add_argument("--out")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--sample", type=int, default=40)
    ap.add_argument("--all", action="store_true", help="--verify 에서 표본이 아니라 lv 가 있는 날 전부를 본다")
    ap.add_argument("--T", type=float, default=IMPORTANCE, help="중요한 낱말의 문턱")
    a = ap.parse_args(argv)
    tokenize, many = kiwi_tokenizer()
    freq = load_frequency(bible.load_db(a.bible), many)
    if a.verify:
        plan = planio.read_plan(a.plan)
        days = [d for d in plan["days"] if d.get("lv")]
        if not a.all:
            days = days[::max(1, len(days) // a.sample)]
        same = blank = diff = 0
        for d in days:
            got, _kw = build_day(d, tokenize, freq, a.T)
            if got == d["lv"]:
                same += 1
                continue
            # 지금 plan 의 lv 는 제목이 아직 없던 시편 198일에서 핵심 단어를 제목 없이 골랐다. 그 경우도 같은 값으로 친다.
            got2, _kw = build_day(d, tokenize, freq, a.T, base_title="")
            if got2 == d["lv"]:
                blank += 1
            else:
                diff += 1
                print(f"{d['day']}일 {d['ref']}: 지금 값과 다릅니다")
        print(f"T={a.T}: 다시 계산한 날 {len(days)}개 중 같은 날 {same}개, 제목 없이 계산한 날과 같은 날 {blank}개, 다른 날 {diff}개")
        return 1 if diff else 0
    if not (a.days and a.out):
        ap.error("--days 와 --out 이 필요합니다")
    items = json.loads(Path(a.days).read_text(encoding="utf-8"))
    result, bad = {}, []
    for it in items:
        lv, _kw = build_day(it, tokenize, freq)
        bad += [f"{it['day']}일: {p}" for p in check_lv(it, lv)]
        result[it["day"]] = lv
    Path(a.out).write_text(json.dumps(result), encoding="utf-8")
    print(f"{a.out} 에 {len(result)}일을 썼습니다", "점검 통과" if not bad else f"문제 {len(bad)}개\n" + "\n".join(bad[:10]))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
