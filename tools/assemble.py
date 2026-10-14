"""파도(해마다 새로 쓰는 묶음) 조립기. 골격의 하루치 + 에이전트가 쓴 해설을 plan 의 날로 합치고 점검한다.

  python tools/assemble.py --prepare DIR --wave 0 [--limit 60] [--skip 60] [--cats C --menus M --pool P]   쓸 날의 입력(본문, 범주, 장면 메뉴)을 조각 파일로 만든다
  python tools/assemble.py --check DIR                                                         DIR/commentary_NN.json 의 짜임과 문체, 장면 선택을 점검한다
  python tools/assemble.py --assemble DIR --out F [--show N]                                   점검을 통과한 해설로 plan 의 날(lv 포함)과 장부 추가분을 만든다(kiwipiepy 필요). 문제는 N개(기본 40)까지 보여 준다

흐름
  1. prepare: schedule.waves 로 그 해에 쓸 하루치 목록과 일차를 정한다(1001일부터. limit 은 시범으로 앞 일부만 쓸 때).
     날마다 입력 항목: 본문(코드가 만든 verses), 책, 시기, 밀도, 배정된 범주, 장면 메뉴(서로 겹치지 않는 후보 4개).
  2. 에이전트는 입력 항목마다 해설을 쓴다: title, themes, format, blocks, scene(메뉴의 후보 id), link, parallels(있으면).
  3. check: 형식과 라벨, 길이, 번역투(tlint), 장면(메뉴 안인가, 필수어가 첫 두 문장에 있는가, 다른 후보 낱말이 섞이지 않았는가).
  4. assemble: 본문은 다시 원본에서 만들고(에이전트가 건드릴 수 없다), 시기와 참조를 규칙표와 맞춰 보고, lv 를 계산해 날을 만든다.
     마지막으로 plan 전체와 합쳐 말뭉치 점검(반복 구절, 복붙, 분포), 장면 점검, 앱의 day_ok, 길 순서를 본다.
같은 입력이면 항상 같은 결과다.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assign  # noqa: E402
import bible  # noqa: E402
import dupcheck  # noqa: E402
import planio  # noqa: E402
import routes  # noqa: E402
import schedule  # noqa: E402
import themes  # noqa: E402
import tlint  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FIRST_DAY = 1001
FORMAT_LABELS = {                    # 형식 번호: 블록 라벨(앱 시험과 같은 표)
    1: ["그 당시", "오늘"],
    2: ["흔한 읽기", "당시의 뜻", "오늘"],
    3: ["한 단어: {term}", "오늘"],
    4: ["그 자리에서", "오늘"],
    5: ["큰 이야기 속에서", "오늘"],
}
TERM_LABEL = re.compile(r"^한 단어: .{1,10}$")
THEME_IDS = [t["id"] for t in routes.THEMES]
TITLE = (4, 26)                      # docs/STYLE.md 4-3
LINK = (4, 80)
LIMITS = {"흔한 읽기": (30, 130), "오늘": (70, 220)}     # 라벨별 글자 수(공백 포함). docs/STYLE.md 2 의 표. 나머지 블록은 DEFAULT_LIMITS
DEFAULT_LIMITS = (90, 260)
# docs/STYLE.md 4-1 에서 글자로 가려낼 수 있는 것. 지금 plan.json 2151개 블록에는 하나도 없다(쉼표는 6개 블록에만)
FORBIDDEN = [
    ("대시", re.compile(r"[—–]")), ("괄호", re.compile(r"[()\[\]]")), ("마크다운 기호", re.compile(r"[*#`~]")),
    ("영문", re.compile(r"[A-Za-z]")), ("한자", re.compile(r"[一-鿿]")), ("세미콜론", re.compile(r";")),
    ("물음표(수사 의문)", re.compile(r"\?")), ("줄바꿈", re.compile(r"\n")), ("이모지", re.compile("[\U0001F300-\U0001FAFF☀-➿]")),
    ("연결어미 뒤 쉼표", re.compile(r"(?:하고|지만|하며|면서|아서|어서|으나|는데|니까),\s")),
]
DAY_KEYS = ("day", "section", "ref", "title", "era", "themes", "note", "parallels", "verses", "format", "blocks", "lv")


def day_numbers(chunks: list, strategy: str = "spread", wave: int = 0, size: int = 365, limit: int = None, first_day: int = FIRST_DAY) -> list:
    """그 해에 쓸 [(일차, 하루치)]. 일차는 해마다 size 씩 이어 붙으므로 limit(시범)과 상관없이 같다."""
    ws = schedule.waves(chunks, strategy, size)
    if not 0 <= wave < len(ws):
        raise ValueError(f"해는 0~{len(ws) - 1} 중에서 고릅니다")
    start = first_day + wave * size
    return [(start + i, c) for i, c in enumerate(ws[wave][:limit])]


def items_for(days: list, db: dict, cats: list = None, menus: list = None, pool: list = None) -> list:
    """에이전트에게 줄 날마다의 입력 항목. cats, menus 는 days 와 같은 순서다."""
    by = {x["id"]: x for x in pool or []}
    out = []
    for i, (day, ch) in enumerate(days):
        verses, note = bible.resolve(db, ch["book"], ch["range"])
        it = {"day": day, "ref": ch["ref"], "book": ch["book"], "range": ch["range"], "section": ch["section"],
              "era": ch["era"], "density": ch["density"], "verses": verses}
        if note:
            it["note"] = note
        if cats:
            it["category"] = cats[i]
        if menus:
            it["menu"] = [{"id": s, "name": by[s]["name"], "words": by[s]["words"],
                           **({"theme": by[s]["theme"]} if by[s].get("theme") else {})} for s in menus[i]]
        out.append(it)
    return out


def check_commentary(c: dict, item: dict, pool_by_id: dict = None) -> list:
    """에이전트가 쓴 한 날의 해설을 점검한다. 문제 목록."""
    day = item["day"]
    out = []

    def bad(msg):
        out.append(f"{day}일: {msg}")
    if c.get("day") != day:
        return [f"{day}일: 해설의 day 가 {c.get('day')} 입니다"]
    title = c.get("title")
    if not isinstance(title, str) or not TITLE[0] <= len(title.strip()) <= TITLE[1] or "\n" in title:
        bad(f"title 은 한 줄 {TITLE[0]}~{TITLE[1]}자여야 합니다")
    themes = c.get("themes")
    if not (isinstance(themes, list) and 1 <= len(themes) <= 2 and len(set(themes)) == len(themes) and set(themes) <= set(THEME_IDS)):
        bad(f"themes 는 겹치지 않는 테마 id 1~2개여야 합니다({THEME_IDS})")
    fmt = c.get("format")
    blocks = c.get("blocks")
    if fmt not in FORMAT_LABELS:
        bad("format 은 1~5 중 하나여야 합니다")
        return out
    want = FORMAT_LABELS[fmt]
    if not (isinstance(blocks, list) and len(blocks) == len(want) and all(isinstance(b, dict) for b in blocks)):
        bad(f"형식 {fmt} 는 블록이 {len(want)}개({' / '.join(want)})여야 합니다")
        return out
    for b, w in zip(blocks, want):
        label, text = b.get("label"), b.get("text")
        if "{term}" in w:
            if not (isinstance(label, str) and TERM_LABEL.match(label)):
                bad(f"라벨은 '한 단어: 낱말'(낱말 1~10자)이어야 합니다('{label}')")
        elif label != w:
            bad(f"블록 라벨이 '{label}' 입니다('{w}' 여야 합니다)")
        if not isinstance(text, str) or not text.strip():
            bad(f"'{label}' 블록의 글이 비었습니다")
            continue
        base = "한 단어" if str(label).startswith("한 단어") else label
        lo, hi = LIMITS.get(base, DEFAULT_LIMITS)
        if not lo <= len(text) <= hi:
            bad(f"'{label}' 블록이 {len(text)}자입니다({lo}~{hi}자)")
        for rid, name, found, fix in tlint.check_block(text):
            bad(f"'{label}' 번역투 {rid}({name}): '{found}' → {fix}")
        for name, rx in FORBIDDEN:
            m = rx.search(text)
            if m:
                bad(f"'{label}' 에 쓰지 않는 표현이 있습니다: {name} '{m.group(0).strip()}'")
    parallels = c.get("parallels")
    if parallels is not None:
        ok = isinstance(parallels, list) and parallels and all(isinstance(p, str) for p in parallels)
        if ok:
            for p in parallels:
                try:
                    bible.book_of(p)
                except ValueError:
                    ok = False
        if not ok or item["ref"] in parallels:
            bad("parallels 는 다른 본문 참조 문자열의 목록이어야 합니다(없으면 키를 빼세요)")
    if item.get("menu"):
        menu = [m["id"] for m in item["menu"]]
        link = c.get("link")
        if not isinstance(link, str) or not LINK[0] <= len(link.strip()) <= LINK[1]:
            bad(f"link 는 {LINK[0]}~{LINK[1]}자여야 합니다")
        if pool_by_id is None:
            pool_by_id = {m["id"]: m for m in item["menu"]}
        if not (isinstance(blocks[-1].get("text"), str)):
            return out
        out += [f"{day}일: {p}" for p in assign.check_choice(menu, c.get("scene"), blocks[-1]["text"], pool_by_id)]
    return out


def assemble_day(item: dict, c: dict, db: dict, tokenize, freq: dict, T: float = None) -> dict:
    """점검을 통과한 해설로 plan 의 한 날을 만든다. 본문은 원본에서 다시 만들어 입력과 같은지 본다."""
    import make_lv
    verses, note = bible.resolve(db, item["book"], item["range"])
    if verses != item["verses"] or note != item.get("note"):
        raise ValueError(f"{item['day']}일: 입력의 본문이 원본과 다릅니다")
    ref = bible.ref_label(db, item["book"], verses)
    if ref != item["ref"]:
        raise ValueError(f"{item['day']}일: 참조 {ref} 가 입력의 {item['ref']} 와 다릅니다")
    era = routes.era_of(ref)
    if era != item["era"]:
        raise ValueError(f"{item['day']}일: 시기 {era} 가 입력의 {item['era']} 와 다릅니다")
    d = {"day": item["day"], "section": bible.section_of(item["book"]), "ref": ref, "title": c["title"].strip(), "era": era,
         "themes": list(c["themes"])}
    if note:
        d["note"] = note
    if c.get("parallels"):
        d["parallels"] = list(c["parallels"])
    d["verses"] = verses
    d["format"] = c["format"]
    d["blocks"] = [{"label": b["label"], "text": b["text"].strip()} for b in c["blocks"]]
    lv, _keywords = make_lv.build_day({"verses": verses, "title": d["title"]}, tokenize, freq, T or make_lv.IMPORTANCE)
    problems = make_lv.check_lv({"verses": verses}, lv)
    if problems:
        raise ValueError(f"{item['day']}일 lv: {problems[0]}")
    d["lv"] = lv
    return {k: d[k] for k in DAY_KEYS if k in d}


def ledger_entries(items: list, comments: list) -> dict:
    """새 날의 장부 추가분 {일차 문자열: {name, category, words, link}}. 고른 후보의 이름과 필수어, 그 날에 배정된 범주를 옮긴다."""
    out = {}
    for it, c in zip(items, comments):
        if not it.get("menu"):
            continue
        s = next(m for m in it["menu"] if m["id"] == c["scene"])
        out[str(it["day"])] = {"name": s["name"], "category": it["category"], "words": list(s["words"]), "link": c["link"].strip(),
                               **({"theme": s["theme"]} if s.get("theme") else {})}
    return out


def final_problems(new_days: list, plan: dict, ledger: dict = None, additions: dict = None, orders: dict = None,
                   baseline: set = None) -> list:
    """새 날을 기존 plan 과 합쳐 점검한다. 새 날이 일으키는 문제만 돌려준다.
    짜임 문제(앱이 못 읽는 날, 겹친 일차나 본문)가 있으면 오래 걸리는 말뭉치 점검은 하지 않고 먼저 돌려준다.
    baseline 은 기존 plan 의 말뭉치 문제 집합이다(여러 번 부를 때 한 번만 계산해 넘긴다)."""
    import kyeon
    out = [f"{d['day']}일: 앱의 day_ok 를 통과하지 못합니다" for d in new_days if not kyeon.day_ok(d)]
    have = {d["day"] for d in plan["days"]}
    nums = [d["day"] for d in new_days]
    out += [f"{n}일이 이미 있거나 겹칩니다" for n in nums if n in have or nums.count(n) > 1]
    refs = {d["ref"] for d in plan["days"]}
    out += [f"{d['day']}일의 본문 {d['ref']} 가 이미 다른 날에 있습니다" for d in new_days if d["ref"] in refs]
    if bible.covered({"days": new_days}) & bible.covered(plan):
        out.append("기존 날과 같은 절이 들어 있습니다")
    if out:
        return out
    plus = {**plan, "days": plan["days"] + new_days}
    before = baseline if baseline is not None else set(dupcheck.corpus_problems(plan))
    out += [p for p in dupcheck.corpus_problems(plus) if p not in before]
    if ledger is not None and additions:
        merged = {**ledger, "scenes": {**ledger["scenes"], **additions}}
        texts = {d: t for d, _l, t in dupcheck.blocks_of(plus, "오늘")}
        out += dupcheck.ledger_shape_problems({"scenes": additions}, texts)
        # 새 날끼리만 본다. 기존 장부의 필수어는 새 글에서 막지 않는다(기존 글에서 고른 낱말이라 세례, 형상 같은 성경 낱말이 섞여 있다.
        # 기존 장면과 겹치는 것은 후보의 필수어가 기존 글 어디에도 없다는 점검과 이름 비교가 막는다)
        out += dupcheck.scene_problems({"scenes": additions}, {d["day"]: texts[d["day"]] for d in new_days if d["day"] in texts})
        order = [d["day"] for d in new_days]
        out += dupcheck.window_problems({"scenes": additions}, order, share=1.0)
        before = set(themes.window_problems(ledger["scenes"]))      # 이웃한 해와의 경계까지 본다
        out += [p for p in themes.window_problems(merged["scenes"]) if p not in before]
        if orders is not None:
            base = len(dupcheck.route_problems(ledger, orders["old"]))
            now = len(dupcheck.route_problems(merged, orders["new"]))
            if now > base:
                out.append(f"길 순서 위반이 {base}개에서 {now}개로 늘었습니다")
    return out


def write_days(path: Path, days: list) -> None:
    """plan.json 과 같은 한 날 한 줄 형식으로 쓴다."""
    lines = [routes._dump(d) for d in days]
    path.write_text('{"days": [\n' + ",\n".join(lines) + "\n]}\n", encoding="utf-8", newline="\n")


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _chunk_files(directory: Path, prefix: str) -> list:
    return sorted(directory.glob(f"{prefix}_*.json"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", default=str(ROOT / "data" / "plan.json"))
    ap.add_argument("--skeleton", default=str(ROOT / "build" / "skeleton.json"))
    ap.add_argument("--bible", default=str(bible.DEFAULT_SOURCE))
    ap.add_argument("--ledger", default=str(ROOT / "ledger" / "scenes.json"))
    ap.add_argument("--strategy", default="spread")
    ap.add_argument("--wave", type=int, default=0)
    ap.add_argument("--size", type=int, default=365)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--skip", type=int, default=0, help="--prepare: 해의 앞 N일은 이미 썼으니 건너뛴다")
    ap.add_argument("--per-agent", type=int, default=30)
    ap.add_argument("--show", type=int, default=40, help="--assemble: 보여 줄 문제의 최대 개수")
    ap.add_argument("--cats")
    ap.add_argument("--menus")
    ap.add_argument("--pool")
    ap.add_argument("--prepare")
    ap.add_argument("--check")
    ap.add_argument("--assemble")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    if a.prepare:
        out_dir = Path(a.prepare)
        out_dir.mkdir(parents=True, exist_ok=True)
        days = day_numbers(_read(a.skeleton)["chunks"], a.strategy, a.wave, a.size, a.limit)
        cats = _read(a.cats)[:len(days)] if a.cats else None        # cats, menus 는 그 해의 첫 날부터 맞춘 목록이고 --skip 이 days 와 함께 자른다
        menus = _read(a.menus)[:len(days)] if a.menus else None
        days = days[a.skip:]
        cats = cats[a.skip:] if cats else None
        menus = menus[a.skip:] if menus else None
        pool = _read(a.pool) if a.pool else None
        items = items_for(days, bible.load_db(a.bible), cats, menus, pool)
        for n, i in enumerate(range(0, len(items), a.per_agent), 1):
            (out_dir / f"items_{n:02d}.json").write_text(json.dumps(items[i:i + a.per_agent], ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{len(items)}일({items[0]['day']}~{items[-1]['day']}일)을 조각 {n}개로 나눠 {out_dir} 에 썼습니다")
        return 0
    if a.check or a.assemble:
        directory = Path(a.check or a.assemble)
        problems, pairs = [], []
        for f in _chunk_files(directory, "items"):
            cf = directory / f.name.replace("items_", "commentary_")
            items = _read(f)
            if not cf.is_file():
                problems.append(f"{cf.name} 이 없습니다")
                continue
            comments = _read(cf)
            if [c.get("day") for c in comments] != [i["day"] for i in items]:
                problems.append(f"{cf.name}: 일차 순서와 개수가 입력과 다릅니다")
                continue
            for it, c in zip(items, comments):
                problems += check_commentary(c, it)       # 같은 날 메뉴의 다른 후보만 막는다. 다른 날과의 겹침은 조립에서 고른 장면끼리 본다
            pairs += list(zip(items, comments))
        if problems:
            print("\n".join(problems[:40]), f"\n… 문제 {len(problems)}개" if len(problems) > 40 else "")
            return 1
        print(f"해설 점검: 통과 ({len(pairs)}일)")
        if a.check:
            return 0
        import make_lv
        tokenize, many = make_lv.kiwi_tokenizer()
        db = bible.load_db(a.bible)
        freq = make_lv.load_frequency(db, many)
        days = [assemble_day(it, c, db, tokenize, freq) for it, c in pairs]
        plan = planio.read_plan(a.plan)
        ledger = _read(a.ledger) if Path(a.ledger).is_file() else None
        additions = ledger_entries([p[0] for p in pairs], [p[1] for p in pairs])
        import ledger as ledger_tool
        plus = {**plan, "days": plan["days"] + days}
        orders = {"old": ledger_tool.route_orders(plan), "new": ledger_tool.route_orders(plus)} if ledger and additions else None
        final = final_problems(days, plan, ledger, additions, orders)
        if final:
            print("\n".join(final[:a.show]), f"\n… 문제 {len(final)}개" if len(final) > a.show else "")
            return 1
        out = Path(a.out or directory / "wave_days.json")
        write_days(out, days)
        if additions:
            (out.parent / (out.stem + "_ledger.json")).write_text(json.dumps(additions, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{out} 에 {len(days)}일을 썼습니다(장부 추가 {len(additions)}개)")
        return 0
    ap.error("--prepare, --check, --assemble 중 하나가 필요합니다")


if __name__ == "__main__":
    sys.exit(main())
