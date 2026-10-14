"""장면 주제 태그와 메뉴 배정 시험: python -m unittest tests.test_themes -v   (tkinter, kiwipiepy 없이 돈다)"""
import sys
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import assign as A  # noqa: E402
import dupcheck as D  # noqa: E402
import themes as T  # noqa: E402


def scene(cat, theme):
    return {"category": cat, "theme": theme}


class Window(unittest.TestCase):
    def test_four_of_one_theme_within_sixty_days_is_found(self):
        s = {"1200": scene("공공·제도", "재판과 법"), "1210": scene("공공·제도", "재판과 법"), "1230": scene("공공·제도", "재판과 법"),
             "1240": scene("공공·제도", "재판과 법")}
        out = T.window_problems(s)
        self.assertEqual(len(out), 1)
        self.assertIn("1200일부터", out[0])

    def test_three_are_fine_and_a_gap_of_sixty_days_resets_the_count(self):
        s = {"1200": scene("공공·제도", "재판과 법"), "1210": scene("공공·제도", "재판과 법"), "1220": scene("공공·제도", "재판과 법")}
        self.assertEqual(T.window_problems(s), [])
        s["1259"] = scene("공공·제도", "재판과 법")          # 1200 과 59일 차이: 아직 한 창 안에 넷
        self.assertEqual(len(T.window_problems(s)), 1)
        s["1259"] = scene("공공·제도", "재판과 법")
        s2 = {"1200": s["1200"], "1210": s["1210"], "1220": s["1220"], "1260": scene("공공·제도", "재판과 법")}
        self.assertEqual(T.window_problems(s2), [])          # 1200 과 1260 은 60일 차이라 어느 창에도 넷이 없다

    def test_other_and_untagged_and_other_categories_are_not_counted(self):
        s = {str(1200 + i): scene("공공·제도", T.OTHER) for i in range(5)}
        s.update({str(1300 + i): {"category": "공공·제도"} for i in range(5)})
        s.update({str(1400 + i): scene("의례·행사", "장례") for i in range(3)})
        s["1401"] = scene("노년·돌봄", "장례")                 # 같은 이름의 주제라도 범주가 다르면 따로 센다
        self.assertEqual(T.window_problems(s), [])

    def test_a_cluster_is_reported_once(self):
        s = {str(1200 + i): scene("공공·제도", "재판과 법") for i in range(8)}
        self.assertEqual(len(T.window_problems(s)), 1)

    def test_every_category_has_its_own_theme_list_ending_in_other(self):
        for c in D.CATEGORIES:
            if c == "직장·일":
                continue
            self.assertIn(c, T.THEMES)
            self.assertEqual(T.THEMES[c][-1], T.OTHER)
            self.assertEqual(len(T.THEMES[c]), len(set(T.THEMES[c])))

    def test_a_theme_must_belong_to_the_category(self):
        self.assertEqual(T.problems_of({"id": "a", "category": "공공·제도", "theme": "재판과 법"}), [])
        self.assertEqual(T.problems_of({"id": "a", "category": "공공·제도"}), [])
        self.assertEqual(len(T.problems_of({"id": "a", "category": "공공·제도", "theme": "장례"})), 1)


def pool_with_themes(per_theme=8, category="의례·행사"):
    pool = []
    for ti, th in enumerate(T.THEMES[category][:-1]):
        for j in range(per_theme):
            pool.append({"id": f"{ti:02d}-{j}", "name": f"장면 {ti} {j}", "category": category, "words": ["가가", "나나"], "theme": th})
    return pool


class Menus(unittest.TestCase):
    def test_a_menu_never_repeats_a_theme_when_the_pool_has_enough(self):
        pool = pool_with_themes()
        by = {x["id"]: x for x in pool}
        menus = A.build_menus(pool, ["의례·행사"] * 12, 4)
        for m in menus:
            self.assertEqual(len({by[i]["theme"] for i in m}), 4)

    def test_menus_are_the_same_every_time_and_follow_the_seed(self):
        pool = pool_with_themes()
        cats = ["의례·행사"] * 10
        self.assertEqual(A.build_menus(pool, cats, 4), A.build_menus(pool, cats, 4))
        self.assertNotEqual(A.build_menus(pool, cats, 4, seed=1), A.build_menus(pool, cats, 4, seed=2))

    def test_the_pool_order_does_not_decide_which_neighbours_share_a_band(self):
        # 풀이 주제 띠로 정렬돼 있어도(첫 해의 원인) 이웃한 날의 메뉴가 같은 띠에 몰리지 않는다
        pool = pool_with_themes(per_theme=10)
        by = {x["id"]: x for x in pool}
        menus = A.build_menus(pool, ["의례·행사"] * 12, 4)
        total = Counter()
        for m in menus[:6]:
            total.update(by[i]["theme"] for i in m)
        self.assertLessEqual(max(total.values()), 3)

    def test_a_theme_that_just_appeared_is_used_less_in_the_next_menus(self):
        pool = pool_with_themes(per_theme=12)
        by = {x["id"]: x for x in pool}
        menus = A.build_menus(pool, ["의례·행사"] * 5, 4)
        first = {by[i]["theme"] for i in menus[0]}
        second = [by[i]["theme"] for i in menus[1]]
        self.assertTrue(len(first & set(second)) < 4)

    def test_a_pool_without_themes_still_works(self):
        pool = [{"id": f"x{i}", "name": f"장면 {i}", "category": "의례·행사", "words": ["가가", "나나"]} for i in range(12)]
        menus = A.build_menus(pool, ["의례·행사"] * 3, 4)
        flat = [i for m in menus for i in m]
        self.assertEqual(len(flat), len(set(flat)))

    def test_pool_check_refuses_a_theme_of_another_category(self):
        bad = [{"id": "a1", "name": "서로 다른 장면 하나", "category": "공공·제도", "words": ["가가", "나나"], "theme": "장례"}]
        self.assertTrue(any("목록에 없습니다" in e for e in A.pool_problems(bad)))


if __name__ == "__main__":
    unittest.main()
