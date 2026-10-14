"""파도 조립기 시험: python -m unittest tests.test_assemble -v   (kiwipiepy 없이 돈다)

본문은 작은 가짜 원본을 쓰고, 형태소 분석기 자리에는 test_make_lv 와 같은 가짜를 쓴다."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))
import assemble as A  # noqa: E402
import dupcheck  # noqa: E402

DB = {"창세기": {1: {1: "태초에 하나님이 천지를 창조하시니라", 2: "땅이 혼돈하고 공허하며 흑암이 깊음 위에 있고", 3: "하나님이 이르시되 빛이 있으라 하시니 빛이 있었고",
                   14: "하나님이 이르시되 하늘의 궁창에 광명체들이 있어 낮과 밤을 나뉘게 하라", 15: "그 광명체들이 하늘의 궁창에 있어 땅을 비추라 하시고 그대로 되니라",
                   16: "하나님이 두 큰 광명체를 만드사 큰 광명체로 낮을 주관하게 하시고", 17: "하나님이 그것들을 하늘의 궁창에 두어 땅을 비추게 하시며",
                   18: "낮과 밤을 주관하게 하시고 빛과 어둠을 나뉘게 하시니 하나님이 보시기에 좋았더라"},
               2: {1: "천지와 만물이 다 이루어지니라"}},
      "시편": {1: {1: "복 있는 사람은 악인의 꾀를 좇지 아니하며", 2: "오직 여호와의 율법을 즐거워하여"}}}


def fake_tokenize(text):
    out, pos = [], 0
    for w in text.split(" "):
        st = text.index(w, pos)
        pos = st + len(w)
        core = w.rstrip(",.")
        out.append((core[:2], "NNG", st, min(2, len(core))))
        if len(core) > 2:
            out.append((core[2:], "JKS", st + 2, len(core) - 2))
    return out


def fake_freq():
    stems = {t[0] for c in DB.values() for ch in c.values() for text in ch.values() for t in fake_tokenize(text) if t[1] == "NNG"}
    df = {s: 5000 for s in stems}
    return {"n": 31000, "df": df, "dft": {f"{s}|NNG": n for s, n in df.items()}}


def chunk(book="창세기", rng="1:1-3", ref="창세기 1:1–3", era="beginnings", section="구약 이야기"):
    return {"id": f"{book}:{rng.split('-')[0]}", "book": book, "range": rng, "ref": ref, "n": 3, "section": section, "stream": "율법", "era": era, "density": "normal", "short": True}


TODAY = ("집어등이 켜진 항구에서 새벽 통발이 그물을 걷는 시간이 옵니다. 선장은 말없이 닻줄을 감습니다. "
         "그 사람에게 빛이 있으라는 말은 거창한 선언이 아니라 오늘 첫 항로를 비추는 작은 불빛입니다.")
LINK = "본문의 빛 ↔ 집어등의 불빛"
POOL = [{"id": "s0001", "name": "새벽 항구에서 그물을 걷는 통발", "category": "농어촌·자연", "words": ["집어등", "통발"]},
        {"id": "s0002", "name": "야간 편의점 계산대에 선 점원", "category": "상가·서비스", "words": ["계산대", "점원"]}]


def commentary(day=1001, **over):
    c = {"day": day, "title": "빛이 있으라", "themes": ["god", "hope"], "format": 1,
         "blocks": [{"label": "그 당시", "text": "고대 사람들은 바다 같은 깊음을 두려워했습니다. 이 글은 그 어둠 한가운데서 말씀 하나로 빛이 생겼다고 적습니다. 이웃 나라의 창조 이야기에는 신들의 싸움이 나오지만 여기에는 싸움이 없습니다."},
                    {"label": "오늘", "text": TODAY}],
         "scene": "s0001", "link": LINK}
    c.update(over)
    return c


def item(day=1001, with_menu=True, ch=None):
    it = A.items_for([(day, ch or chunk())], DB, cats=["농어촌·자연"] if with_menu else None, menus=[["s0001", "s0002"]] if with_menu else None, pool=POOL)[0]
    return it


class Days(unittest.TestCase):
    CHUNKS = [chunk("창세기", f"{i}:1-3", f"창세기 {i}:1–3") for i in range(1, 8)]

    def test_numbers_continue_from_year_to_year_whatever_the_limit(self):
        a = A.day_numbers(self.CHUNKS, "canon", 0, 3)
        b = A.day_numbers(self.CHUNKS, "canon", 1, 3, limit=2)
        self.assertEqual([d for d, _c in a], [1001, 1002, 1003])
        self.assertEqual([d for d, _c in b], [1004, 1005])

    def test_a_year_that_does_not_exist_is_refused(self):
        with self.assertRaises(ValueError):
            A.day_numbers(self.CHUNKS, "canon", 9, 3)

    def test_items_carry_verses_category_and_a_menu(self):
        it = item()
        self.assertEqual(it["verses"][0][:2], [1, 1])
        self.assertEqual(it["category"], "농어촌·자연")
        self.assertEqual([m["id"] for m in it["menu"]], ["s0001", "s0002"])
        self.assertEqual(it["menu"][0]["words"], ["집어등", "통발"])
        self.assertNotIn("menu", item(with_menu=False))


class Commentary(unittest.TestCase):
    def problems(self, c, it=None):
        return "\n".join(A.check_commentary(c, it or item()))

    def test_a_good_one_passes(self):
        self.assertEqual(A.check_commentary(commentary(), item()), [])

    def test_wrong_day_title_themes_format(self):
        self.assertIn("day 가", self.problems(commentary(day=1002)))
        self.assertIn("title", self.problems(commentary(title="")))
        self.assertIn("themes", self.problems(commentary(themes=["god", "없는테마"])))
        self.assertIn("themes", self.problems(commentary(themes=[])))
        self.assertIn("format", self.problems(commentary(format=9)))

    def test_blocks_must_match_the_format(self):
        c = commentary()
        c["blocks"][0]["label"] = "흔한 읽기"
        self.assertIn("블록 라벨", self.problems(c))
        self.assertIn("블록이 3개", self.problems(commentary(format=2)))
        c3 = commentary(format=3, blocks=[{"label": "한 단어: 집어등", "text": "집어등라는 말은 어두운 바다에서 방향을 잡아 주는 불을 뜻합니다. 옛 사람은 이 말을 들으면 먼 불빛을 떠올렸습니다. 배가 돌아올 길이 거기서 시작된다고 믿었기 때문입니다."},
                                         {"label": "오늘", "text": TODAY}])
        self.assertEqual(A.check_commentary(c3, item()), [])
        c3["blocks"][0]["label"] = "한 단어: 아주아주아주긴낱말입니다"
        self.assertIn("한 단어: 낱말", self.problems(c3))

    def test_text_length_and_translationese_are_checked(self):
        c = commentary()
        c["blocks"][1]["text"] = "짧다."
        self.assertIn("자입니다", self.problems(c))
        c = commentary()
        c["blocks"][0]["text"] = "이 글은 그 일에 대해 말합니다. 그 사실에 대한 기록이 이어집니다. 사람들은 이 땅에 있어서 오래 기다렸습니다. " * 1
        self.assertIn("번역투", self.problems(c))

    def test_characters_the_style_guide_forbids_are_found(self):
        for bad, name in (("빛이 있으라 — 그 말씀입니다.", "대시"), ("빛(光)이 있었습니다.", "괄호"), ("빛이 있었을까요?", "물음표"),
                          ("light 가 있었습니다.", "영문"), ("하나님이 빛을 보시고 좋아하고, 어둠을 나누셨습니다.", "연결어미 뒤 쉼표")):
            c = commentary()
            c["blocks"][0]["text"] = c["blocks"][0]["text"] + " " + bad
            self.assertIn(name, self.problems(c), bad)

    def test_title_has_a_length_range(self):
        self.assertIn("title", self.problems(commentary(title="빛")))
        self.assertIn("title", self.problems(commentary(title="가" * 27)))

    def test_scene_must_come_from_the_menu_and_use_its_words(self):
        self.assertIn("메뉴", self.problems(commentary(scene="s0099")))
        other = commentary()
        other["blocks"][1]["text"] = "야간 편의점 계산대 앞에서 점원이 졸린 눈으로 바코드를 찍습니다. 손님이 없는 시간이 이어집니다. 그 사람에게도 말씀은 작은 불빛입니다."
        self.assertIn("필수어", self.problems(other))
        self.assertIn("link", self.problems(commentary(link="")))

    def test_parallels_are_other_passages(self):
        self.assertEqual(A.check_commentary(commentary(parallels=["역대상 1:1–4"]), item()), [])
        self.assertIn("parallels", self.problems(commentary(parallels=["창세기 1:1–3"])))
        self.assertIn("parallels", self.problems(commentary(parallels=["없는책 1:1"])))
        self.assertIn("parallels", self.problems(commentary(parallels=[])))


class Assemble(unittest.TestCase):
    def test_the_day_has_the_plan_keys_in_order_and_a_valid_lv(self):
        d = A.assemble_day(item(), commentary(), DB, fake_tokenize, fake_freq())
        self.assertEqual(list(d), ["day", "section", "ref", "title", "era", "themes", "verses", "format", "blocks", "lv"])
        self.assertEqual((d["ref"], d["era"], d["section"]), ("창세기 1:1–3", "beginnings", "구약 이야기"))
        self.assertEqual(len(d["lv"]), 3)
        self.assertTrue(all(len(s) == len(v[2]) for s, v in zip(d["lv"], d["verses"])))

    def test_parallels_go_between_themes_and_verses(self):
        d = A.assemble_day(item(), commentary(parallels=["역대상 1:1–4"]), DB, fake_tokenize, fake_freq())
        self.assertEqual(list(d)[5:8], ["themes", "parallels", "verses"])

    def test_a_stale_input_or_a_wrong_era_is_refused(self):
        it = item()
        it["verses"][0][2] = "바뀐 본문"
        with self.assertRaises(ValueError):
            A.assemble_day(it, commentary(), DB, fake_tokenize, fake_freq())
        it = item()
        it["era"] = "exodus"
        with self.assertRaises(ValueError):
            A.assemble_day(it, commentary(), DB, fake_tokenize, fake_freq())

    def test_ledger_entries_copy_the_chosen_scene(self):
        got = A.ledger_entries([item()], [commentary()])
        self.assertEqual(got, {"1001": {"name": "새벽 항구에서 그물을 걷는 통발", "category": "농어촌·자연", "words": ["집어등", "통발"], "link": LINK}})

    def test_written_days_read_back_one_line_per_day(self):
        d = A.assemble_day(item(), commentary(), DB, fake_tokenize, fake_freq())
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "w.json"
            A.write_days(p, [d, dict(d, day=1002)])
            raw = p.read_bytes().decode("utf-8")
            self.assertNotIn("\r", raw)
            self.assertEqual(json.loads(raw)["days"][1]["day"], 1002)
            self.assertEqual(sum(1 for ln in raw.split("\n") if ln.startswith('{"day":')), 2)


class Final(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = json.loads((ROOT / "data" / "plan.json").read_text(encoding="utf-8"))
        new = chunk(rng="1:14-18", ref="창세기 1:14–18")
        cls.day = A.assemble_day(item(ch=new), commentary(), DB, fake_tokenize, fake_freq())     # 지금 plan 에 없는 본문
        cls.baseline = set(dupcheck.corpus_problems(cls.plan))

    def test_a_new_day_with_a_new_passage_is_accepted(self):
        self.assertEqual(A.final_problems([self.day], self.plan, baseline=self.baseline), [])

    def test_an_old_passage_or_day_number_is_found(self):
        again = dict(self.day, day=1)
        self.assertTrue(any("이미 있거나" in p for p in A.final_problems([again], self.plan)))
        old = copy.deepcopy(self.plan["days"][0])
        old["day"] = 1001
        problems = "\n".join(A.final_problems([old], self.plan))
        self.assertIn("이미 다른 날에", problems)
        self.assertIn("같은 절", problems)

    def test_a_day_the_app_would_reject_is_found(self):
        broken = dict(self.day, blocks=[])
        self.assertTrue(any("day_ok" in p for p in A.final_problems([broken], self.plan)))

    def test_the_required_words_of_old_days_are_not_enforced_but_a_clash_with_an_old_text_is(self):
        old_ledger = {"scenes": {"5": {"name": "다른 장면 이름입니다", "category": "직장·일", "words": ["집어등", "항로"], "link": "연결고리 한 줄"}}}
        additions = {"1001": {"name": "새벽 항구에서 그물을 걷는 통발", "category": "농어촌·자연", "words": ["집어등", "통발"], "link": LINK}}
        # 기존 장부의 필수어(집어등)를 새 글이 써도 막지 않는다
        self.assertEqual(A.final_problems([self.day], self.plan, old_ledger, additions, baseline=self.baseline), [])
        # 새 장면의 필수어가 기존 오늘 단락에 이미 있으면 막는다
        clash = {"1001": dict(additions["1001"], words=["기도", "통발"])}
        problems = " ".join(A.final_problems([self.day], self.plan, old_ledger, clash, baseline=self.baseline))
        self.assertIn("기도", problems)

    def test_assigned_scenes_leave_out_the_reserve_candidates(self):
        items = [item(), dict(item(), day=1002)]
        self.assertEqual(sorted(A.assigned_scenes(items)), ["s0001", "s0002"])


if __name__ == "__main__":
    unittest.main()
