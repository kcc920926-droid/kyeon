"""읽는 길(전체 순서, 시기별, 테마별, 갈래별) 시험: python -m unittest tests.test_routes -v   (Windows, tkinter 필요)"""
import contextlib
import io
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ["KYEON_NO_UPDATE"] = "1"  # 위젯 시험에서 새 버전 확인(네트워크)이 돌지 않게
import kyeon as K  # noqa: E402
import routes as routes_tool  # noqa: E402

PLAN = K.load_plan()


def out(fn, *a):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn(*a)
    return rc, buf.getvalue()


class RouteData(unittest.TestCase):
    """계획표(plan.json)의 길 정보와 길 만들기. tkinter 없이 돈다."""

    @classmethod
    def setUpClass(cls):
        cls.routes = K.build_routes(PLAN)
        cls.by_id = {r["id"]: r for r in cls.routes}

    def test_plan_route_info_matches_the_rule_table(self):
        self.assertEqual(routes_tool.check(PLAN), [])

    def test_all_route_comes_first_and_has_every_day(self):
        self.assertEqual(self.routes[0]["id"], K.ROUTE_ALL)
        self.assertEqual(self.routes[0]["idxs"], list(range(len(PLAN["days"]))))

    def test_eras_split_the_days_without_overlap(self):
        seen = [i for r in self.routes if r["kind"] == "era" for i in r["idxs"]]
        self.assertEqual(sorted(seen), list(range(len(PLAN["days"]))))

    def test_every_day_is_in_one_or_two_themes(self):
        count = [0] * len(PLAN["days"])
        for r in self.routes:
            if r["kind"] == "theme":
                for i in r["idxs"]:
                    count[i] += 1
        self.assertTrue(all(c in (1, 2) for c in count))

    def test_sections_follow_the_data(self):
        names = [r["name"] for r in self.routes if r["kind"] == "section"]
        self.assertEqual(names, list(dict.fromkeys(d["section"] for d in PLAN["days"])))

    def test_each_route_keeps_the_original_order(self):
        for r in self.routes:
            self.assertEqual(r["idxs"], sorted(set(r["idxs"])), r["id"])
            self.assertTrue(r["idxs"], r["id"])

    def test_route_ids_are_unique_and_prefixed_by_kind(self):
        ids = [r["id"] for r in self.routes]
        self.assertEqual(len(ids), len(set(ids)))
        for r in self.routes:
            self.assertTrue(r["id"] == "all" or r["id"].startswith(r["kind"] + ":"), r["id"])

    def test_plan_without_route_info_has_only_all_and_sections(self):
        plain = {"days": [{k: v for k, v in d.items() if k not in ("era", "themes")} for d in PLAN["days"]]}
        kinds = {r["kind"] for r in K.build_routes(plain)}
        self.assertEqual(kinds, {"all", "section"})

    def test_broken_definitions_and_empty_routes_are_skipped(self):
        plan = {"days": [{"section": "시편", "era": "a", "themes": ["x"]}, {"section": "시편", "era": "a"}],
                "routes": {"era": [{"id": "a", "name": "가"}, {"id": "none", "name": "빈 길"}, {"name": "id 없음"}, "문자열"],
                           "theme": [{"id": "x", "name": "엑스"}, {"id": "", "name": "빈 id"}]}}
        self.assertEqual([r["id"] for r in K.build_routes(plan)], ["all", "era:a", "theme:x", "section:시편"])
        self.assertEqual(K.build_routes(plan)[1]["idxs"], [0, 1])
        self.assertEqual(K.build_routes(plan)[2]["idxs"], [0])

    def test_find_route_falls_back_to_all(self):
        self.assertEqual(K.find_route(self.routes, "era:없는길")["id"], "all")
        self.assertEqual(K.find_route(self.routes, None)["id"], "all")
        self.assertEqual(K.find_route(self.routes, "era:exile")["id"], "era:exile")

    def test_labels(self):
        self.assertEqual(K.route_label(self.by_id["all"]), "전체 순서")
        self.assertEqual(K.route_label(self.by_id["era:exile"]), "시기별 · 포로와 귀환")
        self.assertEqual(K.route_label(self.by_id["theme:comfort"]), "테마별 · 위로와 쉼")

    def test_routes_doc_lists_the_same_ids_and_names_as_the_definitions(self):
        doc = (ROOT / "docs" / "ROUTES.md").read_text(encoding="utf-8")
        for r in routes_tool.ERAS + routes_tool.THEMES:
            self.assertIn(f"| {r['id']} | {r['name']} |", doc, r["id"])

    def test_era_rule_table_reads_chapters_of_split_books(self):
        self.assertEqual(routes_tool.era_of("열왕기상 8:22–30"), "kingdom")
        self.assertEqual(routes_tool.era_of("열왕기상 18:20–39"), "prophets")
        self.assertEqual(routes_tool.era_of("역대하 7:1–3"), "kingdom")
        self.assertEqual(routes_tool.era_of("역대하 20:1–12"), "prophets")
        self.assertEqual(routes_tool.era_of("요한1서 4:7–16"), "church")
        with self.assertRaises(KeyError):
            routes_tool.era_of("토빗기 1:1")


