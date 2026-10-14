"""장면 배정 도구 시험: python -m unittest tests.test_assign -v   (tkinter, kiwipiepy 없이 돈다)"""
import sys
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import assign as A  # noqa: E402
import dupcheck as D  # noqa: E402

# 기존 장부: 가정·육아와 이웃·관계에 몰려 있다
OLD = {"가정·육아": 140, "이웃·관계": 120, "직장·일": 90, "의료·건강": 80, "이동·교통": 70, "디지털·소통": 60, "돈·살림": 80,
       "학교·청년": 60, "농어촌·자연": 40, "날씨·계절": 40, "의례·행사": 60, "노년·돌봄": 40, "상가·서비스": 50,
       "여가·취미": 30, "재난·사고": 20, "공공·제도": 20}


SYL = "가나다라마바사아자차카타파하거너더러머버"      # 20개. 조사로 쓰는 '를' 따위는 넣지 않아 낱말끼리 부분 문자열이 되지 않는다


def hw(n):
    """n 번째 세 음절 낱말(서로 다르다)"""
    return SYL[n // 400 % 20] + SYL[n // 20 % 20] + SYL[n % 20]


def pool_of(per_category=20):
    pool, n = [], 0
    for ci, c in enumerate(D.CATEGORIES):
        for j in range(per_category):
            pool.append({"id": f"s{ci:02d}{j:02d}", "name": f"{c} 장면 {j}번", "category": c, "words": [hw(2 * n), hw(2 * n + 1)]})
            n += 1
    return pool


class Categories(unittest.TestCase):
    def test_new_days_even_out_the_totals_and_keep_to_the_windows(self):
        cats = A.plan_categories(365, OLD)
        self.assertEqual(len(cats), 365)
        new = Counter(cats)
        total = Counter(OLD) + new
        n = sum(total.values())
        for c in D.CATEGORIES:
            if OLD[c] / n > D.CATEGORY_SHARE:
                self.assertEqual(new[c], 0, c)               # 이미 상한을 넘은 범주에는 새 날을 더하지 않는다
            else:
                self.assertLessEqual(total[c] / n, D.CATEGORY_SHARE + 1e-9, c)
        ledger = {"scenes": {str(i): {"category": c} for i, c in enumerate(cats)}}
        self.assertEqual(D.window_problems(ledger, list(range(len(cats))), share=1.0), [])

    def test_overrepresented_categories_get_fewer_new_days(self):
        cats = Counter(A.plan_categories(365, OLD))
        self.assertLess(cats["가정·육아"], cats["공공·제도"])
        self.assertLess(cats["이웃·관계"], cats["재난·사고"] + 40)

    def test_never_the_same_category_two_days_in_a_row_when_avoidable(self):
        cats = A.plan_categories(200, OLD)
        self.assertEqual(sum(a == b for a, b in zip(cats, cats[1:])), 0)

    def test_deterministic(self):
        self.assertEqual(A.plan_categories(100, OLD), A.plan_categories(100, OLD))


class Pool(unittest.TestCase):
    def test_a_good_pool_passes(self):
        self.assertEqual(A.pool_problems(pool_of(3)), [])

    def test_shape_and_exclusivity_problems(self):
        pool = pool_of(2)
        pool[1]["words"] = list(pool[0]["words"])            # 낱말이 같다
        pool[2]["name"] = pool[3]["name"]                    # 이름이 같다
        pool[4]["category"] = "없는 범주"
        pool[5]["words"] = ["하나"]
        problems = "\n".join(A.pool_problems(pool, existing_texts={7: f"기존 글에 {pool[6]['words'][0]} 가 있습니다"}, existing_words={pool[8]["words"][1]}))
        for needle in ("같이 있습니다", "이름이", "범주 '없는 범주'", "필수어는 2~3개", "기존 오늘 단락 1곳", "기존 장부의 필수어"):
            self.assertIn(needle, problems)


class Menus(unittest.TestCase):
    def test_menus_are_disjoint_and_in_the_assigned_category(self):
        pool = pool_of(60)
        cats = A.plan_categories(60, OLD)
        menus = A.build_menus(pool, cats, 4)
        by = {x["id"]: x for x in pool}
        flat = [i for m in menus for i in m]
        self.assertEqual(len(flat), len(set(flat)))
        for c, m in zip(cats, menus):
            self.assertEqual({by[i]["category"] for i in m}, {c})
            self.assertEqual(len(m), 4)

    def test_a_pool_that_is_too_small_is_refused(self):
        with self.assertRaises(ValueError):
            A.build_menus(pool_of(1), ["직장·일", "직장·일"], 4)


class Choice(unittest.TestCase):
    def setUp(self):
        self.pool = pool_of(2)
        self.by = {x["id"]: x for x in self.pool}
        self.menu = ["s0000", "s0001"]

    def test_a_choice_from_the_menu_with_its_words_passes(self):
        w = self.by["s0000"]["words"]
        text = f"{w[0]} 보이는 곳에서 {w[1]} 를 만집니다. 시인은 말합니다. 끝입니다."
        self.assertEqual(A.check_choice(self.menu, "s0000", text, self.by), [])

    def test_choices_outside_the_menu_or_without_words_or_with_foreign_words_are_found(self):
        w = self.by["s0000"]["words"]
        other = self.by["s0001"]["words"][0]
        ok = f"{w[0]} 보이는 곳에서 {w[1]} 를 만집니다. 시인은 말합니다."
        self.assertIn("메뉴", A.check_choice(self.menu, "s0100", ok, self.by)[0])
        self.assertTrue(any("필수어" in p for p in A.check_choice(self.menu, "s0000", "아무 말도 없는 글입니다. 둘째입니다.", self.by)))
        self.assertTrue(any("섞였습니다" in p for p in A.check_choice(self.menu, "s0000", ok + f" 그때 {other} 가 떠오릅니다.", self.by)))


if __name__ == "__main__":
    unittest.main()
