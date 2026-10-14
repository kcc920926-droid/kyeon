"""켠 업데이트 시험: python -m unittest discover -s tests -v
네트워크 없이 폴더 원본과 127.0.0.1 로컬 서버로 확인한다. 위젯 시험에는 tkinter 가 필요하다."""
import functools
import hashlib
import http.server
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["KYEON_NO_UPDATE"] = "1"  # start() 가 네트워크 확인을 켜지 않게(시험은 필요한 곳에서 직접 켠다)
import kyeon as K  # noqa: E402

PLAN_OLD = json.dumps({"days": [{"day": 1}]})
PLAN_NEW = json.dumps({"days": [{"day": 1}, {"day": 2}]})


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def app_src(version: str) -> bytes:
    return f'__version__ = "{version}"\nprint("hi")\n'.encode()


def files_for(version: str, plan: str = PLAN_OLD) -> dict:
    return {"kyeon.py": app_src(version), "data/plan.json": plan.encode(), "README.md": f"# {version}".encode()}


def write_files(d: Path, files: dict) -> None:
    for p, b in files.items():
        f = d.joinpath(*p.split("/"))
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b)


def write_release(d: Path, version: str, files: dict, **extra) -> Path:
    """d 폴더에 파일들과 latest.json 을 쓴다."""
    write_files(d, files)
    m = {"schema": 1, "app": "kyeon", "version": version, "tag": "v" + version, "released": "2026-10-12",
         "notes": ["새 기능 하나", "고친 것 하나"],
         "files": {p: {"sha256": sha(b), "size": len(b)} for p, b in files.items()}}
    m.update(extra)
    (d / "latest.json").write_text(json.dumps(m), encoding="utf-8")
    return d / "latest.json"


def manifest_bytes(**over) -> bytes:
    kb = app_src("9.9.9")
    m = {"schema": 1, "app": "kyeon", "version": "9.9.9", "files": {"kyeon.py": {"sha256": sha(kb), "size": len(kb)}}}
    m.update(over)
    return json.dumps(m).encode()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.rel, self.app, self.state_dir = t / "release", t / "app", t / "state"
        self.app.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def tree(self, d: Path) -> dict:
        return {p.relative_to(d).as_posix(): p.read_bytes() for p in d.rglob("*") if p.is_file()}


class VersionTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(K.parse_version("0.2.0"), (0, 2, 0))
        self.assertEqual(K.parse_version(" 1.10.3 "), (1, 10, 3))
        for bad in ("1.2", "v1.2.3", "1.2.3-beta", "1.2.3.4", "", None, "a.b.c", "1.2.99999"):
            self.assertIsNone(K.parse_version(bad), bad)

    def test_order_is_numeric_not_textual(self):
        self.assertGreater(K.parse_version("0.10.0"), K.parse_version("0.9.0"))
        self.assertGreater(K.parse_version("1.0.0"), K.parse_version("0.99.99"))

    def test_current_version_is_valid(self):
        self.assertIsNotNone(K.parse_version(K.__version__))


class ManifestTests(Base):
    LOC = "C:/x/latest.json"

    def parse(self, raw, loc=LOC):
        return K.parse_manifest(raw, loc)

    def test_good(self):
        m = self.parse(manifest_bytes(notes=["a", "b"], min_python="3.8", tag="v9.9.9", released="2026-10-12"))
        self.assertEqual((m["version"], m["vt"], m["notes"], m["min_python"]), ("9.9.9", (9, 9, 9), ["a", "b"], (3, 8)))
        self.assertIn("kyeon.py", m["files"])

    def test_rejects_broken_documents(self):
        for raw in (b"not json", b"[]", b"\xff\xfe", manifest_bytes(app="other"), manifest_bytes(schema=2),
                    manifest_bytes(version="x"), manifest_bytes(files={}), manifest_bytes(files=[])):
            with self.assertRaises(K.UpdateError, msg=raw[:30]):
                self.parse(raw)

    def test_requires_kyeon_py(self):
        b = app_src("1.0.0")
        with self.assertRaises(K.UpdateError):
            self.parse(manifest_bytes(files={"README.md": {"sha256": sha(b), "size": len(b)}}))

    def test_path_whitelist(self):
        b = b"x"
        ok = {"sha256": sha(b), "size": 1}
        kp = {"kyeon.py": {"sha256": sha(app_src("9.9.9")), "size": len(app_src("9.9.9"))}}
        for good in ("install.bat", "uninstall.bat", "show.bat", "data/plan.json", "CHANGELOG.md", "README.md",
                     "fonts/RIDIBatang.otf", "fonts/LICENSE.txt", "fonts/x-1.ttf"):
            self.parse(manifest_bytes(files={**kp, good: ok}))
        for bad in ("../kyeon.py", "data/../kyeon.py", "sub/kyeon.py", ".hidden.py", "nul.py", "COM1.txt", "aux.md",
                    "kyeon.exe", "data/x.py", "data/plan.JSON", "/abs.py", "C:/x.py", "kyeon.py ", "data/a/b.json",
                    "..\\x.py", "a b.py", "",
                    "fonts/a.exe", "fonts/sub/x.otf", "fonts/.x.otf", "font/x.otf", "fonts/nul.txt", "fonts/x.woff",
                    "fonts/../kyeon.py", "fonts/x.py"):
            with self.assertRaises(K.UpdateError, msg=repr(bad)):
                self.parse(manifest_bytes(files={**kp, bad: ok}))

    def test_hash_and_size_rules(self):
        kb = app_src("9.9.9")
        good = {"sha256": sha(kb), "size": len(kb)}
        for bad in ({"sha256": sha(kb).upper(), "size": 1}, {"sha256": "abc", "size": 1}, {"sha256": sha(kb)},
                    {"sha256": sha(kb), "size": -1}, {"sha256": sha(kb), "size": True},
                    {"sha256": sha(kb), "size": K.UPDATE_MAX_FILE + 1}, {"sha256": sha(kb), "size": "5"}, "text"):
            with self.assertRaises(K.UpdateError, msg=str(bad)[:40]):
                self.parse(manifest_bytes(files={"kyeon.py": bad}))
        self.parse(manifest_bytes(files={"kyeon.py": good}))

    def test_download_origin_rules(self):
        loc = "https://raw.example.com/o/r/main/latest.json"
        m = self.parse(manifest_bytes(base_url="https://raw.example.com/o/r/v9.9.9/"), loc)
        self.assertEqual(m["base"], "https://raw.example.com/o/r/v9.9.9/")
        self.assertEqual(self.parse(manifest_bytes(), loc)["base"], "https://raw.example.com/o/r/main/")
        for bad in ("https://evil.example.com/o/r/v9.9.9/", "http://raw.example.com/o/r/", "https://raw.example.com/o/r",
                    "ftp://raw.example.com/o/", 5):
            with self.assertRaises(K.UpdateError, msg=str(bad)):
                self.parse(manifest_bytes(base_url=bad), loc)

    def test_folder_source_ignores_base_url(self):
        p = write_release(self.rel, "9.9.9", files_for("9.9.9"), base_url="https://evil.example.com/")
        m = K.parse_manifest(p.read_bytes(), str(p))
        self.assertEqual(Path(m["base"]), self.rel)

    def test_notes_are_trimmed(self):
        m = self.parse(manifest_bytes(notes=["x" * 500] * 30))
        self.assertEqual((len(m["notes"]), len(m["notes"][0])), (12, 200))

    def test_url_rules(self):
        K._check_url("https://github.com/x")
        K._check_url("http://127.0.0.1:8000/x")
        K._check_url("http://localhost/x")
        for bad in ("http://example.com/x", "file:///c:/x", "ftp://x/y", "https:///nohost", "javascript:1"):
            with self.assertRaises(K.UpdateError, msg=bad):
                K._check_url(bad)


