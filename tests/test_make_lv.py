"""암송 가림 단계 계산 시험: python -m unittest tests.test_make_lv -v   (kiwipiepy 없이 돈다)

형태소 분석기 자리에는 어절 앞 두 글자를 명사, 나머지를 조사로 보는 가짜를 쓴다. 분석기를 쓴 실제 값과의 대조는
`python tools/make_lv.py --verify`(kiwipiepy 가 있는 가상환경에서)로 한다."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import make_lv as M  # noqa: E402


def fake_tokenize(text):
    """어절의 앞 두 글자는 명사(NNG), 나머지는 조사(JKS). 쉼표와 마침표는 문장부호(SP)."""
    out, pos = [], 0
    for w in text.split(" "):
        st = text.index(w, pos)
        pos = st + len(w)
        core = w.rstrip(",.")
        out.append((core[:2], "NNG", st, min(2, len(core))))
        if len(core) > 2:
            out.append((core[2:], "JKS", st + 2, len(core) - 2))
        for i in range(len(core), len(w)):
            out.append((w[i], "SP", st + i, 1))
    return out


def freq_for(texts, **override):
    """가짜 분석기가 뽑는 명사마다 구절 수 5000(흔함)을 주고 override 로 몇 개를 드물게 만든다."""
    stems = {t[0] for text in texts for t in fake_tokenize(text) if t[1] == "NNG"}
    df = {s: 5000 for s in stems}
    df.update(override)
    return {"n": 31000, "df": df, "dft": {f"{s}|NNG": n for s, n in df.items()}}


class Levels(unittest.TestCase):
    def test_tags_map_to_old_levels(self):
        self.assertEqual([M.level_of(t) for t in ("NNG", "VV-I", "MAG", "JKS", "EF", "SF", "SP")], [2, 2, 2, 3, 3, 0, 0])

    def day(self, *texts, title=""):
        return {"title": title, "verses": [[1, i + 1, t] for i, t in enumerate(texts)]}

    def test_one_string_per_verse_with_the_same_length_and_zero_on_spaces(self):
        item = self.day("하나님이 하늘과 땅을 지으시니", "바다에 물고기가 가득하더라")
        freq = freq_for([v[2] for v in item["verses"]], 바다=90)
        lv, kw = M.build_day(item, fake_tokenize, freq)
        self.assertEqual(M.check_lv(item, lv), [])
        self.assertEqual(len(kw), 2)
        for (_c, _v, t), s in zip(item["verses"], lv):
            self.assertTrue(all(code == "0" for ch, code in zip(t, s) if ch == " "))

    def test_keywords_are_one_to_three_per_verse_and_marked_one(self):
        short = self.day("하늘과 땅")
        long_ = self.day(" ".join(["하나님은 하늘에서 바다를 보시고 물고기를 지으셨다"] * 5))
        for item, want in ((short, 1), (long_, 2)):     # 70자마다 하나, 가짜 분석기에서는 같은 낱말이 거듭 나와 둘까지 간다
            freq = freq_for([v[2] for v in item["verses"]], 바다=90, 물고=40)
            lv, kw = M.build_day(item, fake_tokenize, freq)
            self.assertEqual(len(kw[0]), want, item)
            self.assertTrue(any(ch == "1" for ch in lv[0]))

    def test_the_step_two_codes_split_into_important_words_and_the_rest_and_particles_become_four(self):
        text = "바다와 하늘을 보시고 하나님이"
        item = self.day(text)
        freq = freq_for([text], 바다=90, 하늘=400)      # 바다와 하늘은 드물어 중요하고 보시, 하나는 흔하다
        lv, kw = M.build_day(item, fake_tokenize, freq)
        self.assertEqual(kw[0], ["바다"])                # 가장 드문 낱말이 핵심 단어
        self.assertEqual(lv[0], "11" + "4" + "0" + "22" + "4" + "0" + "33" + "4" + "0" + "33" + "44")

    def test_a_word_in_the_title_is_important_even_if_common(self):
        text = "바다와 하늘을 보시고 하나님이"
        freq = freq_for([text], 바다=90, 하늘=400, 하나=5000)
        lv, kw = M.build_day(self.day(text, title="하나님의 말씀"), fake_tokenize, freq)   # 제목에 '하나' 가 든 낱말은 없으니 영향 없음
        lv2, kw2 = M.build_day(self.day(text, title="보시고 하나"), fake_tokenize, freq)
        self.assertNotEqual(lv, lv2)

    def test_merged_verses_are_never_hidden(self):
        item = self.day("하나님이 하늘을 지으시니", "(앞절과 동일)", "12절과 상동")
        lv, kw = M.build_day(item, fake_tokenize, freq_for([v[2] for v in item["verses"]]))
        self.assertEqual(lv[1], "0" * len("(앞절과 동일)"))
        self.assertEqual(lv[2], "0" * len("12절과 상동"))
        self.assertEqual(kw[1:], [[], []])

    def test_check_lv_finds_bad_shapes(self):
        item = self.day("하늘과 땅")
        self.assertTrue(M.check_lv(item, []))
        self.assertTrue(M.check_lv(item, ["11"]))
        self.assertTrue(M.check_lv(item, ["1a2 3"]))
        self.assertTrue(M.check_lv(item, ["1215"]))     # 5 는 없는 코드
        self.assertTrue(M.check_lv(item, ["12123"]))    # 공백 자리에 0 이 아닌 코드
        self.assertEqual(M.check_lv(item, ["11401"]), [])


class CurrentPlan(unittest.TestCase):
    """지금 plan.json 의 lv 는 본문과 짜임이 맞는다(분석기 없이 확인할 수 있는 부분)."""

    def test_every_day_has_a_well_formed_lv(self):
        plan = json.loads((ROOT / "data" / "plan.json").read_text(encoding="utf-8"))
        bad = []
        for d in plan["days"]:
            bad += [f"{d['day']}일: {p}" for p in M.check_lv(d, d.get("lv") or [])]
        self.assertEqual(bad[:5], [])


if __name__ == "__main__":
    unittest.main()
