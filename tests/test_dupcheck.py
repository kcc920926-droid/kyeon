"""중복 점검기 시험: python -m unittest tests.test_dupcheck -v   (tkinter 없이도 돈다)

장면이 겹쳤는지는 글자 통계로 잡히지 않는다는 실험 결과(tools/dupcheck.py 머리말)에 따라, 장면 필수어 검사가 본체이고
말뭉치 검사(반복 구절, 복붙, 분포)는 보조다. 둘 다 시험한다."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import dupcheck as D  # noqa: E402


def filler(n, seed=7):
    """서로 무관한 80자 넘는 단락 n개(음절을 무작위로 이어 붙인 글)"""
    import random
    rng = random.Random(seed)
    syl = "가나다라마바사아자차카타파하거너더러머버서어저처커터퍼허고노도로모보소오조초코토포호"
    return [" ".join("".join(rng.choice(syl) for _ in range(rng.randint(2, 4))) for _ in range(rng.randint(22, 28))) + "." for _ in range(n)]


def plan_of(texts):
    return {"days": [{"day": d, "blocks": [{"label": "오늘", "text": t}]} for d, t in texts.items()]}


LEDGER = {"scenes": {
    "1": {"name": "새벽 열차의 터널", "category": "이동·교통", "words": ["터널", "차창"], "link": "빛이 들어오는 자리"},
    "2": {"name": "상가 교습소의 불 꺼진 창", "category": "상가·서비스", "words": ["교습소", "수강생"], "link": "떠난 장막"},
    "3": {"name": "병사의 달력", "category": "직장·일", "words": ["전역", "내무반"], "link": "날수를 셈"},
}}


class Phrases(unittest.TestCase):
    def test_a_phrase_in_too_many_days_is_found_and_allowed_ones_are_not(self):
        items = [(d, f"그 일이 있고 나서 사람들은 해고 통보를 받은 날을 오래 기억했습니다 {d}") for d in range(1, 7)]
        found = D.repeated_phrases(items, max_df=4)
        self.assertTrue(any("해고 통보를 받은 날" in g for g, _ds in found))
        self.assertEqual(D.repeated_phrases(items[:4], max_df=4), [])
        same = [(d, "표제에 따르면 다윗의 시이며 노래입니다 오늘") for d in range(1, 9)]
        self.assertEqual(D.repeated_phrases(same, max_df=4), [])   # 시편 표제 설명은 되풀이해도 된다


class Copies(unittest.TestCase):
    base = "타작마당에서 곡식을 공중에 던져 올리면 무거운 알곡은 남고 가벼운 겨는 바람에 흩어졌습니다 시편 첫 노래는 악인을 바로 그 겨에 견줍니다 그 겨는 한 줌의 바람에도 흔적 없이 사라지는 것으로 그려집니다"

    def test_a_pasted_paragraph_is_flagged_and_unrelated_ones_are_not(self):
        texts = {i: t for i, t in enumerate(filler(60))}
        texts[1000] = self.base
        texts[1001] = self.base.replace("시편 첫 노래는", "이 노래는")
        flagged = D.near_copies(texts)
        self.assertEqual({(k, j) for _s, k, j in flagged}, {(1000, 1001), (1001, 1000)})

    def test_very_short_blocks_are_skipped(self):
        texts = {1: "구하라 찾으라 두드리라는 요령으로 읽기 쉽습니다", 2: "구하라 찾으라 두드리라는 약속으로 읽기 쉽습니다"}
        self.assertEqual(D.near_copies(texts), [])


class Distribution(unittest.TestCase):
    def test_a_word_that_opens_too_many_paragraphs_is_reported(self):
        texts = {d: f"오래 쓴 물건 {d}개를 두고 사람들은 말합니다. 시인은 노래합니다. 끝입니다." for d in range(1, 61)}
        problems = D.distribution(texts)["problems"]
        self.assertTrue(any("첫 어절 '오래'" in p for p in problems))
        self.assertTrue(any("둘째 문장의 첫 어절 '시인은'" in p for p in problems))

    def test_a_varied_set_passes(self):
        heads = ["강", "시장", "병원", "버스", "겨울", "밭", "교실", "골목", "공장", "부엌"]
        tails = ["가에서", "앞에서", "길에서", "문에서", "옆에서", "안에서", "끝에서", "한켠에서", "위에서", "밑에서"]
        subjects = ["시인은", "그는", "예수님은", "바울은", "본문은", "이 노래는", "사람들은", "저자는", "그들은", "선지자는"]
        ends = ["끝납니다", "남습니다", "닿습니다", "열립니다", "닫힙니다", "흐릅니다", "오릅니다", "깊습니다", "멈춥니다", "쌓입니다",
                "그칩니다", "번집니다", "잠깁니다", "퍼집니다", "굳습니다", "풀립니다", "젖습니다", "마릅니다", "트입니다", "스칩니다"]
        texts = {}
        for d in range(100):
            texts[d] = f"{heads[d % 10]}{tails[d // 10]} 사람이 서 있습니다. {subjects[(d * 3) % 10]} 말합니다. 하루가 {ends[d % 20]}."
        self.assertEqual(D.distribution(texts)["problems"], [])


class Pairs(unittest.TestCase):
    def test_pairs_that_share_two_rare_words_in_the_first_sentence_are_listed(self):
        firsts = {1: "새벽 열차가 긴 터널을 지나자 차창이 환해졌습니다", 2: "아침 열차가 터널 끝에서 차창 가득 빛을 받았습니다",
                  3: "시장 골목에서 국밥집 할머니가 손을 흔들었습니다", 4: "공원 벤치에서 아이가 연을 날렸습니다"}
        pairs = D.scene_pairs(firsts, max_df=3)
        self.assertEqual([(a, b) for a, b, _w in pairs], [(1, 2)])


class Ledger(unittest.TestCase):
    def test_a_good_ledger_passes_its_shape_check(self):
        self.assertEqual(D.ledger_shape_problems(LEDGER), [])

    def test_shape_problems(self):
        bad = json.loads(json.dumps(LEDGER))
        bad["scenes"]["2"]["words"] = ["터널", "교습소"]            # 터널은 1일의 필수어
        bad["scenes"]["3"]["name"] = "새벽 열차의 터널"            # 이름이 1일과 같다
        bad["scenes"]["3"]["category"] = "없는 범주"
        bad["scenes"]["1"]["link"] = ""
        problems = "\n".join(D.ledger_shape_problems(bad))
        for needle in ("'터널' 가 1일과 2일", "이름 '새벽 열차의 터널'", "범주 '없는 범주'", "'link' 가 비었습니다"):
            self.assertIn(needle, problems)

    def test_words_already_used_elsewhere_are_not_exclusive(self):
        existing = {10: "예전에 쓴 글에도 터널 이야기가 있습니다", 11: "관계 없는 글입니다"}
        problems = D.ledger_shape_problems(LEDGER, existing)
        self.assertTrue(any("'터널'" in p and "10" in p for p in problems))

    def test_a_scene_text_must_use_its_own_words_and_nobody_elses(self):
        ok = {1: "새벽 열차가 긴 터널을 빠져나오자 차창 밖이 환해집니다. 그 빛이 이어집니다.",
              2: "상가 이층 교습소의 수강생이 하나둘 줄어 불이 꺼졌습니다.",
              3: "병사가 전역 날짜를 수첩에 적고 내무반 불을 끕니다."}
        self.assertEqual(D.scene_problems(LEDGER, ok), [])
        wrong = dict(ok)
        wrong[1] = "새벽에 길을 나선 사람이 하늘을 올려다봅니다. 별이 많습니다."   # 자기 필수어 없음
        wrong[3] = "병사가 전역 날짜를 적고 내무반 불을 끕니다. 교습소 앞을 지나던 일이 떠오릅니다."   # 2일의 필수어
        problems = "\n".join(D.scene_problems(LEDGER, wrong))
        self.assertIn("1일: 배정된 장면", problems)
        self.assertIn("3일: 2일의 필수어 '교습소'", problems)

    def test_the_scene_word_must_be_in_the_first_two_sentences(self):
        late = {1: "새벽 길이 조용합니다. 사람들이 걷습니다. 터널과 차창이 그제야 나옵니다.", 2: "교습소 수강생.", 3: "전역 내무반."}
        self.assertTrue(any("1일: 배정된 장면" in p for p in D.scene_problems(LEDGER, late)))


class SceneNames(unittest.TestCase):
    NAMES = {"1": "병원 대기실에서 검사 결과를 기다리는 가족 곁에 앉은 사람",
             "2": "병원 대기실에서 검사 결과를 기다리는 시간",
             "3": "새벽 열차가 긴 터널을 빠져나오는 순간",
             "4": "편의점 야간 근무 중 손님이 뜸한 새벽"}

    def test_same_scene_in_different_words_is_found_inside_one_set(self):
        pairs = D.similar_names(self.NAMES)
        self.assertEqual([(a, b) for _j, a, b in pairs], [("1", "2")])
        self.assertGreater(pairs[0][0], 0.5)

    def test_each_pair_is_reported_once_and_in_order_of_similarity(self):
        names = dict(self.NAMES, **{"5": "병원 대기실에서 검사 결과를 기다리는 저녁"})
        pairs = D.similar_names(names, min_jaccard=0.3)
        self.assertEqual(len({(a, b) for _j, a, b in pairs}), len(pairs))
        self.assertEqual([j for j, _a, _b in pairs], sorted((j for j, _a, _b in pairs), reverse=True))
        self.assertTrue(all(a < b for _j, a, b in pairs))

    def test_comparing_two_sets_does_not_pair_inside_either_set(self):
        old = {"10": "병원 대기실에서 검사 결과를 기다리는 시간", "11": "병원 대기실에서 검사 결과를 기다리는 저녁"}
        new = {"n1": "병원 대기실에서 검사 결과를 기다리는 아침", "n2": "새벽 열차가 긴 터널을 빠져나오는 순간"}
        found = {(a, b) for _j, a, b in D.similar_names(new, old)}
        self.assertEqual(found, {("n1", "10"), ("n1", "11")})

    def test_different_scenes_are_not_flagged(self):
        self.assertEqual(D.similar_names({"3": self.NAMES["3"], "4": self.NAMES["4"]}), [])


class Windows(unittest.TestCase):
    def ledger(self, cats):
        return {"scenes": {str(i + 1): {"name": f"장면{i}", "category": c, "words": ["가가", "나나"], "link": "x"} for i, c in enumerate(cats)}}

    def test_a_category_that_crowds_a_window_is_reported(self):
        cats = ["가정·육아"] * 3 + ["직장·일", "학교·청년", "의료·건강", "이동·교통", "돈·살림", "이웃·관계", "농어촌·자연"]
        problems = D.window_problems(self.ledger(cats), list(range(1, 11)), share=1.0)
        self.assertTrue(any("7일 안에 범주 '가정·육아' 가 3번" in p for p in problems))

    def test_a_varied_order_passes_and_the_share_cap_works(self):
        cats = [D.CATEGORIES[i % 16] for i in range(64)]
        self.assertEqual(D.window_problems(self.ledger(cats), list(range(1, 65))), [])
        crowded = ["가정·육아" if i % 4 == 0 else D.CATEGORIES[1 + i % 15] for i in range(64)]
        self.assertTrue(any("전체의" in p for p in D.window_problems(self.ledger(crowded), list(range(1, 65)))))

    def test_routes_are_checked_in_their_own_order(self):
        cats = [D.CATEGORIES[i % 16] for i in range(40)]
        ledger = self.ledger(cats)
        good = {"전체": list(range(1, 41))}
        self.assertEqual(D.route_problems(ledger, good), [])
        # 같은 범주끼리 모인 길: 1, 17, 33(모두 같은 범주), 2, 18, 34 …
        bad = {"테마": [1, 17, 33, 2, 18, 34, 3, 19, 35, 4, 20, 36]}
        self.assertTrue(D.route_problems(ledger, bad))


class Candidate(unittest.TestCase):
    def test_new_blocks_are_compared_with_the_whole_plan(self):
        syl = "가나다라마바사아자차카타파하거너더러머버서어저처커터퍼허"
        old = {d: f"{syl[d % 26]}{syl[(d * 7) % 26]}{syl[(d * 3 + 1) % 26]} 이야기 {d}번입니다. {syl[(d * 5) % 26]}{syl[(d * 11) % 26]}은 저마다의 하루를 살았고 저녁이면 모여 앉아 {syl[(d * 13) % 26]}{syl[d % 26]}의 이야기를 들었습니다 {d * 17}. 저녁이 되도록 이야기는 끝나지 않았고 사람들은 불을 피워 놓고 밤이 깊도록 앉아 있었습니다."
               for d in range(1, 40)}
        plan = plan_of(old)
        fresh = [{"day": 100, "text": "전혀 다른 이야기입니다. 터널을 빠져나온 열차의 차창이 환해지는 순간을 사람들이 말없이 바라보았습니다."}]
        self.assertEqual(D.candidate_problems(plan, fresh, LEDGER | {"scenes": {"100": LEDGER["scenes"]["1"]}}), [])
        copy = [{"day": 100, "text": old[3]}]
        self.assertTrue(any("거의 같은 글" in p for p in D.candidate_problems(plan, copy)))

    def test_candidate_with_a_foreign_scene_word_is_reported(self):
        plan = plan_of({1: "평범한 옛 글입니다. 오래된 이야기를 나눕니다."})
        ledger = {"scenes": {"100": LEDGER["scenes"]["1"], "101": LEDGER["scenes"]["2"]}}
        cand = [{"day": 100, "text": "터널을 지나는 열차 안에서 차창을 봅니다. 교습소가 떠오릅니다."}]
        self.assertTrue(any("101일의 필수어 '교습소'" in p for p in D.candidate_problems(plan, cand, ledger)))


class RealPlan(unittest.TestCase):
    """지금 plan.json 은 점검기의 기준을 통과한다(더 나빠지지 않게 지키는 시험)."""

    def test_current_plan_passes_the_corpus_gate(self):
        plan = json.loads((ROOT / "data" / "plan.json").read_text(encoding="utf-8"))
        self.assertEqual(D.corpus_problems(plan), [])


if __name__ == "__main__":
    unittest.main()
