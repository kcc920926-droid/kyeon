"""해설 번역투 점검: python -m unittest tests.test_style -v   (tkinter 없이도 돈다)"""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import tlint  # noqa: E402


def ids(text):
    return {h[0] for h in tlint.check_block(text)}


class Rules(unittest.TestCase):
    def test_catches_known_translationese(self):
        self.assertIn("L-1", ids("시편 1편은 그 장면을 악인의 모습에 빌려 씁니다."))
        self.assertIn("L-1", ids("농사 말을 빌려 쓴 것입니다."))
        self.assertIn("A-3", ids("예배에 있어서 중요한 것은 마음입니다."))
        self.assertIn("A-7", ids("그는 힘을 가지고 있었습니다."))
        self.assertIn("A-8", ids("이 뜻은 오래 잊혀져 되어진 것입니다."))
        self.assertIn("L-13", ids("이 말에는 무게가 실립니다."))
        self.assertIn("L-14", ids("본문은 하나님이 먼저 오셨다고 알려 줍니다. 이 구절은 그분의 이름을 소개합니다."))

    def test_cap_allows_one_but_not_two(self):
        one = "이 일에 대해 사람들은 오래 이야기했습니다."
        two = one + " 그 일에 대해 다시 말했습니다."
        self.assertNotIn("A-1", ids(one))
        self.assertIn("A-1", ids(two))

    def test_quoted_scripture_is_not_checked(self):
        self.assertEqual(tlint.check_block('그는 "이를 위하여 가지고 있는 것을 빌려" 주었다고 했습니다.'), [])

    def test_ordinary_words_that_contain_a_rule_are_not_flagged(self):
        for s in ("열쇠는 책상 위에 있어요. 문서는 서랍에 있었습니다.",   # 장소를 말하는 '에 있어' 는 에 있어서 와 다르다
                  "그는 이웃에게 돈을 빌려 달라고 청했습니다.",   # 돈을 꾸는 말
                  "마음이 안전해진 사람은 오래 머물렀습니다.",   # 안전해진 ≠ 전해진
                  "바람에 문이 흔들립니다. 그리고 흔들렸습니다.".replace("그리고 ", ""),   # 흔들립니다 ≠ 들립니다
                  "사람들은 하늘이 아니라 불 가운데서 나타나셨다고 했습니다.",   # 아니라 불 ≠ 라 불리다
                  "차를 마시는 풍습이 있었습니다. 새 포도주를 마시는 사람도 있었습니다."):
            self.assertEqual(tlint.check_block(s), [], s)

    def test_natural_sentences_pass(self):
        for s in ("타작마당에서 곡식을 던져 올리면 무거운 알곡은 남고 가벼운 겨는 흩어졌습니다.",
                  "시편 1편은 악인을 바로 그 겨에 견줍니다.",
                  "듣던 사람들은 이 이야기를 이웃 마을 소문처럼 들었을 것입니다."):
            self.assertEqual(tlint.check_block(s), [], s)

    def test_corpus_quota_trips(self):
        texts = ["평범한 문장입니다."] * 100 + ["이 길은 여리고에 놓여 있습니다."] * 10
        self.assertTrue(any(r[0] == "L-5" for r in tlint.corpus_check(texts)))


class Hedges(unittest.TestCase):
    """추정을 흐리는 말투가 날마다 같은 틀로 되풀이되지 않게 막는다(L-17, L-18)."""

    def test_one_hedge_is_fine_but_two_of_the_same_formula_are_not(self):
        one = "이 이름의 뜻은 풀이하는 이가 많습니다."
        self.assertNotIn("L-17", ids(one))
        self.assertIn("L-17", ids(one + " 이 말도 읽는 이가 많습니다."))
        self.assertNotIn("L-18", ids("곁에서 듣던 사람은 놀랐을 법합니다. 그 소리가 멀리 퍼졌을 듯합니다."))
        self.assertIn("L-18", ids("놀랐을 법합니다. 퍼졌을 듯합니다. 달려왔을 법합니다."))

    def test_a_corpus_full_of_the_formula_trips_the_quota(self):
        texts = ["평범한 문장입니다."] * 100 + ["이 이름은 보는 이가 많습니다."] * 10
        self.assertTrue(any(r[0] == "L-17" for r in tlint.corpus_check(texts)))
        texts = ["평범한 문장입니다."] * 100 + ["그 소리에 놀랐을 법합니다."] * 20
        self.assertTrue(any(r[0] == "L-18" for r in tlint.corpus_check(texts)))


