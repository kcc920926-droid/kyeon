"""Python 이 없는 PC 에 주는 kyeon.exe 의 설치·제거 시험: python -m unittest discover -s tests -v
실제 레지스트리와 설치 폴더는 건드리지 않는다(임시 키와 임시 폴더를 쓴다). exe 를 직접 만들어 돌리는 시험은 tools/build_exe.py 가 만든 뒤 한다."""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
import winreg
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["KYEON_NO_UPDATE"] = "1"
import kyeon as K  # noqa: E402


def drop_key(path: str) -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_ALL_ACCESS) as k:
            while True:
                try:
                    sub = winreg.EnumKey(k, 0)
                except OSError:
                    break
                drop_key(path + "\\" + sub)
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
    except OSError:
        pass


def reg_get(path: str, name: str):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def wait(cond, secs: float = 30.0) -> bool:
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.3)
    return False


class FrozenCommands(unittest.TestCase):
    """exe 로 돌 때는 pythonw 와 kyeon.py 가 아니라 exe 자신을 다시 실행한다."""

    def test_python_mode_is_unchanged(self):
        self.assertFalse(K.FROZEN)
        self.assertIn("kyeon.py", " ".join(K.self_command()))
        self.assertIsNone(K.child_env())

    def test_autostart_and_spawn_use_the_exe_when_frozen(self):
        with mock.patch.object(K, "FROZEN", True), mock.patch.object(sys, "executable", r"C:\x y\kyeon.exe"):
            self.assertEqual(K.self_command(), [r"C:\x y\kyeon.exe"])
            self.assertEqual(K.autostart_command(), '"C:\\x y\\kyeon.exe" --startup')
            with mock.patch.object(K.subprocess, "Popen") as po:
                K.spawn_detached("--after-update", "--show")
            self.assertEqual(po.call_args.args[0], [r"C:\x y\kyeon.exe", "--after-update", "--show"])
            # 같은 exe 를 다시 띄울 때는 이 프로세스의 임시 폴더를 물려주지 않는다(안 그러면 이 프로세스가 끝날 때 새 위젯이 죽는다)
            self.assertEqual(po.call_args.kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"], "1")

    def test_spawn_can_target_another_exe(self):
        with mock.patch.object(K.subprocess, "Popen") as po:
            K.spawn_detached("--first-run", exe=Path(r"C:\i\kyeon.exe"))
        self.assertEqual(po.call_args.args[0], [r"C:\i\kyeon.exe", "--first-run"])


class MissingModules(unittest.TestCase):
    def test_finds_only_what_is_not_there(self):
        src = "from __future__ import annotations\nimport os, tkinter.font\nfrom urllib.request import urlopen\n" \
              "def f():\n    import not_a_real_module_xyz\n"
        self.assertEqual(K.missing_modules(src), ["not_a_real_module_xyz"])

    def test_current_program_needs_nothing_it_does_not_have(self):
        self.assertEqual(K.missing_modules((ROOT / "kyeon.py").read_text(encoding="utf-8")), [])

    def test_update_refuses_a_version_that_needs_a_module_the_runtime_lacks(self):
        with tempfile.TemporaryDirectory() as d:
            stage = Path(d)
            (stage / "kyeon.py").write_text('__version__ = "9.9.9"\nimport not_a_real_module_xyz\n', encoding="utf-8")
            with self.assertRaises(K.UpdateError) as cm:
                K._verify_staged({"version": "9.9.9"}, stage, ["kyeon.py"])
            self.assertIn("not_a_real_module_xyz", str(cm.exception))
            self.assertIn("새로 내려받아", str(cm.exception))


@unittest.skipUnless((ROOT / "tools" / "build_exe.py").exists(), "tools/ 는 ZIP 배포본에 들어 있지 않다")
class LauncherCoversTheProgram(unittest.TestCase):
    def test_every_import_of_kyeon_py_is_listed_in_the_launcher(self):
        """kyeon.py 에 import 를 더하고 tools/launcher.py 에 안 적으면 exe 에서만 시작이 안 된다(묶이지 않은 모듈)."""
        sys.path.insert(0, str(ROOT / "tools"))
        import build_exe
        miss = build_exe.uncovered((ROOT / "kyeon.py").read_text(encoding="utf-8"),
                                   (ROOT / "tools" / "launcher.py").read_text(encoding="utf-8"))
        self.assertEqual(miss, [])

    def test_launcher_runs_the_script_next_to_the_exe_else_sets_up(self):
        src = (ROOT / "tools" / "launcher.py").read_text(encoding="utf-8")
        self.assertIn('exe.with_name("kyeon.py")', src)
        self.assertIn('"--setup"', src)


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kyeon-setup-"))
        self.seed, self.target = self.tmp / "seed", self.tmp / "Programs" / "Kyeon"
        for rel, data in {"kyeon.py": b'__version__ = "9.9.9"\n', "data/plan.json": b"{}", "fonts/F.otf": b"OTTO",
                          "fonts/LICENSE.txt": b"lic", "README.md": b"# r", "latest.json": b"{}",
                          "evil.exe": b"MZ", "data/x.py": b"x"}.items():
            f = self.seed / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(data)
        self.exe = self.tmp / "dl" / "kyeon.exe"
        self.exe.parent.mkdir()
        self.exe.write_bytes(b"MZ runtime")
        self.key = rf"Software\KyeonTest-{uuid.uuid4().hex}"
        self.run_key, self.un_key = self.key + r"\Run", self.key + r"\Uninstall\Kyeon"
        self.menu = self.tmp / "menu"
        self.state = K.State(self.tmp / "state")
        self.args = dict(seed=self.seed, target=self.target, run_key=self.run_key, uninstall_key=self.un_key,
                         start_menu=self.menu)
        self.patches = [mock.patch.object(K, "stop_running_and_wait", return_value=True),
                        mock.patch.object(K, "spawn_detached"),
                        mock.patch.object(K, "make_shortcut", return_value=True)]
        self.stop, self.spawn, self.shortcut = [p.start() for p in self.patches]

    def tearDown(self):
        for p in self.patches:
            p.stop()
        drop_key(self.key)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def setup(self, yes=True):
        return K.cmd_setup(self.state, yes, self.exe, **self.args)

    def test_seed_files_keeps_only_updatable_names(self):
        self.assertEqual(K.seed_files(self.seed), ["README.md", "data/plan.json", "fonts/F.otf", "fonts/LICENSE.txt", "kyeon.py"])

    def test_installs_registers_and_starts(self):
        self.assertEqual(self.setup(), 0)
        for rel in ("kyeon.exe", "kyeon.py", "data/plan.json", "fonts/F.otf", "fonts/LICENSE.txt", "README.md"):
            self.assertTrue((self.target / rel).is_file(), rel)
        self.assertEqual((self.target / "kyeon.exe").read_bytes(), b"MZ runtime")
        for rel in ("latest.json", "evil.exe", "data/x.py"):
            self.assertFalse((self.target / rel).exists(), rel)
        self.assertEqual(list(self.target.glob("*.kyeon-new")), [])
        exe = self.target / "kyeon.exe"
        self.assertEqual(reg_get(self.run_key, "Kyeon"), f'"{exe}" --startup')
        self.assertEqual(reg_get(self.un_key, "DisplayName"), "켠 (kyeon)")
        self.assertEqual(reg_get(self.un_key, "DisplayVersion"), K.__version__)
        self.assertEqual(reg_get(self.un_key, "InstallLocation"), str(self.target))
        self.assertEqual(reg_get(self.un_key, "UninstallString"), f'"{exe}" --uninstall --purge')
        self.assertEqual(reg_get(self.un_key, "NoModify"), 1)
        self.shortcut.assert_called_once()
        self.assertEqual(self.shortcut.call_args.args[0], self.menu / K.SHORTCUT_NAME)
        self.spawn.assert_called_once_with("--first-run", exe=exe)

    def test_declining_installs_nothing(self):
        with mock.patch.object(K, "ask_yes_no", return_value=False) as ask:
            self.assertEqual(self.setup(yes=False), 1)
        ask.assert_called_once()
        self.assertFalse(self.target.exists())
        self.assertIsNone(reg_get(self.run_key, "Kyeon"))
        self.spawn.assert_not_called()

    def test_yes_skips_the_question(self):
        with mock.patch.object(K, "ask_yes_no") as ask:
            self.assertEqual(self.setup(yes=True), 0)
        ask.assert_not_called()

    def test_already_installed_only_opens_it(self):
        self.assertEqual(self.setup(), 0)
        self.spawn.reset_mock()
        (self.target / "kyeon.py").write_bytes(b"edited")
        self.assertEqual(self.setup(), 0)
        self.assertEqual((self.target / "kyeon.py").read_bytes(), b"edited")  # 덮어쓰지 않는다
        self.spawn.assert_called_once_with(exe=self.target / "kyeon.exe")

    def test_missing_seed_is_reported(self):
        (self.seed / "kyeon.py").unlink()
        with mock.patch.object(K, "tell") as tell:
            self.assertEqual(self.setup(), 2)
        self.assertTrue(tell.call_args.kwargs.get("error"))
        self.assertFalse(self.target.exists())

    def test_interrupted_install_is_not_seen_as_installed_and_can_be_retried(self):
        real = K._copy_atomic

        def flaky(src, dst):
            if Path(dst).name == "kyeon.exe":
                raise OSError(13, "권한 없음")
            real(src, dst)
        with mock.patch.object(K, "_copy_atomic", side_effect=flaky), mock.patch.object(K, "tell") as tell:
            self.assertEqual(self.setup(), 2)
        self.assertIn("설치하지 못했습니다", tell.call_args.args[0])
        self.assertTrue((self.target / "kyeon.py").is_file())      # 본체는 복사됐지만
        self.assertFalse((self.target / "kyeon.exe").exists())     # exe 가 없으니 '설치됨' 이 아니다
        self.assertIsNone(reg_get(self.run_key, "Kyeon"))
        self.spawn.assert_not_called()
        self.assertEqual(self.setup(), 0)                           # 다시 하면 끝까지 간다
        self.assertEqual(reg_get(self.run_key, "Kyeon"), f'"{self.target / "kyeon.exe"}" --startup')

    def test_remove_app_entries(self):
        self.setup()
        self.menu.mkdir(exist_ok=True)
        (self.menu / K.SHORTCUT_NAME).write_bytes(b"lnk")
        K.remove_app_entries(self.un_key, self.menu)
        self.assertIsNone(reg_get(self.un_key, "DisplayName"))
        self.assertFalse((self.menu / K.SHORTCUT_NAME).exists())
        K.remove_app_entries(self.un_key, self.menu)  # 두 번 불러도 괜찮다

    def test_app_list_version_follows_updates(self):
        self.setup()
        K.refresh_app_registration(self.un_key)
        self.assertEqual(reg_get(self.un_key, "DisplayVersion"), K.__version__)
        with mock.patch.object(K, "__version__", "9.9.9"):
            K.refresh_app_registration(self.un_key)
        self.assertEqual(reg_get(self.un_key, "DisplayVersion"), "9.9.9")
        K.refresh_app_registration(self.key + r"\없는키")  # 등록돼 있지 않으면 조용히 넘어간다


class ShortcutTests(unittest.TestCase):
    def test_shortcut_is_really_written(self):
        with tempfile.TemporaryDirectory() as d:
            lnk = Path(d) / "메뉴 폴더" / "켠.lnk"
            ok = K.make_shortcut(lnk, Path(sys.executable), Path(d), "화면 한켠, 마음 한가운데")
            if not ok:
                self.skipTest("이 PC 에서는 파워셸로 바로가기를 만들 수 없다")
            self.assertTrue(lnk.is_file())


class PurgeTests(unittest.TestCase):
    """제거: 우리가 둔 파일과 하위 폴더만 지우고, 모르는 파일이 있으면 그 폴더는 둔다."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kyeon-purge-"))
        # 사용자 이름이 한글이고 공백과 %, & 가 들어 있는 PC 를 흉내 낸다(글자 처리가 깨지면 지우지 못한다)
        self.base = self.tmp / "홍 길동 100% & 가족" / "Programs" / "Kyeon"
        self.state = self.tmp / "홍 길동 100% & 가족" / "Kyeon 기록"
        for rel in ("kyeon.exe", "kyeon.py", "README.md", "data/plan.json", "fonts/F.otf", "kyeon.py.kyeon-new"):
            f = self.base / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(b"x")
        for rel in ("state.json", "widget.log", "update/9.9.9/kyeon.py", "backup/0.1.0/kyeon.py"):
            f = self.state / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(b"x")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_refuses_anything_but_the_install_folder(self):
        other = self.tmp / "Other"
        other.mkdir()
        self.assertFalse(K.schedule_purge(self.base, None, install_dir=other))
        self.assertFalse(K.schedule_purge(self.tmp, None, install_dir=self.tmp))  # kyeon.py 가 없는 폴더
        self.assertTrue((self.base / "kyeon.py").exists())

    def test_removes_program_files_and_keeps_records_and_strangers(self):
        (self.base / "mine.txt").write_bytes("내 파일".encode())
        self.assertTrue(K.schedule_purge(self.base, None, install_dir=self.base))
        self.assertTrue(wait(lambda: not (self.base / "kyeon.py").exists() and not (self.base / "data").exists(), 40))
        self.assertTrue(wait(lambda: not (self.base / "kyeon.exe").exists(), 5))
        for rel in ("README.md", "fonts", "kyeon.py.kyeon-new"):
            self.assertFalse((self.base / rel).exists(), rel)
        self.assertEqual((self.base / "mine.txt").read_bytes(), "내 파일".encode())  # 모르는 파일과 폴더는 남는다
        self.assertTrue((self.state / "state.json").exists())                         # 기록은 지우라고 하지 않았다

    def test_removes_empty_folder_and_records_when_asked(self):
        self.assertTrue(K.schedule_purge(self.base, self.state, install_dir=self.base))
        self.assertTrue(wait(lambda: not self.base.exists() and not self.state.exists(), 40),
                        str(list(self.base.rglob("*")) + list(self.state.rglob("*"))))
        self.assertTrue(self.base.parent.exists())  # 위의 Programs 폴더는 건드리지 않는다


class UninstallCommand(unittest.TestCase):
    def test_purge_asks_about_records_unless_told(self):
        with mock.patch.object(K, "ask_yes_no", return_value=False) as ask, \
                mock.patch.object(K, "schedule_purge", return_value=True) as sp:
            K.cmd_purge(False, False)
        ask.assert_called_once()
        self.assertIsNone(sp.call_args.args[1])          # '아니요' = 기록은 남김
        with mock.patch.object(K, "ask_yes_no", return_value=True), mock.patch.object(K, "schedule_purge", return_value=True) as sp:
            K.cmd_purge(False, False)
        self.assertEqual(sp.call_args.args[1], K.STATE_DIR)
        with mock.patch.object(K, "ask_yes_no") as ask, mock.patch.object(K, "schedule_purge", return_value=True) as sp:
            K.cmd_purge(True, False)                      # --yes 만으로는 기록을 지우지 않는다
            ask.assert_not_called()
            self.assertIsNone(sp.call_args.args[1])
            K.cmd_purge(True, True)                       # --purge-records 가 있어야 기록까지
            self.assertEqual(sp.call_args.args[1], K.STATE_DIR)

    def test_not_the_install_folder_deletes_nothing(self):
        with mock.patch.object(K, "schedule_purge", return_value=False), mock.patch("builtins.print") as pr:
            self.assertEqual(K.cmd_purge(True, False), 0)
        self.assertIn("지우지 않았습니다", pr.call_args.args[0])


class InstallerScript(unittest.TestCase):
    def test_script_downloads_the_exe_checks_the_hash_and_needs_no_python(self):
        ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")
        self.assertTrue(ps1.isascii())
        self.assertIn("Get-FileHash", ps1)
        self.assertIn("--setup", ps1)
        self.assertNotIn("python", ps1.lower().replace("no python needed", ""))
        # 해시를 확인한 다음에야 실행한다
        self.assertLess(ps1.index("Get-FileHash"), ps1.index("Start-Process"))
        # WaitForExit 는 그 프로세스만 기다린다(Start-Process -Wait 는 자식까지 기다려 위젯이 끝날 때까지 멈춘다)
        self.assertIn("WaitForExit", ps1)
        self.assertNotIn("-Wait", ps1)


if __name__ == "__main__":
    unittest.main()
