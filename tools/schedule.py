"""골격(skeleton)의 하루치들을 읽는 순서와 '해(파도)'로 나눈다. 어느 365일을 먼저 쓸지가 여기서 정해진다.

  python tools/schedule.py --compare                      네 전략으로 첫 해를 나눠 보고 모양을 비교한다
  python tools/schedule.py --strategy sweep --wave 1 --out build/wave1.json     첫 해의 하루치를 읽는 순서대로 쓴다

전략
  canon  성경 순서대로. 첫 해는 창세기 앞쪽 몇 달로 채워진다.
  mix    갈래(율법, 역사, 지혜, 선지, 복음, 행전, 서신, 계시)를 크기에 비례해 섞는다. 갈래 안에서는 성경 순서를 지킨다.
         해마다 갈래마다 '다음 부분'이 나온다. 이야기가 이어져 읽히지만, 첫 해는 각 갈래의 앞부분에 몰린다.
  spread 해마다 모든 책의 '다음 몫'을 읽는다. 책마다 안에서의 상대 위치((j+0.5)/책의 하루치 수)로 줄을 세워 365일씩 끊는다.
         첫 해는 거의 모든 책의 앞 7분의 1이고, 책 안의 이야기는 성경 순서로 이어진다. 책을 가리지 않으면서 이야기도 이어진다.
  sweep  첫 해부터 성경 전체를 성기게 훑는다. 황금비 수열로 해마다 골고루 뽑아서 해마다 촘촘해진다.
         한 해 안의 읽는 순서는 mix 와 같다. 이야기는 토막토막 나오고, 마지막 해에 가야 빈틈이 다 메워진다.
네 전략 모두 같은 입력이면 같은 결과다. 기존 1000일 뒤(1001일차부터)에 이어 붙이는 것을 전제로 한다.
"""
import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bible  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STREAMS = ["율법", "역사", "지혜", "선지", "복음", "행전", "서신", "계시"]
PHI = (math.sqrt(5) - 1) / 2


def canon_order(chunks: list) -> list:
    return sorted(chunks, key=lambda c: (bible.BOOK_INDEX[c["book"]], tuple(int(x) for x in c["id"].split(":")[1:])))


def mix_order(chunks: list) -> list:
    """갈래마다 [0,1] 구간에 고르게 흩뿌린 시각을 주고 시각 순으로 줄 세운다. 갈래 안의 순서는 성경 순서다."""
    by = {}
    for c in canon_order(chunks):
        by.setdefault(c["stream"], []).append(c)
    keyed = []
    for stream, items in by.items():
        for j, c in enumerate(items):
            keyed.append(((j + 0.5) / len(items), STREAMS.index(stream) if stream in STREAMS else 99, c))
    keyed.sort(key=lambda x: (x[0], x[1]))
    return [c for _t, _s, c in keyed]


def waves(chunks: list, strategy: str, size: int = 365) -> list:
    """해마다 읽는 순서대로 정리한 하루치 목록의 목록"""
    if strategy == "canon":
        order = canon_order(chunks)
        return [order[i:i + size] for i in range(0, len(order), size)]
    if strategy == "mix":
        order = mix_order(chunks)
        return [order[i:i + size] for i in range(0, len(order), size)]
    if strategy == "spread":
        canon = canon_order(chunks)
        counts = Counter(c["book"] for c in canon)
        seen = Counter()
        rel = []
        for c in canon:
            rel.append(((seen[c["book"]] + 0.5) / counts[c["book"]], bible.BOOK_INDEX[c["book"]], c))
            seen[c["book"]] += 1
        rel.sort(key=lambda x: (x[0], x[1]))
        ranked = [c for _r, _b, c in rel]
        return [mix_order(ranked[k:k + size]) for k in range(0, len(ranked), size)]
    if strategy == "sweep":
        canon = canon_order(chunks)
        ranked = sorted(range(len(canon)), key=lambda i: ((i * PHI) % 1.0, i))
        return [mix_order([canon[i] for i in ranked[k:k + size]]) for k in range(0, len(ranked), size)]
    raise ValueError(f"알 수 없는 전략: {strategy}")


def report(wave: list, everything: list) -> dict:
    """한 해의 모양: 닿는 책 수, 갈래 구성, 같은 책이 연속으로 나오는 길이, 이야기가 이어지는 정도"""
    books = Counter(c["book"] for c in wave)
    streak = best = 1
    for a, b in zip(wave, wave[1:]):
        streak = streak + 1 if a["book"] == b["book"] else 1
        best = max(best, streak)
    canon = {c["id"]: i for i, c in enumerate(canon_order(everything))}
    by_book = {}
    for c in wave:
        by_book.setdefault(c["book"], []).append(canon[c["id"]])
    pairs = adjacent = 0
    for ids in by_book.values():
        ids.sort()
        for a, b in zip(ids, ids[1:]):
            pairs += 1
            adjacent += (b - a == 1)
    return {
        "days": len(wave), "verses": sum(c["n"] for c in wave), "books": len(books),
        "sections": dict(Counter(c["section"] for c in wave)),
        "max_same_book_streak": best,
        "continuity": round(adjacent / pairs, 2) if pairs else 0.0,   # 같은 책 안에서 성경 순서로 이웃한 하루치끼리 이어진 비율
        "low_density": sum(c["density"] == "low" for c in wave), "short": sum(c["short"] for c in wave),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skeleton", default=str(ROOT / "build" / "skeleton.json"))
    ap.add_argument("--strategy", choices=["canon", "mix", "spread", "sweep"], default="mix")
    ap.add_argument("--wave", type=int, default=1)
    ap.add_argument("--size", type=int, default=365)
    ap.add_argument("--out")
    ap.add_argument("--compare", action="store_true")
    a = ap.parse_args(argv)
    chunks = json.loads(Path(a.skeleton).read_text(encoding="utf-8"))["chunks"]
    if a.compare:
        for strat in ("canon", "mix", "spread", "sweep"):
            first = waves(chunks, strat, a.size)[0]
            r = report(first, chunks)
            print(f"[{strat}] 첫 해 {r['days']}일, {r['verses']}절, 닿는 책 {r['books']}/66, 같은 책 연속 최대 {r['max_same_book_streak']}일, "
                  f"이야기 이어짐 {r['continuity']}, 저밀도 {r['low_density']}일, 짧은 날 {r['short']}일")
            print("      갈래:", ", ".join(f"{k} {v}" for k, v in r["sections"].items()))
        return 0
    ws = waves(chunks, a.strategy, a.size)
    if not 1 <= a.wave <= len(ws):
        ap.error(f"--wave 는 1~{len(ws)}")
    wave = ws[a.wave - 1]
    if a.out:
        Path(a.out).write_text(json.dumps({"strategy": a.strategy, "wave": a.wave, "size": a.size, "chunks": wave}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report(wave, chunks), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
