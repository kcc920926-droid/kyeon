"""남은 절을 하루치로 나누는 도구와 순서 전략 시험: python -m unittest tests.test_skeleton -v   (tkinter 없이도 돈다)

가짜 성경으로 도구의 규칙을 시험하고, build/krv.json 이 있는 PC 에서는 진짜 자료로도 돌린다."""
import json
import sys
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import bible  # noqa: E402
import schedule  # noqa: E402
import skeleton  # noqa: E402

REAL = bible.DEFAULT_SOURCE


def fake_db():
    """창세기(저밀도인 5장 포함), 출애굽기, 시편, 마태복음만 든 가짜 성경. 절마다 '책 장:절' 이 글이다."""
    shape = {"창세기": [12, 30, 12, 9, 40, 14], "출애굽기": [22, 25, 20], "시편": [6, 8], "마태복음": [25, 25, 9]}
    return {b: {c + 1: {v + 1: f"{b} {c + 1}:{v + 1}" for v in range(n)} for c, n in enumerate(chs)} for b, chs in shape.items()}


def covered_of(db, spec):
    return {(b, c, v) for b, c, v1, v2 in spec for v in range(v1, v2 + 1)}


class Parts(unittest.TestCase):
    def setUp(self):
        self.db = fake_db()
        # 창세기 1장 앞쪽과 3장 한가운데, 마태복음 1장 앞쪽이 이미 담겼다고 본다
        self.covered = covered_of(self.db, [("창세기", 1, 1, 5), ("창세기", 3, 5, 8), ("마태복음", 1, 1, 8)])

    def test_every_remaining_verse_is_in_exactly_one_chunk(self):
        chunks = skeleton.build(self.db, self.covered, 30)
        self.assertEqual(skeleton.problems_of(chunks, self.db, self.covered, 30), [])
        seen = Counter((c["book"], ch, v) for c in chunks for ch, v, _t in bible.resolve(self.db, c["book"], c["range"])[0])
        everything = {(b, c, v) for b in self.db for c in self.db[b] for v in self.db[b][c]}
        self.assertEqual(set(seen), everything - self.covered)
        self.assertEqual(set(seen.values()), {1})

    def test_total_is_exact_and_out_of_range_totals_are_refused(self):
        for total in (22, 30, 41):
            self.assertEqual(len(skeleton.build(self.db, self.covered, total)), total)
        with self.assertRaises(ValueError):
            skeleton.build(self.db, self.covered, 3)
        with self.assertRaises(ValueError):
            skeleton.build(self.db, self.covered, 500)

    def test_sizes_stay_in_range_and_tiny_runs_stay_whole(self):
        chunks = skeleton.build(self.db, self.covered, 30)
        for c in chunks:
            self.assertLessEqual(c["n"], skeleton.MAX_LOW if c["density"] == "low" else skeleton.MAX_NORMAL, c["id"])
            if not c["short"]:
                self.assertGreaterEqual(c["n"], 3, c["id"])   # 덩어리가 작아서 어쩔 수 없는 것만 짧다
        # 창세기 3:9 부터 끝까지는 절 4개뿐이고 앞뒤가 이미 담긴 절이라 덩어리가 나뉘지 않는다
        self.assertTrue(any(c["id"] == "창세기:3:9" for c in chunks))

    def test_low_density_text_is_packed_bigger(self):
        db = {"창세기": {5: {v: "가" for v in range(1, 61)}, 6: {v: "나" for v in range(1, 61)}}}
        chunks = skeleton.build(db, set(), 12)
        low = [c["n"] for c in chunks if c["range"].startswith("5:")]
        norm = [c["n"] for c in chunks if c["range"].startswith("6:")]
        self.assertGreater(sum(low) / len(low), sum(norm) / len(norm))

    def test_chunks_prefer_to_end_where_a_chapter_ends(self):
        chunks = skeleton.build(self.db, set(), 20)
        at_chapter_end = 0
        for c in chunks:
            last = c["range"].split("-")[-1]
            chapter, verse = (int(x) for x in last.split(":")) if ":" in last else (int(c["range"].split(":")[0]), int(last))
            at_chapter_end += verse == max(self.db[c["book"]][chapter])
        self.assertGreater(at_chapter_end, len(chunks) // 2)

    def test_same_input_gives_the_same_result(self):
        a = skeleton.build(self.db, self.covered, 30)
        b = skeleton.build(self.db, self.covered, 30)
        self.assertEqual(a, b)

    def test_cuts_are_used_when_valid_and_refused_when_not(self):
        runs = {r["id"]: r for r in skeleton.runs_of(self.db, self.covered)}
        run = runs["출애굽기:1:1"]
        self.assertEqual(len(run["verses"]), 67)
        good = skeleton.build(self.db, self.covered, 30, {"출애굽기:1:1": ["1:12", "2:1", "2:12", "2:20", "3:1", "3:11"]})
        mine = [c["range"] for c in good if c["book"] == "출애굽기"]
        self.assertEqual(mine[:3], ["1:1-11", "1:12-22", "2:1-11"])
        self.assertEqual(skeleton.problems_of(good, self.db, self.covered), [])
        with self.assertRaises(ValueError):   # 한 덩이가 너무 크다
            skeleton.build(self.db, self.covered, 30, {"출애굽기:1:1": ["3:1"]})
        with self.assertRaises(ValueError):   # 덩어리 안에 없는 자리
            skeleton.build(self.db, self.covered, 30, {"출애굽기:1:1": ["9:9"]})

    def test_problems_are_found(self):
        chunks = skeleton.build(self.db, self.covered, 30)
        self.assertTrue(skeleton.problems_of(chunks[1:], self.db, self.covered))   # 하나 빠짐
        self.assertTrue(skeleton.problems_of(chunks + chunks[:1], self.db, self.covered))   # 겹침
        self.assertTrue(skeleton.problems_of(chunks, self.db, set()))   # 이미 담긴 절을 담기지 않았다고 하면 그 절들이 빠진 것으로 잡힌다
        self.assertTrue(skeleton.problems_of(chunks, self.db, self.covered | {("출애굽기", 1, 1)}))   # 새 덩어리가 이미 담긴 절을 건드린다
        self.assertTrue(skeleton.problems_of(chunks, self.db, self.covered, 99))   # 개수가 다름

    def test_absent_verses_do_not_break_runs_or_count(self):
        db = {"마태복음": {1: {1: "가", 2: "나", 3: "[없음]", 4: "라", 5: "마", 6: "바", 7: "사", 8: "아"}}}
        runs = skeleton.runs_of(db, set())
        self.assertEqual(len(runs), 1)
        self.assertEqual(len(runs[0]["verses"]), 7)


class Order(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db = {b: {c: {v: f"{b}{c}{v}" for v in range(1, 9)} for c in range(1, n + 1)}
              for b, n in (("창세기", 50), ("출애굽기", 40), ("여호수아", 24), ("이사야", 66), ("욥기", 42), ("마태복음", 28), ("로마서", 16), ("사도행전", 28), ("요한계시록", 22))}
        cls.chunks = skeleton.build(db, set(), 330)

    def test_every_strategy_uses_each_chunk_exactly_once(self):
        ids = sorted(c["id"] for c in self.chunks)
        for strat in ("canon", "mix", "spread", "sweep"):
            got = sorted(c["id"] for w in schedule.waves(self.chunks, strat, 50) for c in w)
            self.assertEqual(got, ids, strat)

    def test_waves_have_the_requested_size(self):
        sizes = [len(w) for w in schedule.waves(self.chunks, "spread", 50)]
        self.assertEqual(sizes, [50] * 6 + [30])

    def test_spread_touches_every_book_in_the_first_wave_and_keeps_stories_in_order(self):
        first = schedule.waves(self.chunks, "spread", 50)[0]
        rep = schedule.report(first, self.chunks)
        self.assertEqual(rep["books"], 9)
        self.assertEqual(rep["continuity"], 1.0)
        self.assertLessEqual(rep["max_same_book_streak"], 3)

    def test_canon_first_wave_is_one_long_stretch_and_sweep_breaks_stories(self):
        rep_canon = schedule.report(schedule.waves(self.chunks, "canon", 50)[0], self.chunks)
        rep_sweep = schedule.report(schedule.waves(self.chunks, "sweep", 50)[0], self.chunks)
        self.assertGreater(rep_canon["max_same_book_streak"], 20)
        self.assertLess(rep_sweep["continuity"], 0.5)

    def test_within_a_book_the_reading_order_is_the_bible_order_for_mix_and_spread(self):
        for strat in ("mix", "spread"):
            for wave in schedule.waves(self.chunks, strat, 100):
                last = {}
                for c in wave:
                    key = tuple(int(x) for x in c["id"].split(":")[1:])
                    self.assertGreater(key, last.get(c["book"], (0, 0)), (strat, c["id"]))
                    last[c["book"]] = key

    def test_deterministic(self):
        self.assertEqual(schedule.waves(self.chunks, "sweep", 50), schedule.waves(self.chunks, "sweep", 50))


@unittest.skipUnless(REAL.is_file(), "build/krv.json 이 없는 PC 에서는 진짜 자료 시험을 건너뛴다")
class RealData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = bible.load_db()
        cls.plan = json.loads((ROOT / "data" / "plan.json").read_text(encoding="utf-8"))
        cls.covered = bible.covered(cls.plan)

    def test_source_has_the_whole_bible(self):
        self.assertEqual(len(self.db), 66)
        self.assertEqual(sum(len(c) for c in self.db.values()), 1189)
        self.assertEqual(sum(len(v) for b in self.db.values() for v in b.values()), 31102)

    def test_source_reproduces_every_verse_and_psalm_note_in_the_plan(self):
        for d in self.plan["days"]:
            (c1, v1), (c2, v2) = d["verses"][0][:2], d["verses"][-1][:2]
            rng = f"{c1}:{v1}-{v2}" if c1 == c2 else f"{c1}:{v1}-{c2}:{v2}"
            verses, note = bible.resolve(self.db, bible.book_of(d["ref"]), rng)
            self.assertEqual(verses, d["verses"], d["ref"])
            self.assertEqual(note, d.get("note"), d["ref"])

    def test_remaining_bible_splits_into_exactly_2650_days(self):
        chunks = skeleton.build(self.db, self.covered, 2650)
        self.assertEqual(skeleton.problems_of(chunks, self.db, self.covered, 2650), [])
        sizes = [c["n"] for c in chunks]
        self.assertLessEqual(max(sizes), skeleton.MAX_LOW)
        self.assertAlmostEqual(sum(sizes) / len(sizes), 8.4, delta=0.2)
        self.assertLess(sum(c["short"] for c in chunks), 80)

    def test_spread_first_year_reaches_most_books(self):
        chunks = skeleton.build(self.db, self.covered, 2650)
        rep = schedule.report(schedule.waves(chunks, "spread", 365)[0], chunks)
        self.assertGreaterEqual(rep["books"], 50)
        self.assertEqual(rep["continuity"], 1.0)


if __name__ == "__main__":
    unittest.main()