class RouteState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = K.State(Path(self.tmp.name))
        self.routes = K.build_routes(PLAN)
        self.day = date(2026, 3, 1)

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_route_and_type_guard(self):
        self.assertEqual(self.state.get("route"), "all")
        self.state.data["route"] = 123
        self.assertEqual(self.state.get("route"), "all")
        self.state.set("route", "era:exile")
        self.assertEqual(K.State(Path(self.tmp.name)).get("route"), "era:exile")

    def test_positions_ignore_garbage(self):
        self.state.data["route_pos"] = {"all": 3, "era:x": -1, "theme:y": "5", "section:z": True, "ok": 0}
        self.assertEqual(self.state.route_positions, {"all": 3, "ok": 0})
        self.state.data["route_pos"] = [1, 2]
        self.assertEqual(self.state.route_positions, {})

    def test_reload_sees_what_another_process_wrote(self):
        other = K.State(Path(self.tmp.name))
        other.set("skin", "excel")
        other.set_route_position("all", 7)
        self.assertEqual(self.state.get("skin"), "default")   # 아직 옛 값
        self.state.reload()
        self.assertEqual((self.state.get("skin"), self.state.route_positions), ("excel", {"all": 7}))

    def test_reload_keeps_current_values_when_the_file_is_broken(self):
        self.state.set("skin", "excel")
        self.state.file.write_text("{깨진 파일", encoding="utf-8")
        self.state.reload()
        self.assertEqual(self.state.get("skin"), "excel")

    def test_switch_remembers_the_place_and_resumes_it(self):
        self.state.start_date = self.day - timedelta(days=41)   # 전체 순서에서 오늘은 42일차(자리 41)
        K.switch_route(self.state, self.routes, "era:exile", self.day)
        self.assertEqual(self.state.get("route"), "era:exile")
        self.assertEqual(self.state.route_positions["all"], 41)
        self.assertEqual(self.state.start_date, self.day)   # 새 길은 1일차에서 시작
        later = self.day + timedelta(days=9)                 # 새 길에서 열흘째
        K.switch_route(self.state, self.routes, "all", later)
        self.assertEqual(self.state.route_positions["era:exile"], 9)
        self.assertEqual(K.day_index(self.state.start_date, later, 1000), 41)   # 전체 순서는 읽던 42일차 그대로
        K.switch_route(self.state, self.routes, "era:exile", later)
        n = len(K.find_route(self.routes, "era:exile")["idxs"])
        self.assertEqual(K.day_index(self.state.start_date, later, n), 9)

    def test_switching_to_the_same_route_changes_nothing(self):
        self.state.start_date = self.day
        K.switch_route(self.state, self.routes, "all", self.day)
        self.assertEqual((self.state.start_date, self.state.route_positions), (self.day, {}))

    def test_switch_clears_the_dismissed_day(self):
        self.state.start_date = self.day
        self.state.dismissed_date = self.day
        K.switch_route(self.state, self.routes, "theme:comfort", self.day)
        self.assertIsNone(self.state.dismissed_date)

    def test_remembered_place_wraps_when_the_route_got_shorter(self):
        self.state.set_route_position("era:exile", 10_000)
        self.state.start_date = self.day
        K.switch_route(self.state, self.routes, "era:exile", self.day)
        n = len(K.find_route(self.routes, "era:exile")["idxs"])
        self.assertEqual(K.day_index(self.state.start_date, self.day, n), 10_000 % n)

    def test_forget_positions(self):
        self.state.set_route_position("all", 5)
        self.state.forget_route_positions()
        self.assertEqual(self.state.route_positions, {})
        self.state.forget_route_positions()   # 없어도 문제없다


