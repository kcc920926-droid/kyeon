"""장면 장부(ledger/scenes.json)를 만든다. 날마다 오늘 단락의 장면에 이름, 범주, 필수어를 붙인 기준 자료다.

  python tools/ledger.py --prepare DIR [--size 200]              에이전트에게 줄 입력(조각마다 일차, 참조, 제목, 오늘 단락 첫 두 문장)을 만든다
  python tools/ledger.py --check-names F --in DIR                에이전트가 쓴 이름·범주·연결고리 파일(F)의 짜임을 점검한다
  python tools/ledger.py --build F --out ledger/scenes.json      F 와 형태소 분석으로 장부를 만든다(필수어는 코드가 고른다)
  python tools/ledger.py --report ledger/scenes.json             범주 분포, 7일과 30일 창, 길 순서 점검 결과를 보여 준다

역할 나누기
  장면의 이름, 범주, 본문과 이어지는 한 줄은 글을 읽어야 해서 LLM 이 쓴다.
  필수어는 코드가 고른다. 그 날 첫 두 문장의 명사 가운데 **다른 날의 오늘 단락 어디에도 없는** 낱말을 2~3개 뽑는다.
  이런 낱말이 둘 미만이면 그 장면은 다른 날과 겹칠 수 있다는 뜻이므로 `review` 표시를 달고 겹치는 날을 알려 준다.
필수어를 고를 때 형태소 분석기(kiwipiepy)가 필요하다. tools/make_lv.py 와 같은 방식으로 임시 가상환경에서 실행한다.
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dupcheck  # noqa: E402
import planio  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NOUNS = {"NNG", "NNP"}
MIN_WORD, WANT_WORDS = 2, 3


def head(text: str, n: int = 2) -> str:
    return " ".join(dupcheck.sentences(text)[:n])


def today_texts(plan: dict) -> dict:
    return {d: t for d, l, t in dupcheck.blocks_of(plan, "오늘")}


def prepare(plan: dict, out_dir: Path, size: int = 200) -> int:
    """에이전트에게 줄 입력을 조각 파일로 쓴다. -> 조각 수"""
    out_dir.mkdir(parents=True, exist_ok=True)
    texts = today_texts(plan)
    items = [{"day": d["day"], "ref": d["ref"], "title": d["title"], "head": head(texts[d["day"]])} for d in plan["days"] if d["day"] in texts]
    n = 0
    for i in range(0, len(items), size):
        n += 1
        (out_dir / f"chunk_{n:02d}.json").write_text(json.dumps(items[i:i + size], ensure_ascii=False, indent=1), encoding="utf-8")
    return n


def check_names(names: list, expected_days: list) -> list:
    """에이전트가 쓴 [{"day", "name", "category", "link"}]의 짜임을 점검한다. 문제 목록."""
    out, seen = [], {}
    by = {}
    for x in names:
        by.setdefault(x.get("day"), []).append(x)
    for d in expected_days:
        got = by.get(d, [])
        if len(got) != 1:
            out.append(f"{d}일: 항목이 {len(got)}개입니다")
            continue
        x = got[0]
        if x.get("category") not in dupcheck.CATEGORIES:
            out.append(f"{d}일: 범주 '{x.get('category')}' 는 목록에 없습니다")
        nm = (x.get("name") or "").strip()
        if not 4 <= len(nm) <= 40:
            out.append(f"{d}일: 장면 이름은 4~40자여야 합니다('{nm}')")
        if not 4 <= len((x.get("link") or "").strip()) <= 80:
            out.append(f"{d}일: 연결고리는 4~80자여야 합니다")
        key = re.sub(r"\s+", "", nm)
        if key in seen:
            out.append(f"{d}일: 장면 이름 '{nm}' 이 {seen[key]}일과 같습니다")
        seen.setdefault(key, d)
    extra = set(by) - set(expected_days)
    if extra:
        out.append(f"입력에 없는 일차가 있습니다: {sorted(extra, key=str)[:5]}")
    return out


def candidate_nouns(text: str, tokenize) -> list:
    """첫 두 문장의 명사(두 글자 이상). 나온 순서대로, 중복 없이."""
    seen, out = set(), []
    for form, tag, _st, _ln in tokenize(head(text)):
        if tag in NOUNS and len(form) >= MIN_WORD and re.fullmatch(r"[가-힣]+", form) and form not in seen:
            seen.add(form)
            out.append(form)
    return out


def pick_words(day: int, texts: dict, tokenize) -> tuple:
    """-> (필수어 목록, 겹치는 날 목록). 다른 날의 오늘 단락 어디에도 없는 명사를 우선한다. 긴 낱말이 먼저다."""
    others = {d: t for d, t in texts.items() if d != day}
    scored, shared = [], Counter()
    for w in candidate_nouns(texts[day], tokenize):
        hits = [d for d, t in others.items() if w in t]
        if not hits:
            scored.append((-len(w), w))
        else:
            shared.update(hits)
    scored.sort()
    words = [w for _l, w in scored[:WANT_WORDS]]
    overlap = [d for d, _n in shared.most_common(3)] if len(words) < 2 else []
    return words, overlap


def build(plan: dict, names: list, tokenize) -> dict:
    texts = today_texts(plan)
    by = {x["day"]: x for x in names}
    scenes, review = {}, 0
    for d in sorted(texts):
        x = by[d]
        words, overlap = pick_words(d, texts, tokenize)
        sc = {"name": x["name"].strip(), "category": x["category"], "words": words, "link": x["link"].strip()}
        if len(words) < 2:
            sc["review"] = True
            sc["overlaps_with"] = overlap
            review += 1
        scenes[str(d)] = sc
    return {"meta": {"days": len(scenes), "review": review}, "scenes": scenes}


def report(ledger: dict, order: list = None, orders: dict = None) -> str:
    sc = ledger["scenes"]
    cats = Counter(s["category"] for s in sc.values())
    n = len(sc)
    lines = [f"장면 {n}개, 필수어를 둘 못 얻은 장면 {sum(1 for s in sc.values() if s.get('review'))}개(기존 글에 흔한 낱말뿐이라는 뜻이고 겹친다는 뜻은 아닙니다)",
             "범주 비중: " + ", ".join(f"{c} {k} ({k * 100 / n:.1f}%)" for c, k in cats.most_common())]
    pairs = dupcheck.similar_names({d: s["name"] for d, s in sc.items()})
    lines.append(f"이름이 비슷한 쌍 {len(pairs)}개(같은 장면일 수 있으니 훑어볼 것)")
    lines += [f"  {j:.2f}  {a}일 '{sc[a]['name']}' ↔ {b}일 '{sc[b]['name']}'" for j, a, b in pairs[:8]]
    order = order or sorted(int(d) for d in sc)
    shape = [p for p in dupcheck.ledger_shape_problems({"scenes": {k: v for k, v in sc.items() if not v.get("review")}})]
    win = dupcheck.window_problems(ledger, order)
    lines.append(f"장부 짜임 문제 {len(shape)}개, 창 규칙 위반 {len(win)}개")
    lines += [f"  {p}" for p in shape[:5]] + [f"  {p}" for p in win[:8]]
    if orders:
        rp = dupcheck.route_problems(ledger, orders)
        lines.append(f"길 순서 위반 {len(rp)}개")
        lines += [f"  {p}" for p in rp[:5]]
    return "\n".join(lines)


def route_orders(plan: dict) -> dict:
    """앱이 보여 주는 길(전체, 시기, 테마, 갈래)마다 일차 순서. kyeon.py 를 불러 쓴다."""
    sys.path.insert(0, str(ROOT))
    import kyeon
    days = plan["days"]
    return {f"{r['kind']}:{r['name']}": [days[i]["day"] for i in r["idxs"]] for r in kyeon.build_routes(plan)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", default=str(ROOT / "data" / "plan.json"))
    ap.add_argument("--prepare")
    ap.add_argument("--size", type=int, default=200)
    ap.add_argument("--check-names")
    ap.add_argument("--in", dest="indir")
    ap.add_argument("--build")
    ap.add_argument("--out")
    ap.add_argument("--report")
    a = ap.parse_args(argv)
    plan = planio.read_plan(a.plan)
    if a.prepare:
        print(f"{prepare(plan, Path(a.prepare), a.size)}개 조각을 {a.prepare} 에 썼습니다")
        return 0
    if a.check_names:
        names = json.loads(Path(a.check_names).read_text(encoding="utf-8"))
        errs = check_names(names, sorted(today_texts(plan)))
        print("\n".join(errs[:30]) if errs else f"이름 점검: 통과 ({len(names)}일)")
        return 1 if errs else 0
    if a.build:
        import make_lv
        tokenize, _many = make_lv.kiwi_tokenizer()
        names = json.loads(Path(a.build).read_text(encoding="utf-8"))
        errs = check_names(names, sorted(today_texts(plan)))
        if errs:
            print("\n".join(errs[:20]))
            return 1
        ledger = build(plan, names, tokenize)
        out = Path(a.out or ROOT / "ledger" / "scenes.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(ledger, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{out} 에 장면 {ledger['meta']['days']}개를 썼습니다(겹칠 수 있는 장면 {ledger['meta']['review']}개)")
        return 0
    if a.report:
        ledger = json.loads(Path(a.report).read_text(encoding="utf-8"))
        print(report(ledger, orders=route_orders(plan)))
        return 0
    ap.error("--prepare, --check-names, --build, --report 중 하나가 필요합니다")


if __name__ == "__main__":
    sys.exit(main())
