"""남은 절을 하루치 덩어리로 나눈 골격(skeleton)을 만든다. LLM 이 어느 본문을 쓸지 고르지 않게, 코드가 빠짐없이 나눈다.

  python tools/skeleton.py --out build/skeleton.json              남은 절을 --total 일(기본 2650)로 나눈다
  python tools/skeleton.py --check build/skeleton.json            절 누락, 겹침, 크기를 점검한다
  python tools/skeleton.py --summary build/skeleton.json          갈래와 크기 분포를 보여 준다
  python tools/skeleton.py --dump-runs build/runs.json            끊을 자리를 제안받을 때 줄 입력(덩어리마다 본문과 기본 끊는 자리)
  python tools/skeleton.py --out ... --cuts build/cuts.json       제안받은 끊는 자리를 쓴다(점검을 통과한 것만)

방법
  1. data/plan.json 이 이미 담은 절을 뺀 나머지를, 책 안에서 이어진 덩어리(run)로 모은다. [없음] 절은 건너뛴다.
  2. 족보, 성막 규격, 제사 규정, 성전 환상처럼 낱말이 되풀이되는 본문(LOW_DENSITY)은 절 하나를 0.6절로 쳐서 더 크게 묶는다.
  3. 덩어리마다 며칠을 줄지 정한다. 합이 정확히 total 이 되게, 하루치의 평균 크기가 고르도록 가장 큰 쪽부터 쪼갠다.
  4. 덩어리 안에서는 하루치 크기가 고르게 되도록 동적 계획법으로 끊는다. 장이 끝나는 자리를 좋아한다.
  5. cuts 파일이 있으면 그 덩어리는 제안대로 끊는다. 크기 범위를 어기면 받지 않는다.
같은 입력이면 항상 같은 결과가 나온다(무작위 없음).
"""
import argparse
import hashlib
import heapq
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bible  # noqa: E402
import planio  # noqa: E402
import routes  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MIN_SIZE = 4            # 하루치 최소 절 수(덩어리 자체가 이보다 작으면 그 덩어리 하나가 하루치)
MAX_NORMAL = 18         # 하루치 최대 절 수
MAX_LOW = 25            # 저밀도 본문이 절반 넘게 든 하루치의 최대 절 수
LOW_WEIGHT = 0.6        # 저밀도 절 하나가 차지하는 몫
CHAPTER_BONUS = 0.12    # 장이 끝나는 자리에서 끊을 때 깎아 주는 비용

# 저밀도 본문: (책, 시작 장, 끝 장). 족보, 명단, 규격, 규정처럼 낱말과 틀이 되풀이되는 곳이다.
LOW_DENSITY = [
    ("창세기", 5, 5), ("창세기", 10, 10), ("창세기", 36, 36),
    ("출애굽기", 25, 31), ("출애굽기", 35, 40),
    ("레위기", 1, 7), ("레위기", 11, 15), ("레위기", 27, 27),
    ("민수기", 1, 4), ("민수기", 7, 7), ("민수기", 26, 26), ("민수기", 31, 36),
    ("여호수아", 13, 21),
    ("역대상", 1, 9), ("역대상", 23, 26),
    ("에스라", 2, 2), ("에스라", 8, 8),
    ("느헤미야", 3, 3), ("느헤미야", 7, 7), ("느헤미야", 11, 12),
    ("에스겔", 40, 48),
]


def is_low(book: str, chapter: int) -> bool:
    return any(b == book and c1 <= chapter <= c2 for b, c1, c2 in LOW_DENSITY)


def runs_of(db: dict, covered: set) -> list:
    """남은 절을 책 안에서 이어진 덩어리로 모은다. -> [{id, book, verses: [(장, 절)]}]"""
    out = []
    for book in (b for b in bible.BOOKS if b in db):
        cur = []
        for c in sorted(db[book]):
            for v in sorted(db[book][c]):
                if bible.is_absent(db[book][c][v]):
                    continue
                if (book, c, v) in covered:
                    if cur:
                        out.append(cur)
                        cur = []
                else:
                    cur.append((book, c, v))
        if cur:
            out.append(cur)
    return [{"id": f"{r[0][0]}:{r[0][1]}:{r[0][2]}", "book": r[0][0], "verses": [(c, v) for _b, c, v in r]} for r in out]


