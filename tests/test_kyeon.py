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
import kyeon as K  # noqa: E402

FORMATS = {  # 형식 번호: 블록 라벨
    1: ["그 당시", "오늘"],
    2: ["흔한 읽기", "당시의 뜻", "오늘"],
    3: ["한 단어: {term}", "오늘"],
    4: ["그 자리에서", "오늘"],
    5: ["그 당시", "기도"],
    6: ["큰 이야기 속에서", "오늘"],
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
        self.assertEqual([d["day"] for d in self.days], list(range(1, 1001)))

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
            self.assertTrue(d["question"].endswith("?"), d["day"])

    def test_refs_are_unique_and_text_is_clean(self):
        self.assertEqual([r for r, n in Counter(d["ref"] for d in self.days).items() if n > 1], [])
        for d in self.days:
            for c, v, t in d["verses"]:
                self.assertTrue(t.strip(), d["ref"])
                self.assertNotIn("침례", t)
                self.assertNotIn("&nbsp;", t)

    def test_composition(self):
        secs = Counter(d["section"] for d in self.days)
        self.assertEqual(secs["시편"], 225)
        self.assertEqual(secs["복음서"], 225)
        # 시편과 복음서가 번갈아 나온다(그 사이에 다른 책이 끼어도 시편 다음 복음서 순서는 유지)
        pg = [d["section"] for d in self.days if d["section"] in ("시편", "복음서")]
        self.assertEqual(pg[:6], ["시편", "복음서"] * 3)
        self.assertEqual(len({d["ref"].split()[0] for d in self.days}), 66)

    def test_parallels_are_lists_of_labels(self):
        for d in self.days:
            if "parallels" in d:
                self.assertEqual(d["section"], "복음서")
                self.assertTrue(all(isinstance(p, str) and p for p in d["parallels"]))

    def test_load_plan_rejects_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "plan.json"
            p.write_text(json.dumps({"days": [{"day": 1}, {"day": 3}]}), encoding="utf-8")
            with self.assertRaises(ValueError):
                K.load_plan(p)


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

    def test_cycle_after_1000_days(self):
        self.state.start_date = date(2026, 3, 1)
        self.clock[0] = date(2026, 3, 1) + timedelta(days=1000)
        w = self.make()
        w.start("manual")
        self.assertEqual(w.idx, 0)

    def test_every_day_renders_and_fits_the_screen(self):
        w = self.make(preview_day=1)
        w._apply_theme()
        w.root.geometry(f"{int(w.W * w.sc)}x{int(600 * w.sc)}+0+0")
        w.root.update_idletasks()
        _l, top, _r, bottom = K.work_area()
        too_tall = []
        for i in range(len(w.days)):
            w.idx = i
            w._set_compact(False)
            w.render()
            w.root.update_idletasks()
            if w.root.winfo_reqheight() > (bottom - top) - 2 * int(16 * w.sc):
                w._set_compact(True)
                w.render()
                w.root.update_idletasks()
                if w.root.winfo_reqheight() > (bottom - top) - 2 * int(16 * w.sc):
                    too_tall.append(i + 1)
        self.assertEqual(too_tall, [])


class ReciteData(unittest.TestCase):
    """암송용 가림 정보(lv): 글자마다 0(안 가림) 1(핵심 키워드) 2(내용어) 3(나머지)."""

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
                self.assertTrue(set(s) <= set("0123"), d["ref"])
                if self.MERGED.fullmatch(t):
                    self.assertEqual(set(s), {"0"}, d["ref"])  # 합쳐진 구절 표기는 가리지 않는다
                    continue
                for ch, code in zip(t, s):
                    if ch == " ":
                        self.assertEqual(code, "0")
                    elif "가" <= ch <= "힣":
                        self.assertNotEqual(code, "0", (d["ref"], ch))

    def test_every_verse_has_a_keyword_and_levels_grow(self):
        n = {k: 0 for k in "123"}
        for d in self.days:
            for s, (_c, _v, t) in zip(d["lv"], d["verses"]):
                if self.MERGED.fullmatch(t):
                    continue
                self.assertIn("1", s, d["ref"])
                for k in n:
                    n[k] += s.count(k)
        tot = sum(n.values())
        self.assertLess(n["1"] / tot, 0.15)                 # 1단계는 가볍게
        self.assertGreater((n["1"] + n["2"]) / tot, 0.45)   # 2단계는 절반 이상
        self.assertGreater(n["3"] / tot, 0.2)


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

    def test_particles_stay_visible_until_level_3(self):
        w = self.make(preview_day=3, recite=2)
        w.start("manual")
        shown = w.text.get("1.0", "end")
        self.assertIn("에 ", shown)  # '태초에' 의 조사 '에' 는 2단계에서 보인다

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

    def test_excel_skin_fits_the_screen_on_sample_days(self):
        w = self.make(preview_day=1, skin="excel")
        w._apply_theme()
        w.root.geometry(f"{int(w.W * w.sc)}x{int(600 * w.sc)}+0+0")
        w.root.update_idletasks()
        _l, top, _r, bottom = K.work_area()
        too_tall = []
        for i in range(0, len(w.days), 7):
            w.idx = i
            w._set_compact(False)
            w.render()
            w.root.update_idletasks()
            if w.root.winfo_reqheight() > (bottom - top) - 2 * int(16 * w.sc):
                w._set_compact(True)
                w.render()
                w.root.update_idletasks()
                if w.root.winfo_reqheight() > (bottom - top) - 2 * int(16 * w.sc):
                    too_tall.append(i + 1)
        self.assertEqual(too_tall, [])


class CheckCommand(unittest.TestCase):
    def test_check_passes_on_shipped_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(K.cmd_check(K.load_plan(), K.State(Path(tmp))), 0)

    def test_old_explain_format_still_renders_as_one_block(self):
        d = {"explain": "글", "question": "?", "verses": [[1, 1, "a"]], "title": "t", "ref": "r"}
        self.assertTrue(K.day_ok(d))
        self.assertEqual(K.Widget.blocks_of(d), [("묵상", "글")])


if __name__ == "__main__":
    unittest.main()
