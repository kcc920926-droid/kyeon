"""장면 장부 도구 시험: python -m unittest tests.test_ledger -v   (kiwipiepy 없이 돈다)"""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import dupcheck  # noqa: E402
import ledger as L  # noqa: E402


def fake_tokenize(text):
    """공백으로 나눈 어절에서 끝의 조사 한 글자를 떼어 명사(NNG)로 본다. 마침표는 버린다."""
    out, pos = [], 0
    for w in re.sub(r"[.,]", " ", text).split():
        st = text.index(w, pos)
        pos = st + len(w)
        stem = re.sub(r"(은|는|이|가|을|를|에|에서|의|과|와|도)$", "", w)
        out.append((stem, "VV" if w.endswith("니다") else "NNG", st, len(stem)))
    return out


def plan_of(texts):
    return {"days": [{"day": d, "ref": f"시편 {d}편", "title": f"제목{d}", "blocks": [{"label": "그 당시", "text": "배경."}, {"label": "오늘", "text": t}]}
                     for d, t in texts.items()]}


TEXTS = {
    1: "등대가 보이는 새벽 항구에서 어부가 그물을 손봅니다. 시인은 빛을 노래합니다. 끝입니다.",
    2: "정년을 앞둔 교사가 칠판을 지웁니다. 시인은 날수를 셉니다. 끝입니다.",
    3: "등대가 보이는 새벽 항구에서 선원이 닻을 올립니다. 시인은 길을 노래합니다. 끝입니다.",
}
NAMES = [{"day": d, "name": f"장면 이름 {d}번", "category": "직장·일", "link": "빛과 길이 이어짐"} for d in TEXTS]


class Prepare(unittest.TestCase):
    def test_chunks_cover_every_day_with_the_first_two_sentences(self):
        plan = plan_of({d: f"첫 문장 {d}입니다. 둘째 문장입니다. 셋째 문장입니다." for d in range(1, 8)})
        with tempfile.TemporaryDirectory() as td:
            n = L.prepare(plan, Path(td), size=3)
            self.assertEqual(n, 3)
            items = [x for i in range(1, n + 1) for x in json.loads((Path(td) / f"chunk_{i:02d}.json").read_text(encoding="utf-8"))]
        self.assertEqual([x["day"] for x in items], list(range(1, 8)))
        self.assertEqual(items[0]["head"], "첫 문장 1입니다. 둘째 문장입니다.")


class CheckNames(unittest.TestCase):
    def test_good_names_pass(self):
        self.assertEqual(L.check_names(NAMES, [1, 2, 3]), [])

    def test_bad_names_are_found(self):
        bad = json.loads(json.dumps(NAMES))
        bad[0]["category"] = "없는 범주"
        bad[1]["link"] = ""
        bad[2]["name"] = bad[1]["name"]
        problems = "\n".join(L.check_names(bad[:3] + [{"day": 9, "name": "가나다라마바", "category": "직장·일", "link": "연결 고리"}], [1, 2, 3]))
        for needle in ("1일: 범주", "2일: 연결고리", "3일: 장면 이름", "입력에 없는 일차"):
            self.assertIn(needle, problems)
        self.assertIn("4일: 항목이 0개", "\n".join(L.check_names(NAMES, [1, 2, 3, 4])))


class Words(unittest.TestCase):
    def test_words_that_appear_in_no_other_day_are_picked_and_longer_ones_first(self):
        words, overlap = L.pick_words(2, TEXTS, fake_tokenize)
        self.assertTrue(2 <= len(words) <= 3, words)
        self.assertNotIn("시인", words)            # 1일과 3일에도 있다
        self.assertTrue(all(not any(w in t for d, t in TEXTS.items() if d != 2) for w in words), words)
        self.assertEqual(overlap, [])
        self.assertTrue(all(w in TEXTS[2] for w in words))

    def test_two_days_with_the_same_scene_cannot_get_exclusive_words(self):
        w1, o1 = L.pick_words(1, TEXTS, fake_tokenize)
        w3, o3 = L.pick_words(3, TEXTS, fake_tokenize)
        self.assertNotIn("등대", w1)             # 3일에도 있다
        self.assertIn("어부", w1)                # 1일에만 있다
        self.assertIn("그물", w1)

    def test_a_scene_without_two_exclusive_words_is_marked_for_review_with_its_twin(self):
        texts = {1: "등대가 보이는 항구 새벽입니다. 둘째입니다.", 2: "등대가 보이는 항구 새벽입니다. 다른 말입니다.", 3: "전혀 다른 글입니다. 둘째입니다."}
        # 1일의 첫 두 문장 명사는 모두 2일에도 있다
        ledger = L.build(plan_of(texts), [{"day": d, "name": f"장면 {d}번", "category": "직장·일", "link": "연결고리 한 줄"} for d in texts], fake_tokenize)
        self.assertTrue(ledger["scenes"]["1"].get("review"))
        self.assertEqual(ledger["scenes"]["1"]["overlaps_with"][0], 2)
        self.assertEqual(ledger["meta"]["review"] >= 1, True)


class Build(unittest.TestCase):
    def test_built_ledger_passes_the_shape_and_exclusivity_checks_it_can(self):
        ledger = L.build(plan_of(TEXTS), NAMES, fake_tokenize)
        ok = {k: v for k, v in ledger["scenes"].items() if not v.get("review")}
        self.assertEqual(ledger["meta"]["days"], 3)
        self.assertEqual(dupcheck.ledger_shape_problems({"scenes": ok}, TEXTS), [])
        self.assertEqual(dupcheck.scene_problems({"scenes": ok}, TEXTS), [])

    def test_report_runs(self):
        ledger = L.build(plan_of(TEXTS), NAMES, fake_tokenize)
        text = L.report(ledger)
        self.assertIn("장면 3개", text)
        self.assertIn("범주 비중", text)


class RealLedger(unittest.TestCase):
    """저장소의 ledger/scenes.json 이 plan.json 과 맞는지. 파일이 없으면 건너뛴다."""

    @classmethod
    def setUpClass(cls):
        path = ROOT / "ledger" / "scenes.json"
        if not path.is_file():
            raise unittest.SkipTest("ledger/scenes.json 이 없습니다")
        cls.ledger = json.loads(path.read_text(encoding="utf-8"))
        cls.plan = json.loads((ROOT / "data" / "plan.json").read_text(encoding="utf-8"))
        cls.texts = L.today_texts(cls.plan)

    def test_one_scene_for_every_day_that_has_an_today_paragraph(self):
        self.assertEqual(sorted(int(d) for d in self.ledger["scenes"]), sorted(self.texts))

    def test_shape_and_exclusivity_of_the_scenes_that_have_required_words(self):
        ok = {k: v for k, v in self.ledger["scenes"].items() if not v.get("review")}
        self.assertGreater(len(ok), 100)
        self.assertEqual(dupcheck.ledger_shape_problems({"scenes": ok}, self.texts), [])
        self.assertEqual(dupcheck.scene_problems({"scenes": ok}, {d: t for d, t in self.texts.items() if str(d) in ok}), [])

    def test_every_scene_has_a_category_a_name_and_a_link(self):
        for d, s in self.ledger["scenes"].items():
            self.assertIn(s["category"], dupcheck.CATEGORIES, d)
            self.assertTrue(4 <= len(s["name"]) <= 40 and 4 <= len(s["link"]) <= 80, d)


if __name__ == "__main__":
    unittest.main()
