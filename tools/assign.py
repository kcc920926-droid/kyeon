"""새 날의 장면을 겹칠 수 없게 배정한다. 쓰는 쪽(에이전트)은 배정된 메뉴 안에서만 고른다.

  python tools/assign.py --categories N --ledger L --out cats.json        새 N일의 범주를 정한다(합쳐서 범주 비중이 고르게, 창 규칙을 지키게)
  python tools/assign.py --check-pool POOL [--plan P] [--ledger L]        장면 후보 풀의 짜임과 필수어의 배타성을 점검한다
  python tools/assign.py --menus POOL --cats cats.json --out menus.json   날마다 서로 겹치지 않는 후보 K개(기본 4)를 메뉴로 준다

흐름
  1. plan_categories: 기존 장부의 범주 분포를 보고 새 날마다 범주를 정한다. 어느 7일, 30일 창에서도 같은 범주가 상한을 넘지 않게 한다.
  2. 풀(POOL): 범주마다 장면 후보를 에이전트가 만든다. 후보는 {id, name, category, words}. 필수어는 다른 후보와 기존 오늘 단락 어디에도 없어야 한다.
  3. build_menus: 날마다 배정된 범주의 후보 K개를 준다. **메뉴는 날마다 서로 겹치지 않으므로** 어느 것을 골라도 다른 날과 같은 장면이 될 수 없다.
  4. 에이전트는 메뉴에서 본문에 가장 어울리는 장면을 하나 골라 쓰고, 어울리는 것이 없으면 '교체 요청'을 남긴다.
  5. check_choice: 고른 장면이 그 날의 메뉴에 있는지, 필수어가 첫 두 문장에 있는지, 풀의 다른 후보 낱말이 섞이지 않았는지 본다.
같은 입력이면 항상 같은 결과다.
"""
import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dupcheck  # noqa: E402
import planio  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CATEGORIES = dupcheck.CATEGORIES
MENU_SIZE = 4


def plan_categories(n: int, old_counts: dict, old_total: int = None, windows=dupcheck.WINDOWS,
                    share_cap: float = dupcheck.CATEGORY_SHARE, offset: int = 0) -> list:
    """새 n일의 범주를 정한다. old_counts: {범주: 기존 장면 수}. 기존과 합쳐 범주 비중이 고르고, 창 규칙을 지키게 한다."""
    old_total = old_total if old_total is not None else sum(old_counts.values())
    total = old_total + n
    ideal = total / len(CATEGORIES)
    cap = max(0, math.floor(share_cap * total))
    want = {c: max(0.0, min(ideal - old_counts.get(c, 0), cap - old_counts.get(c, 0))) for c in CATEGORIES}
    if sum(want.values()) <= 0:
        raise ValueError("새 날에 쓸 수 있는 범주 몫이 없습니다")
    scale = n / sum(want.values())
    quota = {c: want[c] * scale for c in CATEGORIES}              # 새 n일에서 범주마다 받을 몫(실수)
    # 정수 몫: 내림 뒤 남는 자리는 소수 부분이 큰 순서로
    base = {c: int(quota[c]) for c in CATEGORIES}
    rest = n - sum(base.values())
    for c in sorted(CATEGORIES, key=lambda c: (-(quota[c] - base[c]), CATEGORIES.index(c)))[:rest]:
        base[c] += 1
    remaining = dict(base)
    out = []
    for i in range(n):
        history = out[-max(w for w, _ in windows):]

        def feasible(c):
            for size, limit in windows:
                if history[-(size - 1):].count(c) >= limit:    # 이번에 더하면 창 안에서 limit+1 번이 된다
                    return False
            return True
        order = sorted((c for c in CATEGORIES if remaining[c] > 0),
                       key=lambda c: (-(remaining[c] / max(1, base[c])), (CATEGORIES.index(c) - i - offset) % len(CATEGORIES)))
        pick = next((c for c in order if feasible(c) and (not out or c != out[-1])), None) \
            or next((c for c in order if feasible(c)), None) or (order[0] if order else None)
        if pick is None:
            raise ValueError("범주를 더 정할 수 없습니다")
        out.append(pick)
        remaining[pick] -= 1
    return out


def pool_problems(pool: list, existing_texts: dict = None, existing_words: set = None, existing_names: dict = None,
                  name_limit: float = dupcheck.NAME_SIMILAR) -> list:
    """장면 후보 풀의 문제 목록: 짜임, 필수어의 배타성(다른 후보와 기존 오늘 단락), 이름이 비슷한 장면(후보끼리, 기존 장부와)."""
    out, ids, owner, names = [], set(), {}, {}
    for x in pool:
        xid = x.get("id")
        if not xid or xid in ids:
            out.append(f"후보 id '{xid}' 가 비었거나 겹칩니다")
        ids.add(xid)
        if x.get("category") not in CATEGORIES:
            out.append(f"{xid}: 범주 '{x.get('category')}' 는 목록에 없습니다")
        nm = re.sub(r"\s+", "", x.get("name", ""))
        if not 4 <= len(nm) <= 40:
            out.append(f"{xid}: 이름은 4~40자여야 합니다")
        if nm in names:
            out.append(f"{xid}: 이름이 {names[nm]} 와 같습니다")
        names.setdefault(nm, xid)
        ws = x.get("words") or []
        if not 2 <= len(ws) <= 3:
            out.append(f"{xid}: 필수어는 2~3개여야 합니다")
        for w in ws:
            if len(w) < 2 or not re.fullmatch(r"[가-힣]+", w):
                out.append(f"{xid}: 필수어 '{w}' 는 두 글자 이상의 한글이어야 합니다")
            elif w in owner and owner[w] != xid:
                out.append(f"필수어 '{w}' 가 {owner[w]} 와 {xid} 에 같이 있습니다")
            owner.setdefault(w, xid)
    if existing_texts:
        for w, xid in owner.items():
            hits = [d for d, t in existing_texts.items() if w in t]
            if hits:
                out.append(f"{xid}: 필수어 '{w}' 가 기존 오늘 단락 {len(hits)}곳({', '.join(map(str, hits[:4]))})에 이미 있습니다")
    if existing_words:
        for w, xid in owner.items():
            if w in existing_words:
                out.append(f"{xid}: 필수어 '{w}' 는 기존 장부의 필수어입니다")
    named = {x["id"]: x["name"] for x in pool if x.get("id") and x.get("name")}
    for j, a, b in dupcheck.similar_names(named, min_jaccard=name_limit):
        out.append(f"{a} '{named[a]}' 와 {b} '{named[b]}' 는 이름이 비슷합니다({j:.2f})")
    if existing_names:
        for j, a, b in dupcheck.similar_names(named, existing_names, min_jaccard=name_limit):
            out.append(f"{a} '{named[a]}' 는 기존 {b}일의 장면 '{existing_names[b]}' 와 이름이 비슷합니다({j:.2f})")
    return out