class RouteNames(unittest.TestCase):
    """사용자에게 보이는 시기·테마의 이름과 설명도 번역투 없이 쓴다."""

    def test_route_names_and_descriptions_have_no_translationese(self):
        import routes
        for r in routes.ERAS + routes.THEMES:
            for field in ("name", "about"):
                masked = tlint.mask(r[field])
                found = [m.group(0) for _i, rx, *_ in tlint.COMPILED for m in rx.finditer(masked)]
                self.assertEqual(found, [], f"{r['id']} {field}: {r[field]}")


class LicenseFiles(unittest.TestCase):
    """공개 저장소의 라이선스 안내가 빠지거나 어긋나지 않게 지킨다."""

    def test_license_is_the_plain_mit_text(self):
        text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("MIT License\n\nCopyright (c) 2026 "), text[:60])
        self.assertIn("Permission is hereby granted, free of charge", text)
        self.assertIn('THE SOFTWARE IS PROVIDED "AS IS"', text)

    def test_notice_keeps_the_upstream_mit_notice_and_leaves_the_bible_text_out(self):
        notice = (ROOT / "NOTICE.md").read_text(encoding="utf-8")
        self.assertIn("Copyright (c) 2026 epoko77-ai", notice)       # im-not-ai 의 MIT 는 저작권 표시를 함께 두어야 한다
        self.assertIn("CC BY 4.0", notice)
        self.assertRegex(notice, r"성경 본문\(`data/plan.json`의 `verses`\) \| \*\*이 프로젝트의 라이선스에 포함되지 않습니다")

    def test_readme_points_to_the_license_files(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("(LICENSE)", readme)
        self.assertIn("(NOTICE.md)", readme)
        self.assertNotIn("라이선스는 아직 정하지 않았", readme)

    def test_bible_text_credits_its_author(self):
        """개역한글판은 저작재산권이 끝났어도 성명표시권과 동일성유지권은 남는다(대한성서공회 안내). 저작자를 밝혀 둔다."""
        notice = (ROOT / "NOTICE.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("성경 본문: 『성경전서 개역한글판』, 대한성서공회, 1961", notice)
        self.assertIn("저작자: 대한성서공회, 『성경전서 개역한글판』, 1961.", readme)
        self.assertNotIn("직접 확인해 준 건 아니에요", readme)

    def test_fonts_keep_their_own_license_file(self):
        self.assertIn("SIL Open Font License", (ROOT / "fonts" / "LICENSE.txt").read_text(encoding="utf-8"))


class StyleGuide(unittest.TestCase):
    """docs/STYLE.md 의 모범 예는 본보기이므로, 번역투 규칙에 한 번도 걸리지 않아야 한다."""

    def test_model_examples_have_no_translationese(self):
        src = (ROOT / "docs" / "STYLE.md").read_text(encoding="utf-8")
        section = src.split("### 모범 예")[1].split("## 3. 내용 원칙")[0]
        examples = [m.group(2) for m in re.finditer(r"^\s*- ([^:\n]+): (.+)$", section, re.M)]
        self.assertGreaterEqual(len(examples), 12)
        for text in examples:
            masked = tlint.mask(text)
            found = [m.group(0) for _i, rx, *_ in tlint.COMPILED for m in rx.finditer(masked)]
            self.assertEqual(found, [], text)


class PlanText(unittest.TestCase):
    """data/plan.json 의 해설 전체가 번역투 점검을 통과해야 한다(새로 쓴 해설도 같은 기준)."""

    @classmethod
    def setUpClass(cls):
        plan = json.loads((ROOT / "data" / "plan.json").read_text(encoding="utf-8"))
        cls.items = [(d["day"], k, b["text"]) for d in plan["days"] for k, b in enumerate(d["blocks"])]

    def test_no_block_over_cap(self):
        bad = [(day, k + 1, tlint.check_block(tx)) for day, k, tx in self.items if tlint.check_block(tx)]
        msg = "\n".join(f"{day}일 {k}번째 블록: " + ", ".join(f"{h[2]}({h[0]})" for h in hits) for day, k, hits in bad[:15])
        self.assertEqual(bad, [], f"번역투 {len(bad)}블록\n{msg}")

    def test_corpus_quota(self):
        over = tlint.corpus_check([tx for _d, _k, tx in self.items])
        self.assertEqual(over, [], "\n".join(f"{rid} {label}: {have}블록 (허용 {allow})" for rid, label, have, allow in over))


if __name__ == "__main__":
    unittest.main()