class CheckTests(Base):
    def test_newer_same_older(self):
        loc = write_release(self.rel, "0.5.0", files_for("0.5.0"))
        m = K.check_update(str(loc), current="0.4.9")
        self.assertEqual(m["version"], "0.5.0")
        self.assertIsNone(K.check_update(str(loc), current="0.5.0"))
        self.assertIsNone(K.check_update(str(loc), current="0.6.0"))
        self.assertEqual(K.check_update(str(loc), current="0.4.99")["version"], "0.5.0")

    def test_folder_source_finds_latest_json(self):
        write_release(self.rel, "0.5.0", files_for("0.5.0"))
        self.assertEqual(K.check_update(str(self.rel), current="0.1.0")["version"], "0.5.0")

    def test_python_requirement(self):
        loc = write_release(self.rel, "0.5.0", files_for("0.5.0"), min_python="99.0")
        with self.assertRaises(K.UpdateError) as cm:
            K.check_update(str(loc), current="0.1.0")
        self.assertIn("Python 99.0", str(cm.exception))

    def test_failures_become_update_errors(self):
        with self.assertRaises(K.UpdateError):
            K.check_update(str(self.rel / "nope" / "latest.json"))

        def boom(*a):
            raise K.UpdateError("서버에 연결하지 못했습니다")

        with self.assertRaises(K.UpdateError):
            K.check_update("https://example.com/latest.json", fetch_fn=boom)

    def test_uses_injected_fetch(self):
        calls = []

        def fake(loc, limit, timeout):
            calls.append((loc, limit, timeout))
            return manifest_bytes()

        m = K.check_update("https://example.com/d/latest.json", current="0.1.0", fetch_fn=fake)
        self.assertEqual(m["version"], "9.9.9")
        self.assertEqual(calls, [("https://example.com/d/latest.json", K.UPDATE_MAX_MANIFEST, K.UPDATE_CHECK_TIMEOUT)])

    def test_update_source_precedence(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = K.State(Path(tmp))
            with mock.patch.dict(os.environ):
                os.environ.pop("KYEON_UPDATE_URL", None)
                self.assertEqual(K.update_source(s), K.UPDATE_URL)
                s.set("update_url", "https://saved.example.com/latest.json")
                self.assertEqual(K.update_source(s), "https://saved.example.com/latest.json")
                os.environ["KYEON_UPDATE_URL"] = "https://env.example.com/latest.json"
                self.assertEqual(K.update_source(s), "https://env.example.com/latest.json")
                self.assertEqual(K.update_source(s, "D:/cli"), "D:/cli")

    def test_default_source_is_the_github_repo(self):
        self.assertTrue(K.UPDATE_URL.startswith("https://raw.githubusercontent.com/kcc920926-droid/kyeon/"))
        self.assertTrue(K.UPDATE_URL.endswith("/latest.json"))


class _Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/redir":
            self.send_response(302)
            self.send_header("Location", "http://example.com/x")
            self.end_headers()
            return
        super().do_GET()


class FetchTests(Base):
    @classmethod
    def setUpClass(cls):
        cls.web = tempfile.TemporaryDirectory()
        cls.root = Path(cls.web.name)
        handler = functools.partial(_Handler, directory=str(cls.root))
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.web.cleanup()

    def url(self, path=""):
        return f"http://127.0.0.1:{self.port}/{path}"

    def test_fetch_ok_missing_and_too_big(self):
        (self.root / "a.txt").write_bytes(b"hello")
        self.assertEqual(K.fetch(self.url("a.txt"), 100), b"hello")
        with self.assertRaises(K.UpdateError) as cm:
            K.fetch(self.url("missing.txt"), 100)
        self.assertIn("404", str(cm.exception))
        with self.assertRaises(K.UpdateError) as cm:
            K.fetch(self.url("a.txt"), 3)
        self.assertIn("너무 큽니다", str(cm.exception))

    def test_redirect_to_plain_http_is_blocked(self):
        with self.assertRaises(K.UpdateError):
            K.fetch(self.url("redir"), 100)

    def test_remote_http_is_refused_before_connecting(self):
        with self.assertRaises(K.UpdateError):
            K.fetch("http://example.com/latest.json", 100)

    def test_connection_failure_message(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        with self.assertRaises(K.UpdateError) as cm:
            K.fetch(f"http://127.0.0.1:{port}/x", 100, timeout=2)
        self.assertIn("연결", str(cm.exception))

    def test_check_and_apply_over_http(self):
        write_release(self.root / "rel", "0.5.0", files_for("0.5.0", PLAN_NEW))
        write_files(self.app, files_for("0.1.0"))
        m = K.check_update(self.url("rel/latest.json"), current="0.1.0")
        self.assertEqual(m["base"], self.url("rel/"))
        changed = K.apply_update(m, self.app, self.state_dir, current="0.1.0")
        self.assertEqual(sorted(changed), ["README.md", "data/plan.json", "kyeon.py"])
        self.assertEqual(self.tree(self.app), files_for("0.5.0", PLAN_NEW))

    def test_other_host_for_files_is_refused(self):
        write_release(self.root / "rel2", "0.5.0", files_for("0.5.0"), base_url=f"http://localhost:{self.port}/rel2/")
        with self.assertRaises(K.UpdateError):  # 127.0.0.1 로 받은 정보가 localhost 로 가라고 하면 거부
            K.check_update(self.url("rel2/latest.json"), current="0.1.0")


class ApplyTests(Base):
    def release(self, version="0.5.0", plan=PLAN_NEW, **kw):
        loc = write_release(self.rel, version, files_for(version, plan), **kw)
        return K.parse_manifest(loc.read_bytes(), str(loc))

    def test_fresh_install_into_an_empty_folder(self):
        m = self.release()
        changed = K.apply_update(m, self.app, self.state_dir, current="0.1.0")
        self.assertEqual(changed[-1], "kyeon.py")  # 프로그램 파일은 마지막에 바꾼다
        self.assertEqual(self.tree(self.app), files_for("0.5.0", PLAN_NEW))
        self.assertEqual(list(self.app.rglob("*.kyeon-new")), [])

    def test_update_replaces_only_changed_files_and_keeps_a_backup(self):
        write_files(self.app, files_for("0.1.0"))
        (self.app / "extra.txt").write_text("mine")  # 목록에 없는 내 파일은 건드리지 않는다
        m = self.release("0.5.0", PLAN_OLD)  # 계획표는 그대로
        fetched = []
        real = K.fetch

        def spy(loc, limit, timeout):
            fetched.append(Path(loc).name)
            return real(loc, limit, timeout)

        changed = K.apply_update(m, self.app, self.state_dir, fetch_fn=spy, current="0.1.0")
        self.assertEqual(sorted(changed), ["README.md", "kyeon.py"])
        self.assertEqual(sorted(fetched), ["README.md", "kyeon.py"])  # 같은 plan.json 은 받지 않는다
        self.assertEqual((self.app / "extra.txt").read_text(), "mine")
        self.assertEqual(self.tree(self.state_dir / "backup" / "0.1.0"),
                         {"kyeon.py": app_src("0.1.0"), "README.md": b"# 0.1.0"})
        self.assertFalse((self.state_dir / "update").exists() and any((self.state_dir / "update").rglob("*.*")))
        last = json.loads((self.state_dir / "last_update.json").read_text(encoding="utf-8"))
        self.assertEqual((last["from"], last["version"], last["notes"][0]), ("0.1.0", "0.5.0", "새 기능 하나"))

    def test_nothing_to_do(self):
        write_files(self.app, files_for("0.5.0", PLAN_NEW))
        m = self.release()
        self.assertEqual(K.apply_update(m, self.app, self.state_dir, current="0.5.0"), [])
        self.assertFalse(self.state_dir.exists())

    def test_hash_mismatch_changes_nothing(self):
        write_files(self.app, files_for("0.1.0"))
        before = self.tree(self.app)
        m = self.release()
        (self.rel / "kyeon.py").write_bytes(app_src("0.5.0").replace(b"hi", b"HI"))  # 같은 크기, 다른 내용
        with self.assertRaises(K.UpdateError) as cm:
            K.apply_update(m, self.app, self.state_dir, current="0.1.0")
        self.assertIn("kyeon.py", str(cm.exception))
        self.assertEqual(self.tree(self.app), before)
        self.assertFalse((self.state_dir / "backup").exists())

    def test_size_mismatch_changes_nothing(self):
        write_files(self.app, files_for("0.1.0"))
        before = self.tree(self.app)
        m = self.release()
        (self.rel / "data" / "plan.json").write_bytes(PLAN_NEW.encode() + b" ")
        with self.assertRaises(K.UpdateError):
            K.apply_update(m, self.app, self.state_dir, current="0.1.0")
        self.assertEqual(self.tree(self.app), before)

    def test_downloaded_program_must_compile_and_match_version(self):
        write_files(self.app, files_for("0.1.0"))
        before = self.tree(self.app)
        for src in (b"def broken(:\n", b'__version__ = "0.4.0"\n'):  # 문법 오류 / 목록과 다른 버전
            files = files_for("0.5.0")
            files["kyeon.py"] = src
            loc = write_release(self.rel, "0.5.0", files)
            m = K.parse_manifest(loc.read_bytes(), str(loc))
            with self.assertRaises(K.UpdateError):
                K.apply_update(m, self.app, self.state_dir, current="0.1.0")
            self.assertEqual(self.tree(self.app), before)

    def test_downloaded_plan_must_be_valid(self):
        write_files(self.app, files_for("0.1.0"))
        before = self.tree(self.app)
        for plan in ("not json", json.dumps({"days": []}), json.dumps({"days": [{"day": 2}]})):
            loc = write_release(self.rel, "0.5.0", files_for("0.5.0", plan))
            m = K.parse_manifest(loc.read_bytes(), str(loc))
            with self.assertRaises(K.UpdateError):
                K.apply_update(m, self.app, self.state_dir, current="0.1.0")
            self.assertEqual(self.tree(self.app), before)

    def test_a_plan_part_file_arrives_with_the_update_and_is_read_after_plan_json(self):
        write_files(self.app, files_for("0.1.0"))                       # plan.json 은 1일차 하나
        files = files_for("0.5.0")
        files["data/plan-2.json"] = json.dumps({"days": [{"day": 2}, {"day": 3}]}).encode()
        loc = write_release(self.rel, "0.5.0", files)
        m = K.parse_manifest(loc.read_bytes(), str(loc))
        changed = K.apply_update(m, self.app, self.state_dir, current="0.1.0")
        self.assertIn("data/plan-2.json", changed)
        self.assertEqual([d["day"] for d in K.load_plan(self.app / "data" / "plan.json")["days"]], [1, 2, 3])

    def test_a_plan_part_that_does_not_continue_the_plan_is_refused(self):
        write_files(self.app, files_for("0.1.0"))
        before = self.tree(self.app)
        for part in ({"days": [{"day": 3}]}, {"days": [{"day": 1}]}, {"days": "x"}):    # 빈틈, 겹침, 모양이 다름
            files = files_for("0.5.0")
            files["data/plan-2.json"] = json.dumps(part).encode()
            loc = write_release(self.rel, "0.5.0", files)
            m = K.parse_manifest(loc.read_bytes(), str(loc))
            with self.assertRaises(K.UpdateError):
                K.apply_update(m, self.app, self.state_dir, current="0.1.0")
            self.assertEqual(self.tree(self.app), before)

    def test_a_changed_plan_part_is_checked_against_the_plan_files_already_installed(self):
        files = files_for("0.1.0", PLAN_NEW)                            # 이미 2일치
        files["data/plan-3.json"] = json.dumps({"days": [{"day": 3}]}).encode()
        write_files(self.app, files)
        new = files_for("0.5.0", PLAN_NEW)                              # plan.json 은 그대로, 3일 파일만 바뀜
        new["data/plan-3.json"] = json.dumps({"days": [{"day": 3}, {"day": 4}]}).encode()
        loc = write_release(self.rel, "0.5.0", new)
        K.apply_update(K.parse_manifest(loc.read_bytes(), str(loc)), self.app, self.state_dir, current="0.1.0")
        self.assertEqual([d["day"] for d in K.load_plan(self.app / "data" / "plan.json")["days"]], [1, 2, 3, 4])
        new["data/plan-3.json"] = json.dumps({"days": [{"day": 4}]}).encode()      # 이번에는 2일 다음에 4일이 와서 빈틈
        loc = write_release(self.rel, "0.6.0", {**new, "kyeon.py": app_src("0.6.0")})
        with self.assertRaises(K.UpdateError):
            K.apply_update(K.parse_manifest(loc.read_bytes(), str(loc)), self.app, self.state_dir, current="0.5.0")
        self.assertEqual([d["day"] for d in K.load_plan(self.app / "data" / "plan.json")["days"]], [1, 2, 3, 4])

    def test_fonts_are_installed_when_they_look_like_fonts(self):
        files = files_for("0.5.0")
        files["fonts/F.otf"] = b"OTTO" + b"\x00" * 20
        files["fonts/LICENSE.txt"] = "라이선스".encode("utf-8")
        loc = write_release(self.rel, "0.5.0", files)
        m = K.parse_manifest(loc.read_bytes(), str(loc))
        changed = K.apply_update(m, self.app, self.state_dir, current="0.1.0")
        self.assertIn("fonts/F.otf", changed)
        self.assertEqual((self.app / "fonts" / "F.otf").read_bytes()[:4], b"OTTO")
        self.assertEqual((self.app / "fonts" / "LICENSE.txt").read_text(encoding="utf-8"), "라이선스")

    def test_a_file_named_like_a_font_but_not_a_font_is_refused(self):
        write_files(self.app, files_for("0.1.0"))
        before = self.tree(self.app)
        files = files_for("0.5.0")
        files["fonts/F.otf"] = b"MZ\x90\x00 this is an executable"
        loc = write_release(self.rel, "0.5.0", files)
        m = K.parse_manifest(loc.read_bytes(), str(loc))
        with self.assertRaises(K.UpdateError) as cm:
            K.apply_update(m, self.app, self.state_dir, current="0.1.0")
        self.assertIn("글꼴 파일이 아니", str(cm.exception))
        self.assertEqual(self.tree(self.app), before)

    def test_failure_while_swapping_rolls_everything_back(self):
        write_files(self.app, files_for("0.1.0"))
        before = self.tree(self.app)
        m = self.release("0.5.0", PLAN_NEW)
        real = os.replace

        def flaky(src, dst, *a, **k):
            if os.path.basename(str(dst)) == "kyeon.py":  # plan.json, README 는 바뀐 뒤 kyeon.py 에서 실패
                raise PermissionError("locked")
            return real(src, dst, *a, **k)

        with mock.patch.object(K.os, "replace", side_effect=flaky):
            with self.assertRaises(K.UpdateError) as cm:
                K.apply_update(m, self.app, self.state_dir, current="0.1.0")
        self.assertIn("되돌렸습니다", str(cm.exception))
        self.assertEqual(self.tree(self.app), before)
        self.assertEqual(list(self.app.rglob("*.kyeon-new")), [])

    def test_rollback_restores_the_previous_files(self):
        write_files(self.app, files_for("0.1.0"))
        K.apply_update(self.release("0.5.0", PLAN_NEW), self.app, self.state_dir, current="0.1.0")
        self.assertEqual((self.app / "kyeon.py").read_bytes(), app_src("0.5.0"))
        ver, paths = K.rollback(self.app, self.state_dir)
        self.assertEqual(ver, "0.1.0")
        self.assertEqual(self.tree(self.app), files_for("0.1.0"))
        self.assertIn("kyeon.py", paths)

    def test_rollback_without_backup(self):
        with self.assertRaises(K.UpdateError):
            K.rollback(self.app, self.state_dir)

    def test_rollback_ignores_unsafe_names_in_the_backup(self):
        write_files(self.state_dir / "backup" / "0.1.0", {"kyeon.py": app_src("0.1.0")})
        (self.state_dir / "backup" / "0.1.0" / "evil.exe").write_bytes(b"x")
        K.rollback(self.app, self.state_dir)
        self.assertTrue((self.app / "kyeon.py").exists())
        self.assertFalse((self.app / "evil.exe").exists())

    def test_old_backups_are_pruned(self):
        root = self.state_dir / "backup"
        for i in range(5):
            d = root / f"0.1.{i}"
            d.mkdir(parents=True)
            os.utime(d, (1000 + i, 1000 + i))
        K._prune_backups(root, keep=3)
        self.assertEqual(sorted(p.name for p in root.iterdir()), ["0.1.2", "0.1.3", "0.1.4"])

    def test_last_update_is_read_once_and_only_for_this_version(self):
        self.state_dir.mkdir()
        f = self.state_dir / "last_update.json"
        f.write_text(json.dumps({"from": "0.1.0", "version": K.__version__, "notes": ["a"]}), encoding="utf-8")
        self.assertEqual(K.read_last_update(self.state_dir)["notes"], ["a"])
        self.assertFalse(f.exists())
        self.assertIsNone(K.read_last_update(self.state_dir))
        f.write_text(json.dumps({"version": "0.0.1"}), encoding="utf-8")
        self.assertIsNone(K.read_last_update(self.state_dir))
        f.write_text("garbage", encoding="utf-8")
        self.assertIsNone(K.read_last_update(self.state_dir))


class StateUpdateTests(unittest.TestCase):
    def test_defaults_and_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = K.State(Path(tmp))
            self.assertTrue(s.get("update_check"))
            self.assertEqual((s.update_checked_at, s.update_skipped), (None, ""))
            s.mark_update_checked(1234.5)
            s.update_skipped = "0.3.0"
            s2 = K.State(Path(tmp))
            self.assertEqual((s2.update_checked_at, s2.update_skipped), (1234.5, "0.3.0"))
            s2.data["update_checked_at"] = "yesterday"
            self.assertIsNone(s2.update_checked_at)
            s2.set("update_check", False)
            self.assertFalse(K.State(Path(tmp)).get("update_check"))


def fake_manifest(version="9.9.9", notes=("새 기능 하나",)):
    return {"version": version, "vt": K.parse_version(version), "notes": list(notes), "tag": "", "released": "",
            "min_python": None, "base": "", "files": {}}


class WidgetUpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["KYEON_THEME"] = "light"
        cls.plan = K.load_plan()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = K.State(Path(self.tmp.name) / "state")
        self.widgets = []

    def tearDown(self):
        for w in self.widgets:
            try:
                w.quit()
            except Exception:  # noqa: BLE001
                pass
        self.tmp.cleanup()

    def make(self, enabled=True):
        w = K.Widget(self.plan, self.state, today_fn=lambda: date(2026, 3, 1))
        self.widgets.append(w)
        w.start("manual")
        w.updates_enabled = enabled  # start() 는 KYEON_NO_UPDATE 때문에 끈 상태로 둔다
        w.root.update()
        return w

    def pump(self, w, until, seconds=10):
        end = time.time() + seconds
        while time.time() < end:
            w.root.update()
            w._poll_update()
            if until():
                return True
            time.sleep(0.02)
        return False

    def show_bar(self, w, **kw):
        w.update_info = fake_manifest(**kw)
        w.update_state = "idle"
        w.reflow()
        w.root.update()

    def test_bar_is_hidden_by_default(self):
        w = self.make()
        self.assertFalse(w.upd_bar.winfo_ismapped())

    def test_bar_shows_version_note_and_buttons(self):
        w = self.make()
        self.show_bar(w)
        self.assertTrue(w.upd_bar.winfo_ismapped())
        text = w.lbl_upd.cget("text")
        self.assertIn("9.9.9", text)
        self.assertIn("새 기능 하나", text)
        self.assertEqual(w.btn_upd.cget("text"), "업데이트")
        self.assertTrue(w.btn_upd.winfo_ismapped() and w.btn_upd_later.winfo_ismapped())
        left, top, right, bottom = K.work_area()
        self.assertLessEqual(w.root.winfo_height(), bottom - top)  # 안내 줄이 끼어도 화면 안에 들어간다
        # 본문 스크롤 영역 아래, 바닥줄 위에 고정된다(본문이 스크롤돼도 늘 보인다)
        self.assertGreater(w.upd_bar.winfo_rooty(), w.scroller.frame.winfo_rooty())
        self.assertLess(w.upd_bar.winfo_rooty(), w.foot.winfo_rooty())

    def test_bar_follows_the_excel_skin_and_dark_theme(self):
        for skin, theme in (("excel", "light"), ("default", "dark")):
            self.state.set("skin", skin)
            self.state.set("theme", theme)
            w = self.make()
            self.show_bar(w)
            self.assertTrue(w.upd_bar.winfo_ismapped(), (skin, theme))
            self.assertEqual(w.upd_bar.cget("bg"), w._p["soft"])

    def test_later_hides_until_a_newer_version(self):
        w = self.make()
        self.show_bar(w)
        w.skip_update()
        w.root.update()
        self.assertEqual(self.state.update_skipped, "9.9.9")
        self.assertFalse(w.upd_bar.winfo_ismapped())
        self.show_bar(w, version="9.9.10")
        self.assertTrue(w.upd_bar.winfo_ismapped())

    def test_working_and_error_states(self):
        w = self.make()
        self.show_bar(w)
        w.update_state = "working"
        w.reflow()
        w.root.update()
        self.assertIn("내려받아", w.lbl_upd.cget("text"))
        self.assertFalse(w.btn_upd.winfo_ismapped() or w.btn_upd_later.winfo_ismapped())
        w.update_state, w.update_msg = "error", "파일이 달라 중단했습니다"
        w.reflow()
        w.root.update()
        self.assertIn("파일이 달라", w.lbl_upd.cget("text"))
        self.assertEqual(w.btn_upd.cget("text"), "다시 시도")

    def test_poll_found_marks_the_check_and_shows_the_bar(self):
        w = self.make()
        w._checking = True
        w._upd_q.put(("check", True, fake_manifest()))
        w._poll_update()
        w.root.update()
        self.assertFalse(w._checking)
        self.assertIsNotNone(self.state.update_checked_at)
        self.assertTrue(w.upd_bar.winfo_ismapped())

    def test_poll_up_to_date_clears_the_bar(self):
        w = self.make()
        self.show_bar(w)
        w._upd_q.put(("check", True, None))
        w._poll_update()
        w.root.update()
        self.assertIsNone(w.update_info)
        self.assertFalse(w.upd_bar.winfo_ismapped())

    def test_logon_check_failure_is_silent_but_manual_is_not(self):
        w = self.make()
        w._check_manual = False
        w._upd_q.put(("check", False, "서버에 연결하지 못했습니다"))
        w._poll_update()
        self.assertEqual(w.update_msg, "")
        self.assertIsNone(self.state.update_checked_at)
        w._check_manual = True
        w._upd_q.put(("check", False, "서버에 연결하지 못했습니다"))
        w._poll_update()
        self.assertEqual(w.update_msg, "서버에 연결하지 못했습니다")

    def test_check_now_runs_in_the_background(self):
        w = self.make()
        with mock.patch.object(K, "check_update", return_value=fake_manifest()) as chk:
            w.check_now()
            self.assertTrue(w._checking)
            self.assertTrue(self.pump(w, lambda: w.update_info is not None))
        self.assertEqual(chk.call_count, 1)
        self.assertFalse(w._checking)

    def test_check_now_does_nothing_in_preview(self):
        w = self.make(enabled=False)
        with mock.patch.object(K, "check_update") as chk:
            w.check_now()
        chk.assert_not_called()
        self.assertIn("미리보기", w.update_msg)

    def test_install_end_to_end(self):
        t = Path(self.tmp.name)
        app, rel = t / "app", t / "rel"
        app.mkdir()
        write_files(app, files_for("0.1.0"))
        loc = write_release(rel, "9.9.9", files_for("9.9.9", PLAN_NEW))
        w = self.make()
        w.base_dir = app
        w.update_info = K.parse_manifest(loc.read_bytes(), str(loc))
        w.reflow()
        with mock.patch.object(w, "_restart") as restart:
            w.install_update()
            self.assertEqual(w.update_state, "working")
            self.assertTrue(self.pump(w, lambda: restart.called))
        self.assertEqual((app / "kyeon.py").read_bytes(), app_src("9.9.9"))
        self.assertEqual((app / "data" / "plan.json").read_text(), PLAN_NEW)

    def test_install_failure_offers_retry(self):
        t = Path(self.tmp.name)
        app, rel = t / "app", t / "rel"
        app.mkdir()
        write_files(app, files_for("0.1.0"))
        loc = write_release(rel, "9.9.9", files_for("9.9.9", PLAN_NEW))
        (rel / "kyeon.py").write_bytes(b"tampered")
        w = self.make()
        w.base_dir = app
        w.update_info = K.parse_manifest(loc.read_bytes(), str(loc))
        w.install_update()
        self.assertTrue(self.pump(w, lambda: w.update_state == "error"))
        w.root.update()
        self.assertEqual(w.btn_upd.cget("text"), "다시 시도")
        self.assertEqual((app / "kyeon.py").read_bytes(), app_src("0.1.0"))

    def test_done_banner_after_restart_is_shown_once(self):
        self.state.dir.mkdir(parents=True, exist_ok=True)
        (self.state.dir / "last_update.json").write_text(
            json.dumps({"from": "0.1.0", "version": K.__version__, "notes": ["고친 것 하나"]}), encoding="utf-8")
        w = K.Widget(self.plan, self.state, today_fn=lambda: date(2026, 3, 1))
        self.widgets.append(w)
        w.updates_enabled = True
        w._announce_update_done()
        w.reflow()
        w.root.update()
        self.assertEqual(w.update_state, "done")
        self.assertIn("업데이트했습니다", w.lbl_upd.cget("text"))
        self.assertEqual(w.btn_upd.cget("text"), "확인")
        self.assertFalse(w.btn_upd_later.winfo_ismapped())
        w._upd_action()
        w.root.update()
        self.assertIsNone(w.update_info)
        self.assertFalse(w.upd_bar.winfo_ismapped())
        w._announce_update_done()
        self.assertIsNone(w.update_info)

    def test_restart_signal_restarts_the_widget(self):
        w = self.make()
        with mock.patch.object(w, "_restart") as restart:
            self.state.send("restart")
            w.tick()
        restart.assert_called_once()

    def test_restart_spawns_the_new_process_first(self):
        w = self.make()
        with mock.patch.object(K, "spawn_detached") as sp:
            w._restart()
        sp.assert_called_once_with("--after-update", "--show")  # 보이는 중이었으면 다시 떠서도 보인다
        self.assertTrue(w._quitting)

    def test_restart_failure_is_reported_and_widget_stays(self):
        w = self.make()
        with mock.patch.object(K, "spawn_detached", side_effect=OSError("no")):
            w._restart()
        self.assertFalse(w._quitting)
        self.assertEqual(w.update_state, "error")

    def test_settings_window_shows_status_and_controls(self):
        w = self.make()
        w.open_settings()
        sw = w.settings_win
        sw.top.update()
        self.assertIn("아직 확인하지 않았습니다", sw.lbl_upd.cget("text"))
        self.assertFalse(sw.btn_ins.winfo_ismapped())
        w.update_info = fake_manifest()
        sw.refresh()
        sw.top.update()
        self.assertIn("9.9.9", sw.lbl_upd.cget("text"))
        self.assertTrue(sw.btn_ins.winfo_ismapped())
        sw._choose("update_check", False)
        self.assertIs(w.cfg["update_check"], False)
        self.assertIs(self.state.get("update_check"), False)

    def _delays(self, mode, **settings):
        for k, v in settings.items():
            self.state.set(k, v)
        w = K.Widget(self.plan, self.state, today_fn=lambda: date(2026, 3, 1))
        self.widgets.append(w)
        seen = []
        real = w.root.after
        w.root.after = lambda ms, *a, **k: (seen.append(ms), real(ms, *a, **k))[1]
        with mock.patch.dict(os.environ):
            os.environ.pop("KYEON_NO_UPDATE", None)
            w.start(mode)
        return seen

    def test_automatic_check_happens_only_at_logon(self):
        self.assertIn(K.UPDATE_FIRST_CHECK_MS, self._delays("startup"))
        self.assertNotIn(K.UPDATE_FIRST_CHECK_MS, self._delays("manual"))
        self.assertNotIn(K.UPDATE_FIRST_CHECK_MS, self._delays("resume"))

    def test_first_run_after_setup_shows_at_once_and_checks_once(self):
        seen = self._delays("first")
        self.assertIn(K.UPDATE_FIRST_CHECK_MS, seen)
        self.assertNotIn(K.SHOW_DELAY_STARTUP_MS, seen)   # 설치 직후에는 로그온처럼 기다리지 않고 바로 보인다

    def test_automatic_check_respects_the_setting(self):
        self.assertNotIn(K.UPDATE_FIRST_CHECK_MS, self._delays("startup", update_check=False))

    def test_no_network_in_preview(self):
        w = K.Widget(self.plan, self.state, today_fn=lambda: date(2026, 3, 1), preview_day=3)
        self.widgets.append(w)
        with mock.patch.dict(os.environ):
            os.environ.pop("KYEON_NO_UPDATE", None)
            w.start("manual")
        self.assertFalse(w.updates_enabled)


class ReleaseFiles(unittest.TestCase):
    """릴리스에 필요한 파일이 빠지지 않았는지 지킨다."""

    def test_version_has_a_changelog_entry_with_notes(self):
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertRegex(text, rf"(?m)^## {K.__version__.replace('.', r'[.]')} \(\d{{4}}-\d{{2}}-\d{{2}}\)$")

    def test_installer_script_points_at_the_same_repo(self):
        ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")
        repo = K.UPDATE_URL.split("raw.githubusercontent.com/")[1].split("/main/")[0]
        self.assertIn(f"raw.githubusercontent.com/{repo}/main/latest.json", ps1)
        self.assertTrue(ps1.isascii(), "irm | iex 로 받을 때 글자가 깨지지 않게 ASCII 만 쓴다")

    def test_every_updatable_file_of_the_release_exists(self):
        for p in ("kyeon.py", "data/plan.json", "install.bat", "uninstall.bat", "show.bat", "README.md", "CHANGELOG.md",
                  "fonts/RIDIBatang.otf", "fonts/LICENSE.txt"):
            self.assertTrue(K._safe_path(p), p)
            self.assertTrue((ROOT / p).is_file(), p)

    def test_latest_json_if_present_is_valid_and_lists_existing_files(self):
        f = ROOT / "latest.json"
        if not f.exists():
            self.skipTest("latest.json 은 릴리스할 때 만든다")
        m = K.parse_manifest(f.read_bytes(), str(f))
        for p in m["files"]:
            self.assertTrue((ROOT / p).is_file(), p)


@unittest.skipUnless((ROOT / "tools" / "make_manifest.py").exists(), "tools/ 는 ZIP 배포본에 들어 있지 않다")
class ManifestTool(Base):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / "tools"))
        import make_manifest
        cls.M = make_manifest

    def git(self, repo, *args):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-C", str(repo), *args],
                              check=True, capture_output=True)

    def make_repo(self, version="0.9.9", changelog=None, with_font=True, name="repo"):
        repo = Path(self.tmp.name) / name
        repo.mkdir()
        write_files(repo, files_for(version))
        write_files(repo, {"CHANGELOG.md": (changelog if changelog is not None
                                           else f"# 변경 기록\n\n## {version} (2026-10-12)\n\n- 첫 항목\n- 둘째\n\n## 0.1.0 (2026-01-01)\n\n- 옛것\n").encode("utf-8")})
        if with_font:
            write_files(repo, {"fonts/F.otf": b"OTTO" + b"\x00" * 10, "fonts/LICENSE.txt": b"lic", "fonts/skip.woff": b"x"})
        self.git(repo, "init", "-q")
        self.git(repo, "add", "-A")
        self.git(repo, "commit", "-q", "-m", "x")
        return repo

    def test_changelog_notes(self):
        text = "## 0.2.0 (d)\n\n- 하나\n- 둘\n\n## 0.1.0 (d)\n\n- 옛것\n"
        self.assertEqual(self.M.changelog_notes(text, "0.2.0"), ["하나", "둘"])
        self.assertEqual(self.M.changelog_notes(text, "0.1.0"), ["옛것"])
        self.assertEqual(self.M.changelog_notes(text, "9.9.9"), [])

    def test_manifest_from_a_tag_is_valid_for_the_client_and_hashes_match(self):
        repo = self.make_repo()
        self.git(repo, "tag", "v0.9.9")
        with mock.patch.object(self.M, "ROOT", repo):
            m = self.M.from_tag("v0.9.9")
        self.assertEqual((m["version"], m["tag"], m["notes"]), ("0.9.9", "v0.9.9", ["첫 항목", "둘째"]))
        self.assertTrue(m["base_url"].endswith("/v0.9.9/"))
        self.assertIn("fonts/F.otf", m["files"])
        self.assertNotIn("fonts/skip.woff", m["files"])    # 허용하지 않는 확장자는 목록에 넣지 않는다
        parsed = K.parse_manifest(json.dumps(m).encode("utf-8"), "https://raw.githubusercontent.com/o/r/main/latest.json")
        for p, info in parsed["files"].items():
            blob = (repo / p).read_bytes()
            self.assertEqual((info["sha256"], info["size"]), (sha(blob), len(blob)), p)

    def test_hashes_come_from_the_tag_not_the_working_folder(self):
        repo = self.make_repo()
        self.git(repo, "tag", "v0.9.9")
        (repo / "kyeon.py").write_bytes('__version__ = "0.9.9"\n# 태그 뒤에 고친 것\n'.encode("utf-8"))
        with mock.patch.object(self.M, "ROOT", repo):
            m = self.M.from_tag("v0.9.9")
        self.assertEqual(m["files"]["kyeon.py"]["sha256"], sha(app_src("0.9.9")))

    def test_refuses_mismatched_version_missing_notes_missing_tag(self):
        repo = self.make_repo("0.9.9")
        self.git(repo, "tag", "v0.9.8")   # 파일은 0.9.9 인데 태그는 0.9.8
        with mock.patch.object(self.M, "ROOT", repo):
            for tag in ("v0.9.8", "v1.0.0", "0.9.9", "latest"):
                with self.assertRaises(SystemExit, msg=tag):
                    self.M.from_tag(tag)
        repo = self.make_repo("0.9.9", changelog="# 변경 기록\n\n## 0.1.0 (d)\n\n- 옛것\n", name="repo2")
        self.git(repo, "tag", "v0.9.9")
        with mock.patch.object(self.M, "ROOT", repo):
            with self.assertRaises(SystemExit):   # 이 버전의 변경 기록이 없다
                self.M.from_tag("v0.9.9")

    def test_runtime_block_is_written_and_the_updater_ignores_it(self):
        exe = Path(self.tmp.name) / "kyeon.exe"
        exe.write_bytes(b"MZ" + b"\x01" * 40)
        rt = self.M.runtime_info(exe, "v0.9.9")
        self.assertEqual(rt, {"name": "kyeon.exe", "url": f"https://github.com/{self.M.REPO}/releases/download/v0.9.9/kyeon.exe",
                              "sha256": sha(exe.read_bytes()), "size": 42})
        blobs = {"kyeon.py": app_src("0.9.9"), "data/plan.json": b"{}"}
        m = self.M.build_manifest(dict(blobs), "0.9.9", "v0.9.9", "2026-10-12", ["n"], runtime=rt)
        self.assertEqual(m["runtime"], rt)
        self.assertNotIn("runtime", self.M.build_manifest(dict(blobs), "0.9.9", "v0.9.9", "2026-10-12", ["n"]))
        parsed = K.parse_manifest(json.dumps(m).encode(), "https://raw.githubusercontent.com/x/y/v0.9.9/latest.json")
        self.assertEqual(sorted(parsed["files"]), ["data/plan.json", "kyeon.py"])  # exe 는 업데이트 대상이 아니다

    def test_from_tag_carries_the_runtime_block(self):
        repo = self.make_repo("0.9.9")
        self.git(repo, "tag", "v0.9.9")
        rt = {"name": "kyeon.exe", "url": "https://github.com/x/y/releases/download/v0.9.9/kyeon.exe", "sha256": "a" * 64, "size": 1}
        with mock.patch.object(self.M, "ROOT", repo):
            self.assertEqual(self.M.from_tag("v0.9.9", rt)["runtime"], rt)
            self.assertNotIn("runtime", self.M.from_tag("v0.9.9"))

    def test_blobs_from_dir_reads_the_working_folder(self):
        repo = self.make_repo("0.9.9", name="wd")
        version, blobs = self.M.blobs_from_dir(repo)
        self.assertEqual(version, "0.9.9")
        self.assertEqual(sorted(blobs), ["CHANGELOG.md", "README.md", "data/plan.json", "fonts/F.otf", "fonts/LICENSE.txt", "kyeon.py"])
        self.git(repo, "tag", "v0.9.9")
        with mock.patch.object(self.M, "ROOT", repo):
            v2, from_git = self.M.blobs_for_tag("v0.9.9")
        self.assertEqual(blobs, from_git)  # 작업 폴더와 태그의 내용이 같으면 같은 파일 묶음이 나온다

    def test_plan_part_files_are_distributed_from_the_tag_and_from_the_folder(self):
        repo = self.make_repo("0.9.9", name="parts")
        write_files(repo, {"data/plan-2.json": b'{"days": []}', "data/plan-1001.json": b'{"days": []}', "data/plan-x.json": b"{}",
                           "data/other.json": b"{}"})
        self.git(repo, "add", "-A")
        self.git(repo, "commit", "-q", "-m", "parts")
        self.git(repo, "tag", "v0.9.9")
        want = ["CHANGELOG.md", "README.md", "data/plan-1001.json", "data/plan-2.json", "data/plan.json", "fonts/F.otf", "fonts/LICENSE.txt", "kyeon.py"]
        _v, from_dir = self.M.blobs_from_dir(repo)
        with mock.patch.object(self.M, "ROOT", repo):
            _v, from_git = self.M.blobs_for_tag("v0.9.9")
            m = self.M.from_tag("v0.9.9")
        self.assertEqual(sorted(from_dir), want)           # plan-x.json, other.json 은 올리지 않는다
        self.assertEqual(sorted(from_git), want)
        parsed = K.parse_manifest(json.dumps(m).encode("utf-8"), "https://raw.githubusercontent.com/o/r/main/latest.json")
        self.assertIn("data/plan-1001.json", parsed["files"])      # 클라이언트도 이 경로를 허용한다

    def test_build_is_deterministic(self):
        blobs = {"kyeon.py": app_src("1.0.0"), "data/plan.json": b"{}", "README.md": b"r"}
        a = self.M.build_manifest(dict(blobs), "1.0.0", "v1.0.0", "2026-10-12", ["n"])
        b = self.M.build_manifest(dict(reversed(list(blobs.items()))), "1.0.0", "v1.0.0", "2026-10-12", ["n"])
        self.assertEqual(json.dumps(a), json.dumps(b))
        with self.assertRaises(SystemExit):
            self.M.build_manifest({"kyeon.py": b"x"}, "1.0.0", "v1.0.0", "d", [])