def build_menus(pool: list, categories: list, k: int = MENU_SIZE) -> list:
    """날마다 배정된 범주의 후보 k개를 준다. 메뉴는 날마다 서로 겹치지 않는다. -> [[후보 id, ...], ...] (날 순서)"""
    queues = defaultdict(list)
    for x in pool:
        queues[x["category"]].append(x["id"])
    need = Counter(categories)
    for c, n in need.items():
        if len(queues[c]) < n * k:
            raise ValueError(f"범주 '{c}' 후보가 {len(queues[c])}개뿐입니다(필요 {n * k}개: {n}일 × {k})")
    cursor = Counter()
    out = []
    for c in categories:
        i = cursor[c]
        out.append(queues[c][i:i + k])
        cursor[c] += k
    return out


def check_choice(menu: list, choice: str, text: str, pool_by_id: dict) -> list:
    """에이전트가 고른 장면(choice 는 후보 id)이 메뉴에 있고, 글이 그 필수어를 쓰며, 풀의 다른 후보 낱말을 섞지 않았는지 본다."""
    if choice not in menu:
        return [f"고른 장면 '{choice}' 는 이 날의 메뉴({', '.join(menu)})에 없습니다"]
    mine = pool_by_id[choice]
    out = []
    head = " ".join(dupcheck.sentences(text)[:2])
    need = max(1, math.ceil(len(mine["words"]) / 2))
    got = [w for w in mine["words"] if w in head]
    if len(got) < need:
        out.append(f"장면 '{mine['name']}' 의 필수어({', '.join(mine['words'])})가 첫 두 문장에 {len(got)}개뿐입니다(필요 {need}개)")
    for xid, x in pool_by_id.items():
        if xid != choice and any(w in text for w in x["words"]):
            out.append(f"다른 후보 {xid} 의 필수어({', '.join(w for w in x['words'] if w in text)})가 섞였습니다")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", default=str(ROOT / "data" / "plan.json"))
    ap.add_argument("--ledger", default=str(ROOT / "ledger" / "scenes.json"))
    ap.add_argument("--categories", type=int)
    ap.add_argument("--check-pool")
    ap.add_argument("--menus")
    ap.add_argument("--cats")
    ap.add_argument("--k", type=int, default=MENU_SIZE)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    if a.categories:
        ledger = json.loads(Path(a.ledger).read_text(encoding="utf-8"))
        old = Counter(s["category"] for s in ledger["scenes"].values())
        cats = plan_categories(a.categories, dict(old), len(ledger["scenes"]))
        problems = dupcheck.window_problems({"scenes": {str(i): {"category": c} for i, c in enumerate(cats)}}, list(range(len(cats))), share=1.0)
        if a.out:
            Path(a.out).write_text(json.dumps(cats, ensure_ascii=False), encoding="utf-8")
        total = Counter(old) + Counter(cats)
        n = sum(total.values())
        print("새 범주 몫:", dict(Counter(cats)), "\n합친 비중 최대:", f"{max(total.values()) * 100 / n:.1f}%", "최소:", f"{min(total.values()) * 100 / n:.1f}%",
              "\n창 규칙 위반:", len(problems))
        return 1 if problems else 0
    if a.check_pool:
        pool = json.loads(Path(a.check_pool).read_text(encoding="utf-8"))
        plan = planio.read_plan(a.plan)
        texts = {d: t for d, l, t in dupcheck.blocks_of(plan, "오늘")}
        words, names = set(), {}
        if Path(a.ledger).is_file():
            scenes = json.loads(Path(a.ledger).read_text(encoding="utf-8"))["scenes"]
            words = {w for s in scenes.values() for w in s.get("words", [])}
            names = {d: s["name"] for d, s in scenes.items()}
        errs = pool_problems(pool, texts, words, names)
        print("\n".join(errs[:30]) if errs else f"풀 점검: 통과 ({len(pool)}개)", Counter(x["category"] for x in pool) if not errs else "")
        return 1 if errs else 0
    if a.menus and a.cats:
        pool = json.loads(Path(a.menus).read_text(encoding="utf-8"))
        cats = json.loads(Path(a.cats).read_text(encoding="utf-8"))
        menus = build_menus(pool, cats, a.k)
        if a.out:
            Path(a.out).write_text(json.dumps(menus, ensure_ascii=False), encoding="utf-8")
        print(f"{len(menus)}일의 메뉴를 만들었습니다(날마다 {a.k}개, 서로 겹치지 않음)")
        return 0
    ap.error("--categories, --check-pool, --menus 와 --cats 중 하나가 필요합니다")


if __name__ == "__main__":
    sys.exit(main())
