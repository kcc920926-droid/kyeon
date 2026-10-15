"""도구용 계획표 읽기 시험: python -m unittest tests.test_planio -v   (tkinter 없이 돈다. 앱과 같은 결과인지는 있을 때만 대조한다)"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import planio  # noqa: E402


def write(tmp, name, days, **head):
    (Path(tmp) / name).write_text(json.dumps({**head, "days": [{"day": d} for d in days]}), encoding="utf-8")


class ReadPlan(unittest.TestCase):
    def test_parts_are_joined_in_number_order_and_the_header_is_the_first_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "plan.json", [1, 2], translation="개역한글")
            write(tmp, "plan-10.json", [10, 11], translation="무시")
            write(tmp, "plan-3.json", list(range(3, 10)))
            write(tmp, "plan-x.json", [99])
            plan = planio.read_plan(Path(tmp) / "plan.json")
            self.assertEqual([d["day"] for d in plan["days"]], list(range(1, 12)))
            self.assertEqual(plan["translation"], "개역한글")

    def test_a_folder_with_only_plan_json_reads_as_before(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "plan.json", [1, 2, 3])
            self.assertEqual(len(planio.read_plan(Path(tmp) / "plan.json")["days"]), 3)

    def test_same_result_as_the_app_loader(self):
        try:
            sys.path.insert(0, str(ROOT))
            import kyeon
        except ImportError:
            self.skipTest("tkinter 가 없습니다")
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "plan.json", [1, 2], routes={"era": []})
            write(tmp, "plan-3.json", [3, 4])
            write(tmp, "plan-1001.json", [])
            p = Path(tmp) / "plan.json"
            self.assertEqual(planio.read_plan(p)["days"][:4], kyeon.load_plan(p)["days"][:4])
            self.assertEqual([x.name for x in planio.part_files(p)], [x.name for x in kyeon.plan_part_files(p)])

    def test_the_repository_plan_reads(self):
        plan = planio.read_plan()
        self.assertEqual([d["day"] for d in plan["days"]], list(range(1, len(plan["days"]) + 1)))


if __name__ == "__main__":
    unittest.main()