class CliTests(Base):
    """kyeon.py 를 폴더에 복사해 실제 명령줄로 돌린다(그 폴더가 곧 설치 폴더)."""

    def setUp(self):
        super().setUp()
        self.real = (ROOT / "kyeon.py").read_text(encoding="utf-8")
        self.env = dict(os.environ, KYEON_STATE_DIR=str(self.state_dir), PYTHONIOENCODING="utf-8")
        self.env.pop("KYEON_UPDATE_URL", None)

    def run_cli(self, *args, input_text=None):
        return subprocess.run([sys.executable, "-X", "utf8", str(self.app / "kyeon.py"), *args], env=self.env,
                              capture_output=True, text=True, encoding="utf-8", timeout=120, input=input_text)

    def future_release(self, version="9.9.9", plan=PLAN_OLD):
        """지금 코드의 복사본에서 버전만 올린 릴리스(받아도 계속 돌아가는 프로그램)."""
        new_src = self.real.replace(f'__version__ = "{K.__version__}"', f'__version__ = "{version}"')
        self.assertTrue((new_src != self.real) == (version != K.__version__))  # 큰 문자열을 출력하지 않도록 assertTrue
        files = {"kyeon.py": new_src.encode("utf-8"), "data/plan.json": plan.encode()}
        return write_release(self.rel, version, files).parent

    def install_current(self, plan=PLAN_OLD):
        (self.app / "kyeon.py").write_text(self.real, encoding="utf-8")
        write_files(self.app, {"data/plan.json": plan.encode()})

    def test_update_check_reports_new_and_current(self):
        self.install_current()
        r = self.run_cli("--update-check", "--update-url", str(self.future_release()))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("새 버전이 있습니다: 9.9.9", r.stdout)
        self.assertIn("새 기능 하나", r.stdout)
        r = self.run_cli("--update-check", "--update-url", str(self.future_release(K.__version__)))
        self.assertIn("최신 버전입니다", r.stdout)

    def test_update_check_failure_exits_with_2(self):
        self.install_current()
        r = self.run_cli("--update-check", "--update-url", str(self.rel / "none"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("확인하지 못했습니다", r.stdout)

    def test_update_then_rollback(self):
        self.install_current()
        src = self.future_release()
        r = self.run_cli("--update", "--update-url", str(src), input_text="n\n")
        self.assertEqual((r.returncode, "취소했습니다" in r.stdout), (1, True))
        self.assertEqual(self.run_cli("--version").stdout.strip(), f"켠 {K.__version__}")
        r = self.run_cli("--update", "--yes", "--update-url", str(src))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("업데이트했습니다: 9.9.9", r.stdout)
        self.assertEqual(self.run_cli("--version").stdout.strip(), "켠 9.9.9")
        r = self.run_cli("--update", "--yes", "--update-url", str(src))
        self.assertIn("이미 최신", r.stdout)
        r = self.run_cli("--rollback")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.run_cli("--version").stdout.strip(), f"켠 {K.__version__}")

    def test_rollback_without_backup(self):
        self.install_current()
        r = self.run_cli("--rollback")
        self.assertEqual(r.returncode, 2)
        self.assertIn("되돌릴 백업이 없습니다", r.stdout)

    def test_empty_folder_gets_installed_from_just_kyeon_py(self):
        """빈 폴더에 kyeon.py 만 있어도 --update 가 나머지를 채운다(install.ps1 이 이 방식으로 설치한다)."""
        (self.app / "kyeon.py").write_text(self.real, encoding="utf-8")
        files = {"kyeon.py": self.real.encode("utf-8"), "data/plan.json": PLAN_NEW.encode(), "README.md": b"# r"}
        write_release(self.rel, K.__version__, files)
        r = self.run_cli("--update", "--yes", "--update-url", str(self.rel))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((self.app / "data" / "plan.json").read_text(), PLAN_NEW)
        self.assertEqual((self.app / "README.md").read_bytes(), b"# r")
        r = self.run_cli("--check")  # 시험용 계획표는 내용이 비어 종료 코드는 1 이지만, 계획표를 읽어 2일로 센다
        self.assertIn("총 2일", r.stdout)

    def test_older_release_is_not_installed_over_a_newer_copy(self):
        self.install_current()
        r = self.run_cli("--update", "--yes", "--update-url", str(self.future_release("0.0.1")))
        self.assertEqual(r.returncode, 0)
        self.assertIn("더 새 버전", r.stdout)
        self.assertEqual(self.run_cli("--version").stdout.strip(), f"켠 {K.__version__}")


if __name__ == "__main__":
    unittest.main()