class RouteWidget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["KYEON_THEME"] = "light"

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
        w = K.Widget(PLAN, self.state, today_fn=lambda: self.clock[0], **kw)
        self.widgets.append(w)
        return w

    def test_today_follows_the_saved_route_one_passage_a_day(self):
        routes = K.build_routes(PLAN)
        exile = K.find_route(routes, "era:exile")["idxs"]
        K.switch_route(self.state, routes, "era:exile", self.clock[0])
        w = self.make()
        w.start("manual")
        self.assertEqual((w.route["id"], w.idx, w.current_day()), ("era:exile", exile[0], 1))
        self.clock[0] += timedelta(days=1)
        w.tick()
        self.assertEqual((w.idx, w.current_day()), (exile[1], 2))
        self.assertEqual(PLAN["days"][w.idx]["era"], "exile")

    def test_unknown_saved_route_falls_back_to_all(self):
        self.state.set("route", "era:사라진길")
        w = self.make()
        w.start("manual")
        self.assertEqual((w.route["id"], w.idx), ("all", 0))

    def test_set_route_changes_the_passage_and_remembers_the_place(self):
        w = self.make()
        w.start("manual")
        w.jump_to_day(5)
        w.set_route("theme:comfort")
        comfort = K.find_route(w.plan_routes, "theme:comfort")["idxs"]
        self.assertEqual((w.current_day(), w.idx), (1, comfort[0]))
        self.assertEqual(self.state.route_positions["all"], 4)
        w.jump_to_day(3)
        w.set_route("all")
        self.assertEqual((w.current_day(), w.idx), (5, 4))
        w.set_route("theme:comfort")
        self.assertEqual((w.current_day(), w.idx), (3, comfort[2]))
        self.assertEqual(self.state.get("route"), "theme:comfort")

    def test_progress_line_names_the_route(self):
        w = self.make()
        w.start("manual")
        self.assertEqual(w.lbl_prog.cget("text"), f"{PLAN['days'][0]['section']} · 1 / 1000")
        w.set_route("era:exile")
        n = len(w.track)
        self.assertEqual(w.lbl_prog.cget("text"), f"포로와 귀환 · 1 / {n}")

    def test_jump_and_day_counter_belong_to_the_route(self):
        w = self.make()
        w.start("manual")
        w.set_route("era:jesus")
        w.jump_to_day(10_000)   # 길의 끝으로 맞춰진다
        self.assertEqual(w.current_day(), len(w.track))
        w.open_settings()
        sw = w.settings_win
        self.assertEqual(sw.lbl_day.cget("text"), f"오늘은 {len(w.track)}일차 / {len(w.track)}")
        self.assertEqual(sw.lbl_route.cget("text"), "읽는 길: 시기별 · 예수님의 생애")
        sw.entry.delete(0, "end")
        sw.entry.insert(0, str(len(w.track) + 1))
        sw._jump()   # 길 안의 일수를 넘으면 받아 주지 않는다
        self.assertEqual(w.current_day(), len(w.track))
        w.set_route("all")
        self.assertEqual(sw.entry.get(), str(w.current_day()))   # 길이 바뀌면 입력칸도 그 길의 일차로

    def test_follows_a_route_saved_by_another_process(self):
        w = self.make()
        w.start("manual")
        other = K.State(Path(self.tmp.name))   # kyeon.py --route 를 실행한 다른 프로세스
        K.switch_route(other, w.plan_routes, "section:복음서", self.clock[0])
        self.state.send("show")
        w.tick()
        self.assertEqual(w.route["id"], "section:복음서")
        self.assertEqual(w.days[w.idx]["section"], "복음서")

    def test_setting_saved_by_another_process_reaches_the_running_widget(self):
        """0.2.0 의 위젯은 시작할 때 읽은 값만 들고 있어서 kyeon.py --skin 으로 바꾼 값이 떠 있는 위젯에 닿지 않았다."""
        w = self.make()
        w.start("manual")
        self.assertEqual(w.skin, "default")
        other = K.State(Path(self.tmp.name))
        other.set("skin", "excel")
        self.state.send("show")
        w.tick()
        self.assertEqual(w.skin, "excel")

    def test_preview_route_leaves_the_saved_state_alone(self):
        w = self.make(preview_day=3, route="theme:fear")
        w.start("manual")
        fear = K.find_route(w.plan_routes, "theme:fear")["idxs"]
        self.assertEqual((w.idx, w.current_day()), (fear[2], 3))
        w.set_route("era:jesus")
        self.assertEqual(w.current_day(), 1)
        self.assertIsNone(self.state.start_date)
        self.assertEqual(self.state.get("route"), "all")

    def test_route_window_lists_every_route_and_switches(self):
        w = self.make()
        w.start("manual")
        w.open_routes()
        rw = w.routes_win
        self.assertTrue(rw.alive())
        self.assertEqual(set(rw.rows), {r["id"] for r in w.plan_routes})
        w.open_routes()
        self.assertIs(w.routes_win, rw)   # 두 번 눌러도 창은 하나
        for row in rw.rows.values():
            self.assertTrue(row["name"].bind("<Button-1>"))
        rw._pick("era:exile")
        self.assertFalse(rw.alive())
        self.assertEqual(w.route["id"], "era:exile")

    def test_route_window_shows_places_remembered_for_other_routes(self):
        w = self.make()
        w.start("manual")
        w.jump_to_day(8)
        w.set_route("theme:hope")
        w.open_routes()
        rw = w.routes_win
        self.assertEqual(rw.rows["all"]["more"].cget("text"), "8일차에서 이어 읽기")
        self.assertEqual(rw.rows["theme:hope"]["more"].cget("text"), "지금 1일차")
        self.assertEqual(rw.rows["era:exile"]["more"].cget("text"), "")

    def test_closing_the_widget_for_today_closes_the_route_window(self):
        w = self.make()
        w.start("manual")
        w.open_routes()
        rw = w.routes_win
        w.dismiss()
        self.assertFalse(rw.alive())

    def test_progress_line_opens_the_route_window(self):
        w = self.make()
        w.start("manual")
        self.assertTrue(w.lbl_prog.bind("<Button-1>"))
        self.assertEqual(str(w.lbl_prog.cget("cursor")), "hand2")


class RouteCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = K.State(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_routes_lists_ids_and_marks_the_current_one(self):
        self.state.set("route", "era:exile")
        rc, text = out(K.cmd_routes, PLAN, self.state)
        self.assertEqual(rc, 0)
        for need in ("[전체 순서]", "[시기별]", "[테마별]", "[갈래별]", "era:jesus", "theme:comfort", "section:복음서"):
            self.assertIn(need, text)
        self.assertIn("* era:exile", text)
        self.assertNotIn("* all", text)

    def test_route_sets_and_validates(self):
        with mock.patch.object(K, "_tell_running"):
            rc, text = out(K.cmd_route, PLAN, self.state, "theme:comfort")
            self.assertEqual((rc, self.state.get("route")), (0, "theme:comfort"))
            self.assertIn("테마별 · 위로와 쉼", text)
            rc, text = out(K.cmd_route, PLAN, self.state, "theme:없는길")
            self.assertEqual((rc, self.state.get("route")), (2, "theme:comfort"))
            self.assertIn("--routes", text)

    def test_check_names_the_route(self):
        self.state.set("route", "era:exile")
        self.state.start_date = date.today()
        rc, text = out(K.cmd_check, PLAN, self.state)
        self.assertEqual(rc, 0)
        self.assertIn("시기별 · 포로와 귀환 1일차 /", text)

    def test_check_of_the_default_route_keeps_the_old_format(self):
        self.state.start_date = date.today()
        rc, text = out(K.cmd_check, PLAN, self.state)
        self.assertRegex(text, r"오늘\(\d{4}-\d\d-\d\d\) = 1일차 · 시편 · 시편 1편")


if __name__ == "__main__":
    unittest.main()
