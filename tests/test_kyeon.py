"""켠 테스트: python -m unittest discover -s tests -v   (Windows, tkinter 필요)"""
import json
import os
import re
import sys
import tempfile
import unittest
import uuid
import winreg
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["KYEON_NO_UPDATE"] = "1"  # 위젯 시험에서 새 버전 확인(네트워크)이 돌지 않게
import kyeon as K  # noqa: E402

FORMATS = {  # 형식 번호: 블록 라벨
    1: ["그 당시", "오늘"],
    2: ["흔한 읽기", "당시의 뜻", "오늘"],
    3: ["한 단어: {term}", "오늘"],
    4: ["그 자리에서", "오늘"],
    5: ["큰 이야기 속에서", "오늘"],
}


class DayIndex(unittest.TestCase):
    def test_cycle(self):
        s = date(2026, 1, 1)
        self.assertEqual(K.day_index(s, s, 1000), 0)
        self.assertEqual(K.day_index(s, s + timedelta(999), 1000), 999)
        self.assertEqual(K.day_index(s, s + timedelta(1000), 1000), 0)
        self.assertEqual(K.day_index(s, s - timedelta(3), 1000), 0)


class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_roundtrip(self):
        s = K.State(self.dir)
        self.assertIsNone(s.start_date)
        s.start_date = date(2026, 3, 1)
        s.dismissed_date = date(2026, 3, 2)
        s2 = K.State(self.dir)
        self.assertEqual((s2.start_date, s2.dismissed_date), (date(2026, 3, 1), date(2026, 3, 2)))
        s2.dismissed_date = None
        self.assertIsNone(K.State(self.dir).dismissed_date)

    def test_corrupt_file_is_ignored(self):
        (self.dir / "state.json").write_text("{not json", encoding="utf-8")
        self.assertIsNone(K.State(self.dir).start_date)

    def test_signal_is_consumed_once(self):
        s = K.State(self.dir)
        self.assertIsNone(s.take_signal())
        s.send("show")
        self.assertEqual(s.take_signal(), "show")
        self.assertIsNone(s.take_signal())


class AutostartTests(unittest.TestCase):
    def test_set_get_remove_in_temp_key(self):
        key = rf"Software\KyeonTest-{uuid.uuid4().hex}"
        try:
            self.assertIsNone(K.autostart_get("x", key))
            K.autostart_set("cmd", "x", key)
            self.assertEqual(K.autostart_get("x", key), "cmd")
            self.assertTrue(K.autostart_remove("x", key))
            self.assertFalse(K.autostart_remove("x", key))
        finally:
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
            except OSError:
                pass

    def test_command_points_at_this_script(self):
        cmd = K.autostart_command()
        self.assertIn("kyeon.py", cmd)
        self.assertTrue(cmd.endswith("--startup"))


class PlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = K.load_plan()
        cls.days = cls.plan["days"]

    def test_size_and_numbers(self):
        # 처음 1000일은 plan.json, 그 뒤 날은 data/plan-<첫 일차>.json 에서 이어 붙는다. 번호는 빈틈없이 이어져야 한다
        self.assertGreaterEqual(len(self.days), 1000)
        self.assertEqual([d["day"] for d in self.days], list(range(1, len(self.days) + 1)))

    def test_every_day_is_complete(self):
        self.assertEqual([d["day"] for d in self.days if not K.day_ok(d)], [])

    def test_blocks_match_format(self):
        for d in self.days:
            want = FORMATS[d["format"]]
            got = [b["label"] for b in d["blocks"]]
            self.assertEqual(len(got), len(want), d["day"])
            for g, w in zip(got, want):
                if "{term}" in w:
                    self.assertRegex(g, r"^한 단어: .{1,10}$", d["day"])
                else:
                    self.assertEqual(g, w, d["day"])

    def test_no_prayer_and_no_question_anywhere(self):
        """해설까지만 쓴다: 기도 블록과 질문은 어떤 날에도 없다."""
        for d in self.days:
            self.assertNotIn("question", d, d["day"])
            self.assertNotIn("기도", [b["label"] for b in d["blocks"]], d["day"])
            self.assertTrue(all(b["text"].strip() for b in d["blocks"]), d["day"])
        self.assertEqual({d["format"] for d in self.days}, {1, 2, 3, 4, 5})
        self.assertTrue(all(d["blocks"][-1]["label"] == "오늘" for d in self.days))   # 날마다 마지막 단락은 '오늘'

    def test_refs_are_unique_and_text_is_clean(self):
        self.assertEqual([r for r, n in Counter(d["ref"] for d in self.days).items() if n > 1], [])
        for d in self.days:
            for c, v, t in d["verses"]:
                self.assertTrue(t.strip(), d["ref"])
                self.assertNotIn("침례", t)
                self.assertNotIn("&nbsp;", t)

    def test_composition(self):
        first = self.days[:1000]            # 처음 1000일의 짜임. 새로 붙는 날들(남은 성경)은 시편이 없고 복음서가 적다
        secs = Counter(d["section"] for d in first)
        self.assertEqual(secs["시편"], 225)
        self.assertEqual(secs["복음서"], 225)
        # 시편과 복음서가 번갈아 나온다(그 사이에 다른 책이 끼어도 시편 다음 복음서 순서는 유지)
        pg = [d["section"] for d in first if d["section"] in ("시편", "복음서")]
        self.assertEqual(pg[:6], ["시편", "복음서"] * 3)
        self.assertEqual(len({d["ref"].split()[0] for d in first}), 66)

    def test_parallels_are_lists_of_labels(self):
        for d in self.days:
            if "parallels" in d:           # 복음서 병행뿐 아니라 열왕기와 역대기 같은 병행도 있을 수 있다
                self.assertTrue(isinstance(d["parallels"], list) and d["parallels"])
                self.assertTrue(all(isinstance(p, str) and p and p != d["ref"] for p in d["parallels"]))
                if d["day"] <= 1000:
                    self.assertEqual(d["section"], "복음서")

    def test_load_plan_rejects_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "plan.json"
            p.write_text(json.dumps({"days": [{"day": 1}, {"day": 3}]}), encoding="utf-8")
            with self.assertRaises(ValueError):
                K.load_plan(p)