def _prefix(run):
    eff, low = [0.0], [0]
    for c, _v in run["verses"]:
        lw = is_low(run["book"], c)
        eff.append(eff[-1] + (LOW_WEIGHT if lw else 1.0))
        low.append(low[-1] + lw)
    return eff, low


def _bounds(run, eff, low):
    n = len(run["verses"])
    if n < MIN_SIZE:
        return 1, 1
    mx = MAX_LOW if low[-1] * 2 >= n else MAX_NORMAL if low[-1] == 0 else MAX_LOW
    return math.ceil(n / mx), n // MIN_SIZE


def partition(run, eff, low, k):
    """run 을 k 개로 끊는다. -> 끝 위치 목록(마지막은 n). 가능한 끊음이 없으면 None."""
    n = len(run["verses"])
    s = eff[-1] / k
    minlen = min(MIN_SIZE, n // k)
    ends_chapter = [i + 1 == n or run["verses"][i + 1][0] != run["verses"][i][0] for i in range(n)]
    INF = float("inf")
    dp = [[INF] * (n + 1) for _ in range(k + 1)]
    back = [[-1] * (n + 1) for _ in range(k + 1)]
    dp[0][0] = 0.0
    for j in range(1, k + 1):
        for b in range(j, n + 1):
            best, arg = INF, -1
            for a in range(max(j - 1, b - MAX_LOW), b - minlen + 1):
                if dp[j - 1][a] == INF:
                    continue
                length = b - a
                mx = MAX_LOW if (low[b] - low[a]) * 2 >= length else MAX_NORMAL
                if length > mx:
                    continue
                cost = dp[j - 1][a] + ((eff[b] - eff[a] - s) / s) ** 2
                if b < n and ends_chapter[b - 1]:
                    cost -= CHAPTER_BONUS
                if cost < best:
                    best, arg = cost, a
            dp[j][b], back[j][b] = best, arg
    if dp[k][n] == INF:
        return None
    ends, b = [], n
    for j in range(k, 0, -1):
        ends.append(b)
        b = back[j][b]
    return ends[::-1]


def check_cuts(run, starts: list, eff, low):
    """제안받은 끊는 자리(각 하루치가 시작하는 'c:v')를 점검한다. -> (끝 위치 목록, 문제 목록)"""
    pos = {f"{c}:{v}": i for i, (c, v) in enumerate(run["verses"])}
    n = len(run["verses"])
    idx = []
    for s in starts:
        if s not in pos or pos[s] == 0:
            return None, [f"{run['id']}: 끊는 자리 {s} 가 덩어리 안에 없거나 맨 앞입니다"]
        idx.append(pos[s])
    if idx != sorted(set(idx)):
        return None, [f"{run['id']}: 끊는 자리가 순서대로 하나씩이어야 합니다"]
    ends = idx + [n]
    problems, a = [], 0
    for b in ends:
        length = b - a
        mx = MAX_LOW if (low[b] - low[a]) * 2 >= length else MAX_NORMAL
        floor = min(MIN_SIZE, n // len(ends))
        if length > mx or length < floor:
            problems.append(f"{run['id']}: {run['verses'][a][0]}:{run['verses'][a][1]} 부터 {length}절은 범위({floor}~{mx}절)를 벗어납니다")
        a = b
    return (None if problems else ends), problems


def build(db: dict, covered: set, total: int = 2650, cuts: dict = None) -> list:
    cuts = cuts or {}
    runs = runs_of(db, covered)
    pre = [_prefix(r) for r in runs]
    lo, hi, fixed = [], [], {}
    for i, (r, (eff, low)) in enumerate(zip(runs, pre)):
        l, h = _bounds(r, eff, low)
        if r["id"] in cuts:
            ends, problems = check_cuts(r, cuts[r["id"]], eff, low)
            if problems:
                raise ValueError("\n".join(problems))
            fixed[i] = ends
            l = h = len(ends)
        lo.append(l)
        hi.append(h)
    if not sum(lo) <= total <= sum(hi):
        raise ValueError(f"{total}일로는 나눌 수 없습니다. 가능한 범위는 {sum(lo)}~{sum(hi)}일입니다")
    while True:
        if sum(lo) > total:
            raise ValueError(f"크기 범위를 지키려면 {sum(lo)}일이 필요해서 {total}일로는 나눌 수 없습니다")
        k = lo[:]
        heap = [(-pre[i][0][-1] / k[i], i) for i in range(len(runs)) if k[i] < hi[i]]
        heapq.heapify(heap)
        for _ in range(total - sum(k)):
            _neg, i = heapq.heappop(heap)
            k[i] += 1
            if k[i] < hi[i]:
                heapq.heappush(heap, (-pre[i][0][-1] / k[i], i))
        ends_of, retry = {}, False
        for i, r in enumerate(runs):
            ends = fixed.get(i) or partition(r, pre[i][0], pre[i][1], k[i])
            if ends is None:     # 이 개수로는 크기 범위를 지킬 수 없다. 하나 더 쪼개서 다시 푼다
                if k[i] + 1 > hi[i]:
                    raise ValueError(f"{r['id']} 를 크기 범위 안에서 나눌 수 없습니다")
                lo[i] = k[i] + 1
                retry = True
                break
            ends_of[i] = ends
        if not retry:
            break
    chunks = []
    for i, r in enumerate(runs):
        a = 0
        for b in ends_of[i]:
            (c1, v1), (c2, v2) = r["verses"][a], r["verses"][b - 1]
            rng = f"{c1}:{v1}-{v2}" if c1 == c2 else f"{c1}:{v1}-{c2}:{v2}"
            verses, _note = bible.resolve(db, r["book"], rng)
            ref = bible.ref_label(db, r["book"], verses)
            lows = sum(is_low(r["book"], c) for c, _v in r["verses"][a:b])
            chunks.append({
                "id": f"{r['book']}:{c1}:{v1}", "book": r["book"], "range": rng, "ref": ref, "n": len(verses),
                "section": bible.section_of(r["book"]), "stream": bible.stream_of(r["book"]), "era": routes.era_of(ref),
                "density": "low" if lows * 2 >= (b - a) else "normal", "short": (b - a) < MIN_SIZE,
            })
            a = b
    return chunks


def problems_of(chunks: list, db: dict, covered: set, total: int = None) -> list:
    """골격의 문제 목록(비어 있으면 통과): 절 누락, 겹침, 이미 담은 절, 크기, 개수"""
    out = []
    if total is not None and len(chunks) != total:
        out.append(f"하루치가 {len(chunks)}개입니다(기대 {total}개)")
    seen = Counter()
    for ch in chunks:
        try:
            verses, _note = bible.resolve(db, ch["book"], ch["range"])
        except (KeyError, ValueError) as e:
            out.append(f"{ch['id']}: 범위를 풀 수 없습니다 ({e})")
            continue
        if len(verses) != ch["n"]:
            out.append(f"{ch['id']}: n 이 {ch['n']} 인데 실제 {len(verses)}절")
        mx = MAX_LOW if ch["density"] == "low" else MAX_NORMAL
        if ch["n"] > mx:
            out.append(f"{ch['id']}: {ch['n']}절은 {ch['density']} 의 최대 {mx}절을 넘습니다")
        for c, v, _t in verses:
            seen[(ch["book"], c, v)] += 1
            if (ch["book"], c, v) in covered:
                out.append(f"{ch['book']} {c}:{v} 은 이미 plan.json 에 있습니다")
    out += [f"{b} {c}:{v} 이 {n}번 들어 있습니다" for (b, c, v), n in seen.items() if n > 1]
    for book in (b for b in bible.BOOKS if b in db):
        for c in db[book]:
            for v, t in db[book][c].items():
                if not bible.is_absent(t) and (book, c, v) not in covered and (book, c, v) not in seen:
                    out.append(f"{book} {c}:{v} 이 빠졌습니다")
    return out


def summary(chunks: list) -> str:
    sizes = [c["n"] for c in chunks]
    lines = [f"하루치 {len(chunks)}개, 절 {sum(sizes)}개, 평균 {sum(sizes) / len(sizes):.2f}절, 최소 {min(sizes)}, 최대 {max(sizes)}",
             f"1~3절짜리 {sum(c['short'] for c in chunks)}개, 저밀도 {sum(c['density'] == 'low' for c in chunks)}개"]
    bins = Counter(("1-3" if n <= 3 else "4-6" if n <= 6 else "7-9" if n <= 9 else "10-12" if n <= 12 else "13-18" if n <= 18 else "19-25") for n in sizes)
    lines.append("크기 분포: " + ", ".join(f"{k}절 {bins[k]}" for k in ("1-3", "4-6", "7-9", "10-12", "13-18", "19-25")))
    by = defaultdict(lambda: [0, 0])
    for c in chunks:
        by[c["section"]][0] += 1
        by[c["section"]][1] += c["n"]
    for sec, (d, v) in by.items():
        lines.append(f"  {sec}: {d}일, {v}절")
    return "\n".join(lines)


def source_fingerprint(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bible", default=str(bible.DEFAULT_SOURCE))
    ap.add_argument("--plan", default=str(ROOT / "data" / "plan.json"))
    ap.add_argument("--total", type=int, default=2650)
    ap.add_argument("--out")
    ap.add_argument("--cuts")
    ap.add_argument("--check")
    ap.add_argument("--summary")
    ap.add_argument("--dump-runs")
    a = ap.parse_args(argv)
    db = bible.load_db(a.bible)
    plan = planio.read_plan(a.plan)
    covered = bible.covered(plan)
    if a.dump_runs:
        runs = runs_of(db, covered)
        data = []
        for r in runs:
            eff, low = _prefix(r)
            lo, hi = _bounds(r, eff, low)
            data.append({"id": r["id"], "book": r["book"], "verses": [[c, v, bible.normalize(db[r["book"]][c][v])] for c, v in r["verses"]],
                         "min_days": lo, "max_days": hi})
        Path(a.dump_runs).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        print(f"{a.dump_runs} 에 덩어리 {len(data)}개를 썼습니다")
        return 0
    if a.check or a.summary:
        doc = json.loads(Path(a.check or a.summary).read_text(encoding="utf-8"))
        if a.summary:
            print(summary(doc["chunks"]))
            return 0
        errs = problems_of(doc["chunks"], db, covered, doc["meta"]["total"])
        print("\n".join(errs[:30]) if errs else f"골격 점검: 통과 ({len(doc['chunks'])}일)")
        return 1 if errs else 0
    if not a.out:
        ap.error("--out 이 필요합니다")
    cuts = json.loads(Path(a.cuts).read_text(encoding="utf-8")) if a.cuts else None
    chunks = build(db, covered, a.total, cuts)
    meta = {"total": a.total, "min_size": MIN_SIZE, "max_normal": MAX_NORMAL, "max_low": MAX_LOW, "low_weight": LOW_WEIGHT,
            "bible": source_fingerprint(a.bible), "covered_verses": len(covered), "cuts": bool(cuts)}
    Path(a.out).write_text(json.dumps({"meta": meta, "chunks": chunks}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(summary(chunks))
    errs = problems_of(chunks, db, covered, a.total)
    print("점검:", "통과" if not errs else f"문제 {len(errs)}개\n" + "\n".join(errs[:10]))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