class PlanParts(unittest.TestCase):
    """plan.json 뒤에 plan-<첫 일차>.json 을 이어 붙여 읽는다."""

    def write(self, tmp, name, days, **head):
        (Path(tmp) / name).write_text(json.dumps({**head, "days": [{"day": d} for d in days]}), encoding="utf-8")

    def test_parts_are_ordered_by_the_number_in_the_name_not_alphabetically(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, "plan.json", [1, 2], routes={"era": []})
            self.write(tmp, "plan-10.json", [10, 11])          # 사전순으로는 plan-10 이 plan-3 보다 앞이다
            self.write(tmp, "plan-3.json", list(range(3, 10)))
            self.write(tmp, "plan-bad.json", [99])             # 모양이 다른 이름은 읽지 않는다
            self.write(tmp, "plan-4.json.bak", [99])
            plan = K.load_plan(Path(tmp) / "plan.json")
            self.assertEqual([d["day"] for d in plan["days"]], list(range(1, 12)))
            self.assertEqual([p.name for p in K.plan_part_files(Path(tmp) / "plan.json")], ["plan-3.json", "plan-10.json"])

    def test_numbers_must_run_on_across_the_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, "plan.json", [1, 2])
            self.write(tmp, "plan-3.json", [3, 4])
            self.assertEqual([d["day"] for d in K.load_plan(Path(tmp) / "plan.json")["days"]], [1, 2, 3, 4])
            self.write(tmp, "plan-5.json", [6])                 # 5일이 빠졌다
            with self.assertRaises(ValueError):
                K.load_plan(Path(tmp) / "plan.json")

    def test_header_comes_from_plan_json_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, "plan.json", [1], translation="개역한글", routes={"era": [{"id": "a"}]})
            self.write(tmp, "plan-2.json", [2], translation="다른 것", routes={"era": [{"id": "b"}]})
            plan = K.load_plan(Path(tmp) / "plan.json")
            self.assertEqual((plan["translation"], plan["routes"]["era"][0]["id"]), ("개역한글", "a"))

    def test_a_part_with_the_wrong_shape_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, "plan.json", [1])
            (Path(tmp) / "plan-2.json").write_text(json.dumps([{"day": 2}]), encoding="utf-8")
            with self.assertRaises(ValueError):
                K.load_plan(Path(tmp) / "plan.json")

    def test_explicit_parts_replace_the_folder_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, "plan.json", [1])
            self.write(tmp, "plan-2.json", [2])
            self.assertEqual([d["day"] for d in K.load_plan(Path(tmp) / "plan.json", [])["days"]], [1])

    def test_routes_follow_the_day_order_across_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = {"era": [{"id": "a", "name": "가"}]}
            (Path(tmp) / "plan.json").write_text(json.dumps({"routes": first, "days": [{"day": 1, "era": "a"}]}), encoding="utf-8")
            (Path(tmp) / "plan-2.json").write_text(json.dumps({"days": [{"day": 2, "era": "a"}, {"day": 3}]}), encoding="utf-8")
            routes = K.build_routes(K.load_plan(Path(tmp) / "plan.json"))
            self.assertEqual({r["id"]: r["idxs"] for r in routes}["era:a"], [0, 1])
            self.assertEqual(routes[0]["idxs"], [0, 1, 2])


class WidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["KYEON_THEME"] = "light"
        cls.plan = K.load_plan()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = K.State(Path(self.tmp.name))
        self.clock = [date(2026, 3, 1)]
        self.widgets = []

    def tearDown(self):
        for w in self.widgets:
            try:
                w.quit()
            except Exception:  # noqa: BLE001
                pass
        self.tmp.cleanup()

    def make(self, **kw):
        w = K.Widget(self.plan, self.state, today_fn=lambda: self.clock[0], **kw)
        self.widgets.append(w)
        return w

    def test_day_flow_dismiss_and_midnight(self):
        w = self.make()
        w.start("manual")
        self.assertTrue(w.visible)
        self.assertEqual((w.idx, self.state.start_date), (0, date(2026, 3, 1)))
        w.dismiss()
        self.assertFalse(w.visible)
        self.assertEqual(self.state.dismissed_date, date(2026, 3, 1))
        self.clock[0] = date(2026, 3, 2)  # 자정을 넘김
        w.tick()
        self.assertTrue(w.visible)
        self.assertEqual(w.idx, 1)

    def test_startup_stays_quiet_when_dismissed_today(self):
        w = self.make()
        w.start("manual")
        w.dismiss()
        w.quit()
        w2 = self.make()
        w2.start("startup")
        self.assertFalse(w2.visible)
        self.state.send("show")
        w2.tick()
        self.assertTrue(w2.visible)

    def test_quit_signal(self):
        w = self.make()
        w.start("manual")
        self.state.send("quit")
        w.tick()
        with self.assertRaises(Exception):
            w.root.winfo_exists()

    def test_preview_does_not_touch_state(self):
        w = self.make(preview_day=500)
        w.start("manual")
        self.assertEqual(w.idx, 499)
        self.assertIsNone(self.state.start_date)

    def test_cycle_after_the_whole_plan(self):
        self.state.start_date = date(2026, 3, 1)
        self.clock[0] = date(2026, 3, 1) + timedelta(days=len(self.plan["days"]))
        w = self.make()
        w.start("manual")
        self.assertEqual(w.idx, 0)

    def test_every_day_renders_in_one_fixed_frame(self):
        """모든 날이 같은 크기의 창에 담긴다. 길이가 달라도 창 모양은 늘 같고, 넘치는 건 스크롤로 읽는다."""
        w = self.make(preview_day=1)
        w.show()
        w.root.update()
        sizes = set()
        for i in range(len(w.days)):
            w.idx = i
            w._layout()
            sizes.add(w._size)
        self.assertEqual(len(sizes), 1, sizes)
        width, height = next(iter(sizes))
        _l, top, _r, bottom = K.work_area()
        avail = (bottom - top) - 2 * int(16 * w.sc)
        self.assertLessEqual(height, avail)
        if height < avail:  # 화면이 충분히 높으면 정확히 의도한 비율(낮은 화면은 폭을 줄여 맞춘다)
            self.assertAlmostEqual(height / width, K.ASPECT, delta=0.01)


class ReciteData(unittest.TestCase):
    """암송용 가림 정보(lv): 글자마다 0(공백·부호) 1(핵심 단어) 2(뜻이 중요한 명사·형용사) 3(그 밖의 내용어) 4(조사·어미, 안 가림)."""

    @classmethod
    def setUpClass(cls):
        cls.days = K.load_plan()["days"]

    # 개역한글 인쇄본에서 앞 구절에 합쳐진 구절 자리의 표기: '(앞절과 동일)', '12절과 상동', '상동'
    MERGED = re.compile(r"[(\[]?\s*(?:\d+절과 (?:상동|같음)|앞절과 동일|상동)\s*[)\]]?")

    def test_shape(self):
        for d in self.days:
            self.assertEqual(len(d["lv"]), len(d["verses"]), d["day"])
            for s, (_c, _v, t) in zip(d["lv"], d["verses"]):
                self.assertEqual(len(s), len(t), d["ref"])
                self.assertTrue(set(s) <= set("01234"), d["ref"])
                if self.MERGED.fullmatch(t):
                    self.assertEqual(set(s), {"0"}, d["ref"])  # 합쳐진 구절 표기는 가리지 않는다
                    continue
                for ch, code in zip(t, s):
                    if ch == " ":
                        self.assertEqual(code, "0")
                    elif "가" <= ch <= "힣":
                        self.assertNotEqual(code, "0", (d["ref"], ch))

    def test_every_verse_has_a_keyword_and_levels_grow_gently(self):
        n = {k: 0 for k in "1234"}
        for d in self.days:
            for s, (_c, _v, t) in zip(d["lv"], d["verses"]):
                if self.MERGED.fullmatch(t):
                    continue
                self.assertIn("1", s, d["ref"])
                for k in n:
                    n[k] += s.count(k)
        tot = sum(n.values())
        lv1, lv2, lv3 = n["1"] / tot, (n["1"] + n["2"]) / tot, (n["1"] + n["2"] + n["3"]) / tot
        self.assertLess(lv1, 0.10)                      # 1단계는 가볍게(구절마다 핵심 단어 1~3개)
        self.assertTrue(0.15 < lv2 < 0.35, lv2)         # 2단계는 중요한 명사·형용사까지만: 글자의 4분의 1 안팎
        self.assertTrue(0.50 < lv3 < 0.70, lv3)         # 3단계는 뜻이 있는 말 전부(예전 2단계). 조사와 어미는 남는다
        self.assertGreater(n["4"] / tot, 0.25)          # 조사·어미는 어느 단계에서도 보인다

    def test_old_particle_level_is_gone(self):
        """예전 3단계(모든 글자)는 없어졌다: 3단계에서도 코드 4(조사·어미)는 가리지 않는다."""
        self.assertEqual(sorted(K.RECITE_LEVELS), [1, 2, 3])
        self.assertIn("중요한", K.RECITE_LEVELS[2])


class _Ev:
    def __init__(self, x, y):
        self.x, self.y = x, y


class ReciteWidget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["KYEON_THEME"] = "light"
        cls.plan = K.load_plan()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = K.State(Path(self.tmp.name))
        self.widgets = []

    def tearDown(self):
        for w in self.widgets:
            try:
                w.quit()
            except Exception:  # noqa: BLE001
                pass
        self.tmp.cleanup()

    def make(self, plan=None, **kw):
        w = K.Widget(plan or self.plan, self.state, today_fn=lambda: date(2026, 3, 1), **kw)
        self.widgets.append(w)
        return w

    @staticmethod
    def hidden_chars(w):
        t = w.text
        r = t.tag_ranges("hid")
        return sum(len(t.get(a, b)) for a, b in zip(r[::2], r[1::2]))

    def expected_hidden(self, w, level):
        d = w.days[w.idx]
        return sum(1 for s in d["lv"] for ch in s if ch in "123" and int(ch) <= level)

    def test_levels_hide_more_and_match_the_data(self):
        counts = []
        for level in (1, 2, 3):
            w = self.make(preview_day=3, recite=level)
            w.start("manual")
            self.assertEqual(self.hidden_chars(w), self.expected_hidden(w, level))
            counts.append(self.hidden_chars(w))
        self.assertLess(counts[0], counts[1])
        self.assertLess(counts[1], counts[2])

    def test_particles_stay_visible_at_every_level(self):
        for level in (1, 2, 3):
            w = self.make(preview_day=3, recite=level)
            w.start("manual")
            at = w.text.search("태초에", "1.0")
            self.assertTrue(at)
            self.assertIn("hid", w.text.tag_names(at), level)                     # 핵심 단어 '태초' 는 1단계부터 가려지고
            self.assertNotIn("hid", w.text.tag_names(f"{at}+2c"), level)          # 조사 '에' 는 3단계에서도 보인다

    def test_level_2_hides_important_nouns_and_level_3_hides_the_rest_of_the_content_words(self):
        w2, w3 = self.make(preview_day=3, recite=2), self.make(preview_day=3, recite=3)
        w2.start("manual")
        w3.start("manual")
        for w in (w2, w3):
            self.assertIn("hid", w.text.tag_names(w.text.search("말씀", "1.0")))   # 중요한 명사
        at2, at3 = w2.text.search("계시니라", "1.0"), w3.text.search("계시니라", "1.0")
        self.assertNotIn("hid", w2.text.tag_names(at2))   # 동사 '계시' 는 2단계에서 보이고
        self.assertIn("hid", w3.text.tag_names(at3))      # 3단계에서 가려진다

    def test_click_reveals_the_whole_word_and_rehide_restores(self):
        w = self.make(preview_day=3, recite=1)
        w.start("manual")
        before = self.hidden_chars(w)
        first = w.text.tag_ranges("hid")[0]
        w.root.update()
        x, y, wd, ht = w.text.bbox(first)
        self.assertEqual(w._reveal(_Ev(x + 2, y + ht // 2)), "break")
        self.assertLess(self.hidden_chars(w), before)
        self.assertTrue(w.text.tag_ranges("shown"))
        self.assertEqual(len(w.revealed), 1)
        w._rehide()
        self.assertEqual(self.hidden_chars(w), before)
        self.assertFalse(w.text.tag_ranges("shown"))

    def test_toggle_and_level_are_saved(self):
        w = self.make()
        w.start("manual")
        self.assertFalse(w.recite)
        w._toggle_recite()
        self.assertTrue(w.recite)
        w._set_level(3)
        s2 = K.State(Path(self.tmp.name))
        self.assertEqual((s2.recite, s2.recite_level), (True, 3))
        self.assertEqual(self.hidden_chars(w), self.expected_hidden(w, 3))
        w._toggle_recite()
        self.assertEqual(self.hidden_chars(w), 0)
        self.assertFalse(K.State(Path(self.tmp.name)).recite)

    def test_new_widget_restores_saved_mode(self):
        self.state.recite, self.state.recite_level = True, 2
        w = self.make()
        w.start("manual")
        self.assertEqual((w.recite, w.level), (True, 2))
        self.assertEqual(self.hidden_chars(w), self.expected_hidden(w, 2))

    def test_show_again_hides_everything_again(self):
        w = self.make(preview_day=3, recite=1)
        w.start("manual")
        w.revealed.add((0, 0))
        w.show()
        self.assertEqual(w.revealed, set())

    def test_preview_does_not_touch_saved_settings(self):
        w = self.make(preview_day=3, recite=2)
        w.start("manual")
        w._set_level(3)
        w._toggle_recite()
        self.assertEqual(K.State(Path(self.tmp.name)).data, {})

    def test_plan_without_lv_has_no_recite(self):
        old = {"days": [{"day": 1, "section": "시편", "ref": "시편 1편", "title": "t", "verses": [[1, 1, "가 나"]],
                         "explain": "e", "question": "q?"}]}
        w = self.make(plan=old)
        self.assertFalse(w.can_recite)
        w.start("manual")
        w._toggle_recite()
        self.assertFalse(w.recite)


class SettingsState(unittest.TestCase):
    def test_defaults_and_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = K.State(Path(tmp))
            self.assertEqual({k: s.get(k) for k in K.SETTING_DEFAULTS}, K.SETTING_DEFAULTS)
            s.set("skin", "excel")
            s.set("font", "large")
            s2 = K.State(Path(tmp))
            self.assertEqual((s2.get("skin"), s2.get("font")), ("excel", "large"))
            s2.data["skin"] = "fancy"      # 허용 범위 밖의 값은 기본값으로
            s2.data["recite_level"] = 9
            self.assertEqual((s2.get("skin"), s2.get("recite_level")), ("default", 1))
            with self.assertRaises(KeyError):
                s2.set("nope", 1)

    def test_skin_option_saves_without_opening_a_window(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, KYEON_STATE_DIR=tmp, PYTHONIOENCODING="utf-8")
            r = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "kyeon.py"), "--skin", "excel"],
                               env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(K.State(Path(tmp)).get("skin"), "excel")


class SkinAndSettings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["KYEON_THEME"] = "light"
        cls.plan = K.load_plan()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = K.State(Path(self.tmp.name))
        self.widgets = []

    def tearDown(self):
        for w in self.widgets:
            try:
                w.quit()
            except Exception:  # noqa: BLE001
                pass
        self.tmp.cleanup()

    def make(self, **kw):
        w = K.Widget(self.plan, self.state, today_fn=lambda: date(2026, 3, 1), **kw)
        self.widgets.append(w)
        return w

    def test_excel_skin_looks_like_a_sheet(self):
        w = self.make(preview_day=3, skin="excel")
        w.start("manual")
        w.root.update()
        self.assertEqual(w.skin, "excel")
        self.assertTrue(w.xl_menu.winfo_ismapped() and w.xl_formula.winfo_ismapped() and w.xl_tabs.winfo_ismapped())
        self.assertEqual(w.lbl_app.cget("text"), "통합 문서1 - 저장됨")
        self.assertEqual(w.root.title(), "켠")  # 창 제목은 그대로(창 찾기용)
        self.assertTrue(w.text.tag_ranges("row0") and w.text.tag_ranges("row1"))
        self.assertIn("\t", w.text.get("1.0", "end"))   # 번호 열 / 본문 열
        self.assertEqual(w._p, K.EXCEL)

    def test_default_skin_has_no_sheet_chrome(self):
        w = self.make(preview_day=3)
        w.start("manual")
        w.root.update()
        self.assertFalse(w.xl_menu.winfo_ismapped())
        self.assertEqual(w.lbl_app.cget("text"), "켠")
        self.assertNotIn("\t", w.text.get("1.0", "end"))

    def test_recite_hides_text_behind_the_stripes_in_excel_skin(self):
        w = self.make(preview_day=3, skin="excel", recite=3)
        w.start("manual")
        t = w.text
        hid = t.tag_ranges("hid")
        self.assertTrue(hid)
        names = t.tag_names()
        self.assertGreater(names.index("hid"), names.index("row1"))  # 가림 태그가 줄무늬보다 위에 있다

    def test_every_setting_applies_and_is_saved(self):
        w = self.make()
        w.start("manual")
        w.set_setting("skin", "excel")
        w.set_setting("font", "large")
        w.set_setting("corner", "tl")
        w.set_setting("topmost", False)
        w.set_setting("theme", "dark")
        s = K.State(Path(self.tmp.name))
        self.assertEqual({k: s.get(k) for k in ("skin", "font", "corner", "topmost", "theme")},
                         {"skin": "excel", "font": "large", "corner": "tl", "topmost": False, "theme": "dark"})
        self.assertEqual(w.W, 576)
        left, top, _r, _b = K.work_area()
        self.assertLess(w.root.winfo_x() - left, 2 * int(16 * w.sc) + 2)   # 왼쪽 위 모서리 근처
        self.assertLess(w.root.winfo_y() - top, 2 * int(16 * w.sc) + 2)
        self.assertFalse(bool(int(w.root.attributes("-topmost"))))
        self.assertEqual(w._p, K.EXCEL)  # 엑셀 스타일은 테마와 상관없이 밝게 고정
        w.set_setting("skin", "default")
        self.assertEqual(w._p, K.DARK)

    def test_font_size_changes_width_and_text(self):
        sizes = {}
        for font in ("small", "normal", "large"):
            self.state.set("font", font)
            w = self.make(preview_day=3) if False else K.Widget(self.plan, self.state, today_fn=lambda: date(2026, 3, 1))
            self.widgets.append(w)
            w.start("manual")
            sizes[font] = (w.W, w.f_body.cget("size"))
        self.assertLess(sizes["small"][0], sizes["normal"][0])
        self.assertLess(sizes["normal"][0], sizes["large"][0])
        self.assertLess(sizes["small"][1], sizes["large"][1])

    def test_settings_window_controls(self):
        w = self.make()
        w.start("manual")
        w.open_settings()
        win = w.settings_win
        self.assertTrue(win.alive())
        win._choose("skin", "excel")
        win._choose("recite", True)
        win._choose("recite_level", 2)
        win._choose("font", "small")
        s = K.State(Path(self.tmp.name))
        self.assertEqual((s.get("skin"), s.get("recite"), s.get("recite_level"), s.get("font")),
                         ("excel", True, 2, "small"))
        w.open_settings()  # 이미 열려 있으면 새로 만들지 않는다
        self.assertIs(w.settings_win, win)
        win.close()
        self.assertFalse(win.alive())

    def test_settings_window_shows_the_bible_text_credit(self):
        """개역한글판의 저작자 표시(성명표시권)는 설정 창 안에서 보여 준다."""
        w = self.make()
        w.start("manual")
        w.open_settings()
        win = w.settings_win
        self.assertEqual(win.lbl_credit.cget("text"), K.TEXT_CREDIT)
        for part in ("개역한글판", "대한성서공회", "1961"):
            self.assertIn(part, K.TEXT_CREDIT)
        win.top.update_idletasks()
        self.assertTrue(win.lbl_credit.grid_info(), "출처 줄이 창 안에 놓여 있어야 한다")
        self.assertGreater(win.lbl_credit.winfo_width(), 1)
        bottom = win.lbl_credit.winfo_rooty() + win.lbl_credit.winfo_height()
        self.assertLessEqual(bottom, win.top.winfo_rooty() + win.top.winfo_reqheight(), "출처 줄이 창 밖으로 잘리면 안 된다")
        win.close()

    def test_autostart_toggle_uses_the_registry_helpers(self):
        from unittest import mock
        w = self.make()
        w.start("manual")
        with mock.patch.object(K, "autostart_set") as aset, mock.patch.object(K, "autostart_remove") as arem, \
                mock.patch.object(K, "autostart_get", return_value="cmd"):
            self.assertTrue(w.autostart_on())
            self.assertTrue(w.set_autostart(True))
            aset.assert_called_once()
            self.assertTrue(w.set_autostart(False))
            arem.assert_called_once()
        with mock.patch.object(K, "autostart_set", side_effect=OSError):
            self.assertFalse(w.set_autostart(True))

    def test_preview_never_touches_the_registry(self):
        from unittest import mock
        w = self.make(preview_day=3)
        with mock.patch.object(K, "autostart_set") as aset:
            self.assertFalse(w.set_autostart(True))
            aset.assert_not_called()

    def test_jump_to_day_and_restart(self):
        w = self.make()
        w.start("manual")
        w.jump_to_day(250)
        self.assertEqual(w.current_day(), 250)
        self.assertEqual(self.state.start_date, date(2026, 3, 1) - timedelta(days=249))
        w.jump_to_day(5000)  # 범위를 넘으면 마지막 일차로
        self.assertEqual(w.current_day(), len(w.days))
        w.jump_to_day(1)
        self.assertEqual(w.current_day(), 1)

    def test_settings_window_validates_the_day_box(self):
        w = self.make()
        w.start("manual")
        w.open_settings()
        win = w.settings_win
        win.entry.delete(0, "end")
        win.entry.insert(0, "abc")
        win._jump()
        self.assertIn("숫자", win.lbl_msg.cget("text"))
        win.entry.delete(0, "end")
        win.entry.insert(0, "42")
        win._jump()
        self.assertEqual(w.current_day(), 42)

    def test_excel_skin_uses_the_same_frame_on_sample_days(self):
        w = self.make(preview_day=1, skin="excel")
        w.show()
        w.root.update()
        sizes = set()
        for i in range(0, len(w.days), 7):
            w.idx = i
            w._layout()
            sizes.add(w._size)
        self.assertEqual(len(sizes), 1, sizes)
        # 엑셀 스타일에서도 열 머리글(A·B)은 고정이고 본문 영역만 넘어간다
        w.root.update()
        self.assertLess(w.xl_cols.winfo_rooty(), w.scroller.frame.winfo_rooty())
        self.assertGreater(w.xl_tabs.winfo_rooty(), w.scroller.frame.winfo_rooty())


class _Wheel:
    def __init__(self, widget, delta):
        self.widget, self.delta = widget, delta


class ScrollAndProportion(unittest.TestCase):
    """창은 늘 정해진 비율로 열고, 긴 본문은 테마색의 스크롤바로 읽는다."""

    @classmethod
    def setUpClass(cls):
        os.environ["KYEON_THEME"] = "light"
        cls.plan = K.load_plan()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = K.State(Path(self.tmp.name))
        self.widgets = []

    def tearDown(self):
        for w in self.widgets:
            try:
                w.quit()
            except Exception:  # noqa: BLE001
                pass
        self.tmp.cleanup()

    def make(self, day, **kw):
        w = K.Widget(self.plan, self.state, today_fn=lambda: date(2026, 3, 1), preview_day=day, **kw)
        self.widgets.append(w)
        w.start("manual")
        w.root.update()
        return w

    def find_day(self, want_scrollable, limit=40):
        """스크롤이 필요한(또는 필요 없는) 날을 하나 찾는다."""
        w = self.make(1)
        for i in range(limit):
            w.idx = i
            w._layout()
            w._place(*w._size)
            w.root.update()
            if w.scroller.scrollable() == want_scrollable:
                return i + 1
        return None

    def test_window_opens_in_the_intended_proportion(self):
        w = self.make(3)
        width, height = w.root.winfo_width(), w.root.winfo_height()
        _l, top, _r, bottom = K.work_area()
        avail = (bottom - top) - 2 * int(16 * w.sc)
        self.assertLessEqual(height, avail)
        if height < avail:
            self.assertAlmostEqual(height / width, K.ASPECT, delta=0.01)
        self.assertEqual((width, height), w._size)

    def test_short_and_long_days_open_at_the_same_size(self):
        sizes = set()
        for day in (1, 3, 8, 10, 500, 1000):
            w = self.make(day)
            sizes.add((w.root.winfo_width(), w.root.winfo_height()))
        self.assertEqual(len(sizes), 1, sizes)

    def test_long_text_gets_a_scrollbar_and_short_text_does_not(self):
        long_day, short_day = self.find_day(True), self.find_day(False)
        self.assertIsNotNone(long_day, "스크롤이 필요한 날이 없음")
        w = self.make(long_day)
        s = w.scroller
        self.assertTrue(s.scrollable())
        self.assertGreater(s.content_height(), s.view_height())
        self.assertEqual(len(s.bar.find_all()), 2)       # 트랙과 막대
        self.assertEqual(s.first(), 0.0)
        top, bottom = s._thumb
        self.assertLess(0, bottom - top)
        self.assertLess(bottom - top, s.bar.winfo_height())
        if short_day is not None:
            w2 = self.make(short_day)
            self.assertEqual(w2.scroller.bar.find_all(), ())  # 내용이 짧으면 막대를 그리지 않는다

    def test_mouse_wheel_scrolls_and_stops_at_the_ends(self):
        w = self.make(self.find_day(True))
        s = w.scroller
        w._wheel(_Wheel(w.text, -120))                    # 아래로
        self.assertGreater(s.first(), 0.0)
        for _ in range(200):
            w._wheel(_Wheel(w.box, -120))
        w.root.update()
        self.assertTrue(s.seen_all())
        self.assertLessEqual(s.canvas.yview()[1], 1.0)
        for _ in range(200):
            w._wheel(_Wheel(w.text, 120))                 # 위로
        self.assertEqual(s.first(), 0.0)

    def test_wheel_over_the_settings_window_does_not_scroll_the_widget(self):
        w = self.make(self.find_day(True))
        w.open_settings()
        w.settings_win.top.update()
        w._wheel(_Wheel(w.settings_win.btn_close, -120))
        self.assertEqual(w.scroller.first(), 0.0)

    def test_drag_the_thumb_and_click_the_track(self):
        w = self.make(self.find_day(True))
        s = w.scroller
        top, bottom = s._thumb
        mid = (top + bottom) // 2
        s._press(_Ev(0, mid))
        s._motion(_Ev(0, mid + 40))
        self.assertGreater(s.first(), 0.0)
        s._release(_Ev(0, mid + 40))
        self.assertIsNone(s._grab)
        before = s.first()
        top, bottom = s._thumb
        s._press(_Ev(0, bottom + 20))                     # 막대 아래의 트랙을 누르면 한 쪽 넘어간다
        self.assertGreater(s.first(), before)
        s._press(_Ev(0, 1))                               # 막대 위의 트랙을 누르면 거꾸로
        s._press(_Ev(0, 1))
        self.assertEqual(s.first(), 0.0)

    def test_new_render_starts_at_the_top(self):
        w = self.make(self.find_day(True))
        w._wheel(_Wheel(w.text, -120))
        self.assertGreater(w.scroller.first(), 0.0)
        w.idx += 1
        w.render()
        w.root.update()
        self.assertEqual(w.scroller.first(), 0.0)

    def test_header_and_footer_stay_while_the_body_scrolls(self):
        w = self.make(self.find_day(True))
        head_y, foot_y = w.lbl_title.winfo_rooty(), w.foot.winfo_rooty()
        for _ in range(5):
            w._wheel(_Wheel(w.text, -120))
        w.root.update()
        self.assertEqual((w.lbl_title.winfo_rooty(), w.foot.winfo_rooty()), (head_y, foot_y))
        self.assertLess(w.scroller.frame.winfo_rooty(), foot_y)
        self.assertGreater(w.scroller.frame.winfo_rooty(), head_y)

    def test_hidden_words_still_reveal_on_click_inside_the_scroll_area(self):
        w = self.make(3, recite=2)
        w.root.update()
        ranges = w.text.tag_ranges("hid")
        self.assertTrue(ranges)
        x, y, _w, ht = w.text.bbox(ranges[0])
        self.assertEqual(w._reveal(_Ev(x + 2, y + ht // 2)), "break")
        self.assertEqual(len(w.revealed), 1)
        # 스크롤로 내용이 움직인 뒤에도 누른 자리의 낱말이 정확히 보인다
        w._wheel(_Wheel(w.text, -120))
        w.root.update()
        x, y, _w, ht = w.text.bbox(w.text.tag_ranges("hid")[0])
        before = len(w.revealed)
        w._reveal(_Ev(x + 2, y + ht // 2))
        self.assertEqual(len(w.revealed), before + 1)

    def test_scrollbar_follows_the_theme(self):
        w = self.make(self.find_day(True))
        light = w.scroller.colors["thumb"]
        w.set_setting("theme", "dark")
        w.root.update()
        self.assertNotEqual(w.scroller.colors["thumb"], light)
        self.assertEqual(w.scroller.colors["thumb"], K.DARK["veil_hi"])
        self.assertEqual(w.scroller.canvas.cget("bg"), K.DARK["card"])

    def test_font_size_keeps_the_proportion(self):
        for font in ("small", "large"):
            self.state.set("font", font)
            w = self.make(3)
            _l, top, _r, bottom = K.work_area()
            if w.root.winfo_height() < (bottom - top) - 2 * int(16 * w.sc):
                self.assertAlmostEqual(w.root.winfo_height() / w.root.winfo_width(), K.ASPECT, delta=0.01, msg=font)


class BodyFont(unittest.TestCase):
    """성경 본문(구절)만 함께 배포하는 리디바탕으로 보이고, 해설과 화면 글꼴은 그대로다."""

    RIDI = ("RIDIBatang", "리디바탕")

    @classmethod
    def setUpClass(cls):
        os.environ["KYEON_THEME"] = "light"
        cls.plan = K.load_plan()

    def make(self, tmp):
        w = K.Widget(self.plan, K.State(Path(tmp)), today_fn=lambda: date(2026, 3, 1), preview_day=3)
        self.addCleanup(w.quit)
        return w

    def test_verses_use_the_bundled_font_and_the_rest_do_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = self.make(tmp)
            self.assertIn(w.body_family, self.RIDI)
            self.assertIn(w.f_body.actual("family"), self.RIDI)   # 글꼴이 실제로 적용됨(대체 글꼴이 아님)
            self.assertIn(w.text.cget("font"), (str(w.f_body), w.f_body.name))
            for name in ("f_expl", "f_ref", "f_title", "f_small", "f_btn", "f_app"):
                self.assertNotIn(getattr(w, name).actual("family"), self.RIDI, name)

    def test_font_is_measurably_not_the_fallback(self):
        """없는 글꼴 이름은 시스템 기본 글꼴로 대체되어 폭이 달라진다. 리디바탕은 그것과 달라야 한다."""
        from tkinter import font as tkfont
        with tempfile.TemporaryDirectory() as tmp:
            w = self.make(tmp)
            sample = "태초에 말씀이 계시니라 하나님과 함께"
            ridi = tkfont.Font(root=w.root, family=w.body_family, size=30).measure(sample)
            missing = tkfont.Font(root=w.root, family="없는글꼴-zzz", size=30).measure(sample)
            self.assertNotEqual(ridi, missing)

    def test_body_size_is_one_step_larger_than_the_serif_default(self):
        self.assertEqual(K.Widget.FONT_BASE["f_body"], 12)

    def test_loading_ignores_missing_or_broken_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(K.load_bundled_fonts(Path(tmp) / "none"), 0)
            self.assertEqual(K.load_bundled_fonts(Path(tmp)), 0)
            (Path(tmp) / "broken.otf").write_bytes(b"not a font")
            (Path(tmp) / "notes.txt").write_text("x")
            self.assertEqual(K.load_bundled_fonts(Path(tmp)), 0)

    def test_shipped_font_is_a_real_opentype_file_with_its_license(self):
        font = K.FONT_DIR / "RIDIBatang.otf"
        self.assertEqual(font.read_bytes()[:4], b"OTTO")
        lic = (K.FONT_DIR / "LICENSE.txt").read_text(encoding="utf-8")
        for need in ("SIL OPEN FONT LICENSE Version 1.1", "리디주식회사", "Copyright (c) 2019 RIDI & Sandoll"):
            self.assertIn(need, lic)
        self.assertGreaterEqual(K.load_bundled_fonts(), 1)

    def test_fallback_order_when_the_bundled_font_is_missing(self):
        import types

        class Fake:
            def __init__(self, names):
                self._n = names

            def families(self):
                return self._n

        stub = types.SimpleNamespace(family="맑은 고딕", BODY_FAMILIES=K.Widget.BODY_FAMILIES)
        pick = K.Widget._pick_body_family
        self.assertEqual(pick(stub, Fake(["리디바탕", "Batang", "맑은 고딕"])), "리디바탕")
        self.assertEqual(pick(stub, Fake(["Batang", "맑은 고딕"])), "Batang")
        self.assertEqual(pick(stub, Fake(["바탕", "맑은 고딕"])), "바탕")
        self.assertEqual(pick(stub, Fake(["Arial", "맑은 고딕"])), "맑은 고딕")  # 바탕체가 하나도 없으면 화면 글꼴


class CheckCommand(unittest.TestCase):
    def test_check_passes_on_shipped_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(K.cmd_check(K.load_plan(), K.State(Path(tmp))), 0)

    def test_old_explain_format_still_renders_as_one_block(self):
        d = {"explain": "글", "verses": [[1, 1, "a"]], "title": "t", "ref": "r"}
        self.assertTrue(K.day_ok(d))
        self.assertEqual(K.Widget.blocks_of(d), [("묵상", "글")])

    def test_question_is_no_longer_required_nor_shown(self):
        d = {"blocks": [{"label": "그 당시", "text": "배경"}], "verses": [[1, 1, "a"]], "title": "t", "ref": "r"}
        self.assertTrue(K.day_ok(d))                       # 질문이 없어도 완전한 날이다
        self.assertTrue(K.day_ok({**d, "question": "q?"}))  # 옛 계획표에 질문이 남아 있어도 문제없이 무시한다


if __name__ == "__main__":
    unittest.main()
