"""켠 (kyeon) - 화면 한켠, 마음 한가운데

조용히 백그라운드에서 돌다가, 로그온할 때와 매일 자정에 오늘의 말씀(개역한글)을 위젯으로 띄웁니다.
읽고 나서 '오늘은 닫기'를 누르면 그날은 다시 뜨지 않습니다.
표준 라이브러리(tkinter)만 사용하며 Windows 에서 동작합니다.
Python 이 없는 PC 에는 kyeon.exe(Python 실행 환경만 든 껍데기, tools/launcher.py)로 줍니다. exe 는 옆의 이 파일을 그대로
실행하고, 내려받은 exe 를 처음 실행하면 --setup 이 돌아 사용자 폴더에 설치합니다(아래 '설치와 제거').

  python kyeon.py              실행(이미 떠 있으면 위젯을 다시 보여 줌)
  python kyeon.py --install    로그온 시 자동 실행 등록 + 지금 실행
  python kyeon.py --uninstall  자동 실행 해제 + 종료(--purge 를 더하면 exe 설치 폴더도 지움)
  kyeon.exe --setup            내려받은 exe 를 설치(exe 를 두 번 누르면 저절로 이 단계가 됨)
  python kyeon.py --quit       실행 중인 위젯 종료
  python kyeon.py --status     등록/진행 상태 확인
  python kyeon.py --check      데이터 점검 + 오늘의 말씀을 콘솔에 출력
  python kyeon.py --reset      1일차부터 다시 시작
  python kyeon.py --day N      N일차를 미리보기(상태를 바꾸지 않음)
  python kyeon.py --routes     고를 수 있는 읽는 길(전체 순서, 시기별, 테마별, 갈래별) 목록
  python kyeon.py --route ID   읽는 길을 바꿈(--day 와 함께 쓰면 그 길의 N일차를 미리보기)
  python kyeon.py --update-check  새 버전이 있는지 확인
  python kyeon.py --update     새 버전으로 업데이트(--yes 로 확인 질문 생략)
  python kyeon.py --rollback   직전 버전으로 되돌리기
  python kyeon.py --version    버전 표시
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import zlib
from datetime import date, datetime, timedelta
from pathlib import Path

__version__ = "0.4.0"   # 버전의 유일한 원본. 릴리스마다 올린다(docs/RELEASING.md)
TEXT_CREDIT = "성경 본문: 성경전서 개역한글판, 대한성서공회, 1961"   # 저작자 표시(성명표시권). 설정 창에 보인다. 바꾸지 않는다(NOTICE.md)
APP = "Kyeon"
LEGACY_APP = "DailyVerseWidget"  # 켠으로 이름을 바꾸기 전 버전의 자동 실행 값(설치·제거 때 함께 정리)
BASE = Path(__file__).resolve().parent
SCRIPT = BASE / "kyeon.py"
PLAN_FILE = BASE / "data" / "plan.json"
FONT_DIR = BASE / "fonts"   # 함께 배포하는 본문 글꼴(리디바탕). 설치하지 않고 이 프로그램 안에서만 쓴다
STATE_DIR = Path(os.environ.get("KYEON_STATE_DIR")
                 or (Path(os.environ.get("LOCALAPPDATA") or Path.home()) / APP))
RUN_KEY = os.environ.get("KYEON_RUN_KEY") or r"Software\Microsoft\Windows\CurrentVersion\Run"   # 환경변수는 시험용(임시 키로 바꿔 쓴다)
FROZEN = bool(getattr(sys, "frozen", False))  # PyInstaller 로 묶은 kyeon.exe 로 돌 때(Python 이 없는 PC 에 주는 배포본)
UNINSTALL_KEY = (os.environ.get("KYEON_UNINSTALL_KEY")
                 or r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Kyeon")   # 설정 > 앱 목록에 나오는 항목
INSTALL_DIR = Path(os.environ.get("KYEON_INSTALL_DIR")
                   or (Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Programs" / APP))
START_MENU_DIR = Path(os.environ.get("KYEON_START_MENU_DIR")
                      or (Path(os.environ.get("APPDATA") or Path.home()) / "Microsoft" / "Windows" / "Start Menu" / "Programs"))
SHORTCUT_NAME = "켠.lnk"
WEEKDAY = "월화수목금토일"

ALWAYS_ON_TOP = True          # 닫을 때까지 다른 창 위에 둠
SHOW_DELAY_STARTUP_MS = 4000  # 로그온 직후 바탕화면이 준비될 때까지 잠시 대기
TICK_MS = 1000                # 날짜 변경/신호 확인 주기


# ───────────────────────── 로그 / 상태 ─────────────────────────
def log(msg: str, directory: Path | None = None) -> None:
    try:
        d = directory or STATE_DIR
        d.mkdir(parents=True, exist_ok=True)
        f = d / "widget.log"
        if f.exists() and f.stat().st_size > 200_000:
            f.write_text("", encoding="utf-8")
        with f.open("a", encoding="utf-8") as fp:
            fp.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")
    except OSError:
        pass


# 설정 창에서 바꾸는 값과 기본값. 허용 값이 정해진 항목은 SETTING_CHOICES 에 적는다.
SETTING_DEFAULTS = {"skin": "default", "theme": "auto", "font": "normal", "corner": "br",
                    "topmost": ALWAYS_ON_TOP, "recite": False, "recite_level": 1,
                    "update_check": True, "update_url": "",   # update_url: 비우면 GitHub(UPDATE_URL), 설정 창에는 없는 고급 값
                    "route": "all"}   # 읽는 길: all(전체 순서) | era:<id> | theme:<id> | section:<갈래 이름>. 고르는 창은 RouteWindow
SETTING_CHOICES = {"skin": ("default", "excel"), "theme": ("auto", "light", "dark"),
                   "font": ("small", "normal", "large"), "corner": ("br", "bl", "tr", "tl"),
                   "recite_level": (1, 2, 3)}


class State:
    """시작일(1일차 기준), '오늘 닫은 날짜', 설정 값을 저장하고, 다른 프로세스의 신호를 받는다."""

    def __init__(self, directory: Path = STATE_DIR):
        self.dir = Path(directory)
        self.file = self.dir / "state.json"
        self.signal = self.dir / "signal.txt"
        try:
            self.data = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.file)

    def reload(self) -> None:
        """다른 프로세스(--route, --skin 등)가 파일에 쓴 값을 다시 읽는다. 읽지 못하면 지금 값을 그대로 둔다."""
        try:
            self.data = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass

    @property
    def route_positions(self) -> dict[str, int]:
        """길마다 마지막으로 읽던 자리(0부터). 길을 바꿔도 돌아오면 그 자리에서 이어 읽는다."""
        v = self.data.get("route_pos")
        if not isinstance(v, dict):
            return {}
        return {k: n for k, n in v.items() if isinstance(n, int) and not isinstance(n, bool) and n >= 0}

    def set_route_position(self, route_id: str, pos: int) -> None:
        d = self.route_positions
        d[route_id] = max(0, int(pos))
        self.data["route_pos"] = d
        self.save()

    def forget_route_positions(self) -> None:
        if self.data.pop("route_pos", None) is not None:
            self.save()

    def _get_date(self, key: str) -> date | None:
        try:
            return date.fromisoformat(self.data[key])
        except (KeyError, ValueError, TypeError):
            return None

    @property
    def start_date(self) -> date | None:
        return self._get_date("start_date")

    @start_date.setter
    def start_date(self, d: date) -> None:
        self.data["start_date"] = d.isoformat()
        self.save()

    @property
    def dismissed_date(self) -> date | None:
        return self._get_date("dismissed_date")

    @dismissed_date.setter
    def dismissed_date(self, d: date | None) -> None:
        if d is None:
            self.data.pop("dismissed_date", None)
        else:
            self.data["dismissed_date"] = d.isoformat()
        self.save()

    def get(self, key: str):
        """설정 값. 저장된 값이 없거나 허용 범위 밖이면 기본값."""
        default = SETTING_DEFAULTS[key]
        v = self.data.get(key, default)
        if isinstance(default, str) and not isinstance(v, str):
            return default
        choices = SETTING_CHOICES.get(key)
        if choices is not None and v not in choices:
            return default
        return bool(v) if isinstance(default, bool) else v

    def set(self, key: str, value) -> None:
        if key not in SETTING_DEFAULTS:
            raise KeyError(key)
        self.data[key] = value
        self.save()

    @property
    def recite(self) -> bool:
        return self.get("recite")

    @recite.setter
    def recite(self, on: bool) -> None:
        self.set("recite", bool(on))

    @property
    def recite_level(self) -> int:
        return self.get("recite_level")

    @recite_level.setter
    def recite_level(self, lv: int) -> None:
        self.set("recite_level", int(lv))

    # ---- 업데이트 확인 기록(설정이 아니라 실행 기록. 설정 창에 '마지막 확인' 으로 보여 줌) ----
    @property
    def update_checked_at(self) -> float | None:
        v = self.data.get("update_checked_at")
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    def mark_update_checked(self, now: float | None = None) -> None:
        self.data["update_checked_at"] = time.time() if now is None else now
        self.save()

    @property
    def update_skipped(self) -> str:
        """'나중에' 를 누른 버전. 이보다 새 버전이 나오기 전까지 안내 줄을 다시 띄우지 않는다."""
        return str(self.data.get("update_skipped") or "")

    @update_skipped.setter
    def update_skipped(self, version: str) -> None:
        self.data["update_skipped"] = version
        self.save()

    def send(self, cmd: str) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.signal.write_text(cmd, encoding="utf-8")

    def take_signal(self) -> str | None:
        try:
            cmd = self.signal.read_text(encoding="utf-8").strip()
            self.signal.unlink()
            return cmd or None
        except OSError:
            return None


def day_index(start: date, today: date, n: int) -> int:
    """start 가 1일차. n일(계획의 전체 일수)을 다 읽으면 처음부터 다시 돈다."""
    return max(0, (today - start).days) % n


PLAN_PART_RE = re.compile(r"plan-(\d+)\.json")


def plan_part_files(path: Path = PLAN_FILE) -> list[Path]:
    """plan.json 뒤에 이어 붙는 같은 폴더의 plan-<첫 일차>.json 들. 일차 순서로 정렬한다."""
    found = []
    for p in Path(path).parent.glob("plan-*.json"):
        m = PLAN_PART_RE.fullmatch(p.name)
        if m:
            found.append((int(m.group(1)), p))
    return [p for _n, p in sorted(found)]


def load_plan(path: Path = PLAN_FILE, parts: list[Path] | None = None) -> dict:
    """계획표. plan.json 이 첫 묶음(머리말과 길 정의 포함)이고, 같은 폴더의 plan-<첫 일차>.json 이 있으면 그 날들을 이어 붙인다
    (parts 로 이어 붙일 파일을 직접 줄 수 있다). 날 번호는 합쳐서 1..N 으로 빈틈없이 이어져야 한다."""
    plan = json.loads(path.read_text(encoding="utf-8"))
    days = list(plan["days"])
    for p in (plan_part_files(path) if parts is None else parts):
        extra = json.loads(Path(p).read_text(encoding="utf-8"))
        if not isinstance(extra, dict) or not isinstance(extra.get("days"), list):
            raise ValueError(f"{Path(p).name} 의 모양이 다릅니다")
        days += extra["days"]
    if not days or [d["day"] for d in days] != list(range(1, len(days) + 1)):
        raise ValueError("plan.json 의 day 번호가 1..N 연속이 아닙니다")
    plan["days"] = days
    return plan


# ───────────────────────── 읽는 길 ─────────────────────────
ROUTE_ALL = "all"
ROUTE_KIND_NAMES = {"all": "전체 순서", "era": "시기별", "theme": "테마별", "section": "갈래별"}


def build_routes(plan: dict) -> list[dict]:
    """읽는 길 목록. 길마다 {id, kind, name, about, idxs}. idxs 는 plan["days"] 의 색인이고 원래 날 순서를 따른다.
    맨 앞은 늘 전체 순서. 시기·테마는 계획표 머리말의 routes 정의와 날마다의 era·themes 가 있을 때만 생기고(없는 옛 계획표는
    전체 순서와 갈래만), 갈래는 section 값으로 만든다. 날이 하나도 없는 길은 뺀다."""
    days = plan["days"]
    routes = [{"id": ROUTE_ALL, "kind": "all", "name": ROUTE_KIND_NAMES["all"], "about": "원래 순서대로 하루에 하나",
               "idxs": list(range(len(days)))}]
    meta = plan.get("routes") or {}
    for kind in ("era", "theme"):
        for r in meta.get(kind) or []:
            rid = r.get("id") if isinstance(r, dict) else None
            if not (isinstance(rid, str) and rid and r.get("name")):
                continue
            idxs = [i for i, d in enumerate(days)
                    if rid in ((d.get("themes") or []) if kind == "theme" else [d.get("era")])]
            if idxs:
                routes.append({"id": f"{kind}:{rid}", "kind": kind, "name": str(r["name"]),
                               "about": str(r.get("about") or ""), "idxs": idxs})
    sections: dict[str, list[int]] = {}
    for i, d in enumerate(days):
        if d.get("section"):
            sections.setdefault(d["section"], []).append(i)
    for name, idxs in sections.items():
        routes.append({"id": f"section:{name}", "kind": "section", "name": name, "about": "", "idxs": idxs})
    return routes


def find_route(routes: list[dict], route_id: str | None) -> dict:
    """id 로 길을 찾는다. 없으면(계획표에서 사라진 길 등) 전체 순서."""
    for r in routes:
        if r["id"] == route_id:
            return r
    return routes[0]


def route_label(route: dict) -> str:
    return route["name"] if route["kind"] == "all" else f"{ROUTE_KIND_NAMES[route['kind']]} · {route['name']}"


def switch_route(state: State, routes: list[dict], new_id: str, today: date, cur_id: str | None = None) -> dict:
    """읽는 길을 바꾼다. 떠나는 길의 읽던 자리는 기억해 두고, 새 길은 기억한 자리(처음이면 1일차)에서 이어 읽는다.
    start_date 는 '지금 길의 1일차인 날'이므로 새 길의 자리에 맞춰 옮긴다."""
    cur = find_route(routes, cur_id if cur_id is not None else state.get("route"))
    new = find_route(routes, new_id)
    if new["id"] == cur["id"]:
        return new
    start = state.start_date or today
    state.set_route_position(cur["id"], day_index(start, today, len(cur["idxs"])))
    pos = state.route_positions.get(new["id"], 0) % len(new["idxs"])
    state.start_date = today - timedelta(days=pos)
    state.dismissed_date = None
    state.set("route", new["id"])
    return new


# ───────────────────────── Windows 보조 ─────────────────────────
def acquire_single_instance(name: str = f"Local\\{APP}-{zlib.crc32(str(STATE_DIR).encode()):08x}"):
    """이름 있는 뮤텍스로 중복 실행 방지(상태 폴더별). (핸들, 이미 실행 중 여부)"""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    handle = k32.CreateMutexW(None, False, name)
    return handle, ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS


def work_area() -> tuple[int, int, int, int]:
    """주 모니터의 작업 영역(작업 표시줄 제외) left, top, right, bottom."""
    class RECT(ctypes.Structure):
        _fields_ = [(n, ctypes.c_long) for n in ("left", "top", "right", "bottom")]

    r = RECT()
    ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)  # SPI_GETWORKAREA
    return r.left, r.top, r.right, r.bottom


def is_dark() -> bool:
    forced = os.environ.get("KYEON_THEME", "").lower()
    if forced in ("dark", "light"):
        return forced == "dark"
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def load_bundled_fonts(directory: Path = FONT_DIR) -> int:
    """폴더의 글꼴(.otf, .ttf)을 이 프로세스에서만 쓰도록 등록한다. PC 에 설치되지 않고 프로세스가 끝나면 사라진다.
    등록한 글꼴 수를 돌려준다(폴더가 없거나 등록에 실패하면 0)."""
    n = 0
    try:
        files = sorted(Path(directory).glob("*.[ot]tf"))
    except OSError:
        return 0
    for f in files:
        try:
            n += bool(ctypes.windll.gdi32.AddFontResourceExW(str(f), 0x10, 0))  # 0x10 = FR_PRIVATE
        except (OSError, AttributeError):
            pass
    return n


def pythonw_path() -> str:
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return str(w if w.exists() else exe)


def self_command() -> list[str]:
    """이 프로그램을 다시 실행하는 명령. exe 로 묶여 있으면 exe 자신, 아니면 pythonw 와 kyeon.py."""
    return [sys.executable] if FROZEN else [pythonw_path(), str(SCRIPT)]


def autostart_command() -> str:
    return " ".join(f'"{c}"' for c in self_command()) + " --startup"


def autostart_get(name: str = APP, key_path: str = RUN_KEY) -> str | None:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def autostart_set(command: str, name: str = APP, key_path: str = RUN_KEY) -> None:
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_SZ, command)


def autostart_remove(name: str = APP, key_path: str = RUN_KEY) -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, name)
        return True
    except OSError:
        return False


def child_env() -> dict | None:
    """exe 가 같은 exe 를 다시 띄울 때, 이 프로세스가 풀어 둔 임시 폴더를 물려받지 않고 새로 풀게 한다.
    (물려받으면 이 프로세스가 끝날 때 임시 폴더가 지워져 새 프로세스가 죽는다. PyInstaller 6.9 이상의 환경변수)"""
    return dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1") if FROZEN else None


def spawn_detached(*args: str, exe: Path | str | None = None) -> None:
    """새 프로세스로 켠을 띄운다(이 프로세스가 끝나도 계속 산다). exe 를 주면 그 실행 파일로 띄운다."""
    flags = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED | NEW_PROCESS_GROUP | NO_WINDOW
    cmd = [str(exe)] if exe else self_command()
    subprocess.Popen([*cmd, *args], creationflags=flags, close_fds=True, env=child_env())


def release_handle(handle) -> None:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    k32.CloseHandle(handle)


def wait_for_instance_exit(timeout: float = 20.0):
    """업데이트 뒤 다시 뜰 때: 이전 위젯이 끝나 뮤텍스가 풀릴 때까지 기다렸다가 잡는다. (핸들, 아직 실행 중 여부)"""
    end = time.time() + timeout
    while True:
        handle, running = acquire_single_instance()
        if not running or time.time() >= end:
            return handle, running
        release_handle(handle)  # 열린 핸들이 남아 있으면 이전 프로세스가 끝나도 뮤텍스가 사라지지 않는다
        time.sleep(0.3)


# ───────────────────────── 업데이트 ─────────────────────────
# 새 버전 정보(latest.json)에는 파일마다 SHA-256 이 적혀 있다. 달라진 파일만 내려받아 해시를 확인하고,
# 문법과 계획표 형식까지 본 뒤에야 바꿔 넣는다. 중간에 실패하면 이전 파일로 되돌린다. 빈 폴더에서 실행하면 설치가 된다.
UPDATE_URL = "https://raw.githubusercontent.com/kcc920926-droid/kyeon/main/latest.json"
UPDATE_FIRST_CHECK_MS = 8000   # 로그온으로 시작한 뒤 이만큼 지나서 한 번 확인(시작을 느리게 하지 않으려고)
UPDATE_CHECK_TIMEOUT = 5       # 새 버전 확인(작은 json 하나)
UPDATE_FILE_TIMEOUT = 30       # 파일 내려받기
UPDATE_MAX_MANIFEST = 256 * 1024
UPDATE_MAX_FILE = 20 * 1024 * 1024
# 업데이트가 쓸 수 있는 파일 이름. 받은 목록이 무슨 경로를 말해도 이 모양이 아니면 거부한다(폴더 밖, 숨김 파일, 장치 이름 차단)
UPDATE_PATH_RE = re.compile(r"(?:[A-Za-z0-9_][A-Za-z0-9_-]*\.(?:py|bat|md|txt)|data/[A-Za-z0-9_][A-Za-z0-9_-]*\.json"
                            r"|fonts/[A-Za-z0-9_][A-Za-z0-9_-]*\.(?:otf|ttf|txt))")
WIN_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
_URL_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://")


class UpdateError(Exception):
    """업데이트 확인·적용 실패. 메시지는 사용자에게 그대로 보여 줄 수 있는 한국어 문장."""


def parse_version(text) -> tuple | None:
    m = re.fullmatch(r"(\d{1,4})\.(\d{1,4})\.(\d{1,4})", str(text).strip())
    return tuple(int(x) for x in m.groups()) if m else None


def update_source(state: State, override: str | None = None) -> str:
    """새 버전 정보의 위치: 명령줄 값 > 환경변수 KYEON_UPDATE_URL > 저장된 update_url > GitHub. 주소 또는 폴더 경로."""
    return override or os.environ.get("KYEON_UPDATE_URL") or state.get("update_url") or UPDATE_URL


def _check_url(url: str) -> None:
    from urllib.parse import urlsplit
    s = urlsplit(url)
    host = (s.hostname or "").lower()
    if s.scheme == "https" and host:
        return
    if s.scheme == "http" and host in ("127.0.0.1", "localhost", "::1"):
        return  # 개발·시험용 로컬 서버만 http 허용
    raise UpdateError("https 주소만 쓸 수 있습니다")


def fetch(location: str, limit: int, timeout: float = UPDATE_CHECK_TIMEOUT) -> bytes:
    """https 주소(또는 로컬 경로)의 내용을 limit 바이트까지 읽는다. 리다이렉트도 https 만 따라간다."""
    if _URL_RE.match(location):
        import http.client
        import urllib.error
        import urllib.request

        class Guard(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                _check_url(newurl)
                return super().redirect_request(req, fp, code, msg, headers, newurl)

        _check_url(location)
        req = urllib.request.Request(location, headers={"User-Agent": f"kyeon/{__version__}"})
        try:
            with urllib.request.build_opener(Guard).open(req, timeout=timeout) as r:
                data = r.read(limit + 1)
        except urllib.error.HTTPError as e:
            raise UpdateError(f"서버가 {e.code} 로 응답했습니다") from e
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
            raise UpdateError("서버에 연결하지 못했습니다") from e
    else:
        try:
            with open(location, "rb") as fp:
                data = fp.read(limit + 1)
        except OSError as e:
            raise UpdateError("파일을 읽지 못했습니다") from e
    if len(data) > limit:
        raise UpdateError("받은 내용이 너무 큽니다")
    return data


def manifest_location(source: str) -> str:
    """원본이 폴더 경로면 그 안의 latest.json 을 가리킨다."""
    if not _URL_RE.match(source) and os.path.isdir(source):
        return os.path.join(source, "latest.json")
    return source


def _safe_path(path) -> bool:
    return (isinstance(path, str) and UPDATE_PATH_RE.fullmatch(path) is not None
            and path.split("/")[-1].split(".")[0].lower() not in WIN_RESERVED)


def parse_manifest(raw: bytes, location: str) -> dict:
    """latest.json 을 검사해 정리한 dict 로 돌려준다. 모양이 조금이라도 다르면 UpdateError."""
    from urllib.parse import urlsplit
    try:
        m = json.loads(raw.decode("utf-8"))
    except ValueError as e:  # UnicodeDecodeError 도 ValueError
        raise UpdateError("업데이트 정보를 읽지 못했습니다") from e
    if not isinstance(m, dict) or m.get("app") != "kyeon" or m.get("schema") != 1:
        raise UpdateError("켠의 업데이트 정보가 아닙니다")
    vt = parse_version(m.get("version"))
    if vt is None:
        raise UpdateError("업데이트 정보의 버전 표기가 올바르지 않습니다")
    files = m.get("files")
    if not isinstance(files, dict) or "kyeon.py" not in files:
        raise UpdateError("업데이트 정보의 파일 목록이 올바르지 않습니다")
    clean = {}
    for path, info in files.items():
        sha, size = (info.get("sha256"), info.get("size")) if isinstance(info, dict) else (None, None)
        if not _safe_path(path):
            raise UpdateError(f"허용되지 않은 파일 이름입니다: {str(path)[:40]}")
        if (not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha) or not isinstance(size, int)
                or isinstance(size, bool) or not 0 <= size <= UPDATE_MAX_FILE):
            raise UpdateError(f"{path} 의 해시나 크기가 올바르지 않습니다")
        clean[path] = {"sha256": sha, "size": size}
    if _URL_RE.match(location):
        base = m.get("base_url") or location.rsplit("/", 1)[0] + "/"
        if not isinstance(base, str) or not base.endswith("/"):
            raise UpdateError("내려받을 주소가 올바르지 않습니다")
        _check_url(base)
        if urlsplit(base).netloc.lower() != urlsplit(location).netloc.lower():
            raise UpdateError("업데이트 정보와 파일의 서버가 다릅니다")
    else:  # 폴더에서 받을 때는 latest.json 이 있는 폴더가 곧 원본이다
        base = os.path.dirname(os.path.abspath(location))
    notes = m.get("notes") if isinstance(m.get("notes"), list) else []
    mp = re.fullmatch(r"(\d+)\.(\d+)", str(m.get("min_python") or ""))
    return {"version": m["version"].strip(), "vt": vt, "tag": str(m.get("tag") or "")[:40],
            "released": str(m.get("released") or "")[:20], "notes": [str(n)[:200] for n in notes[:12]],
            "min_python": tuple(int(x) for x in mp.groups()) if mp else None, "base": base, "files": clean}


def check_update(source: str, current: str = __version__, fetch_fn=None) -> dict | None:
    """원본의 버전이 현재보다 새로우면 정리된 정보(dict), 아니면 None. 실패하면 UpdateError."""
    loc = manifest_location(source)
    m = parse_manifest((fetch_fn or fetch)(loc, UPDATE_MAX_MANIFEST, UPDATE_CHECK_TIMEOUT), loc)
    cur = parse_version(current)
    if cur is not None and m["vt"] <= cur:
        return None
    check_python(m)
    return m


def check_python(m: dict) -> None:
    if m["min_python"] and sys.version_info[:2] < m["min_python"]:
        need = ".".join(map(str, m["min_python"]))
        raise UpdateError(f"새 버전 {m['version']} 은 Python {need} 이상이 필요합니다")


def _local(base_dir: Path, path: str) -> Path:
    return Path(base_dir).joinpath(*path.split("/"))


def sha256_of(path: Path) -> str | None:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def plan_changes(m: dict, base_dir: Path = BASE) -> list[str]:
    """목록과 내용이 다르거나 없는 파일. kyeon.py 는 마지막에 바꾸도록 맨 뒤에 둔다."""
    out = [p for p, info in m["files"].items() if sha256_of(_local(base_dir, p)) != info["sha256"]]
    return sorted(out, key=lambda p: p == "kyeon.py")


def _file_url(m: dict, path: str) -> str:
    return m["base"] + path if _URL_RE.match(m["base"]) else str(_local(Path(m["base"]), path))


def missing_modules(src: str) -> list[str]:
    """프로그램이 가져다 쓰는 모듈 중 이 실행 환경에 없는 것. exe 로 묶인 켠은 묶을 때 넣은 표준 라이브러리만 쓸 수 있어서,
    새 버전이 그 밖의 모듈을 쓰기 시작하면 받아서 바꾸기 전에 알아야 한다."""
    import ast
    import importlib.util
    names: set[str] = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module and node.module != "__future__":
            names.add(node.module)
    out = []
    for name in sorted(names):
        try:
            found = importlib.util.find_spec(name) is not None
        except (ImportError, ValueError, AttributeError):
            found = False
        if not found:
            out.append(name)
    return out


def _is_plan_file(path: str) -> bool:
    return path == "data/plan.json" or (path.startswith("data/") and PLAN_PART_RE.fullmatch(path[5:]) is not None)


def _verify_staged(m: dict, stage: Path, changes: list[str], base_dir: Path = BASE) -> None:
    """바꿔 넣기 전에 받은 파일이 쓸 만한지 본다(프로그램은 문법과 버전, 계획표는 형식)."""
    if "kyeon.py" in changes:
        src = (stage / "kyeon.py").read_text(encoding="utf-8")
        try:
            compile(src, "kyeon.py", "exec")
        except (SyntaxError, ValueError) as e:
            raise UpdateError("받은 프로그램 파일에 문제가 있어 중단했습니다") from e
        missing = missing_modules(src)
        if missing:
            raise UpdateError(f"새 버전은 이 PC 의 실행 환경에 없는 기능({', '.join(missing)})이 필요해 중단했습니다. "
                              "켠을 새로 내려받아 설치해 주세요")
        mm = re.search(r'^__version__ = "([^"]+)"', src, re.M)
        if not mm or mm.group(1) != m["version"]:
            raise UpdateError("받은 프로그램의 버전이 업데이트 정보와 달라 중단했습니다")
    if any(_is_plan_file(p) for p in changes):
        # 계획표는 plan.json 과 plan-<일차>.json 들을 이어 붙인 것이다. 이번에 받은 파일은 받은 것으로, 안 바뀐 파일은 지금 것으로 합쳐 본다
        def source(p: str) -> Path:
            return _local(stage if p in changes else base_dir, p)
        try:
            parts = sorted((p for p in m["files"] if _is_plan_file(p) and p != "data/plan.json"),
                           key=lambda p: int(PLAN_PART_RE.fullmatch(p[5:]).group(1)))
            load_plan(source("data/plan.json"), [source(p) for p in parts])
        except (OSError, ValueError, KeyError, TypeError) as e:
            raise UpdateError("받은 계획표에 문제가 있어 중단했습니다") from e
    for path in changes:  # 글꼴 파일은 OpenType/TrueType 머리말(OTTO, 0x00010000)로 시작해야 한다
        if path.startswith("fonts/") and path.endswith((".otf", ".ttf")):
            with open(_local(stage, path), "rb") as fp:
                if fp.read(4) not in (b"OTTO", b"\x00\x01\x00\x00"):
                    raise UpdateError(f"받은 {path} 가 글꼴 파일이 아니어서 중단했습니다")


def _restore(base_dir: Path, from_dir: Path, paths: list[str]) -> None:
    for path in paths:
        src, target = _local(from_dir, path), _local(base_dir, path)
        tmp = target.with_name(target.name + ".kyeon-new")
        try:
            if src.is_file():
                shutil.copyfile(src, tmp)
                os.replace(tmp, target)
            else:  # 이번 업데이트로 새로 생긴 파일
                target.unlink()
        except OSError:
            log(f"복원 실패: {path}\n{traceback.format_exc()}")


def apply_update(m: dict, base_dir: Path = BASE, state_dir: Path = STATE_DIR, fetch_fn=None,
                 current: str = __version__) -> list[str]:
    """달라진 파일을 받아 검증하고 바꿔 넣는다. 바꾼 파일 경로를 돌려주고, 실패하면 UpdateError(원래 상태 유지)."""
    fetch_fn = fetch_fn or fetch
    changes = plan_changes(m, base_dir)
    if not changes:
        return []
    stage = Path(state_dir) / "update" / m["version"]
    backup = Path(state_dir) / "backup" / current
    shutil.rmtree(stage, ignore_errors=True)
    try:
        for path in changes:
            info = m["files"][path]
            data = fetch_fn(_file_url(m, path), info["size"], UPDATE_FILE_TIMEOUT)
            if len(data) != info["size"] or hashlib.sha256(data).hexdigest() != info["sha256"]:
                raise UpdateError(f"내려받은 {path} 가 업데이트 정보와 달라 중단했습니다")
            dest = _local(stage, path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        _verify_staged(m, stage, changes, base_dir)
        shutil.rmtree(backup, ignore_errors=True)
        for path in changes:  # 지금 파일을 백업해 둔다(--rollback 으로 되돌릴 수 있게)
            src = _local(base_dir, path)
            if src.is_file():
                _local(backup, path).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, _local(backup, path))
        done: list[str] = []
        try:
            for path in changes:
                target = _local(base_dir, path)
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp = target.with_name(target.name + ".kyeon-new")
                shutil.copyfile(_local(stage, path), tmp)
                os.replace(tmp, target)
                done.append(path)
        except OSError as e:
            for path in changes:  # 바꾸다 만 임시 파일을 치운다
                try:
                    t = _local(base_dir, path)
                    t.with_name(t.name + ".kyeon-new").unlink()
                except OSError:
                    pass
            _restore(base_dir, backup, done)
            raise UpdateError("파일을 바꾸지 못해 이전 상태로 되돌렸습니다. 폴더에 쓸 권한이 있는지 확인하세요") from e
        _prune_backups(Path(state_dir) / "backup")
        try:  # 다시 뜬 위젯이 '업데이트했습니다' 를 한 번 보여 주도록
            (Path(state_dir) / "last_update.json").write_text(
                json.dumps({"from": current, "version": m["version"], "notes": m["notes"]}, ensure_ascii=False),
                encoding="utf-8")
        except OSError:
            pass
        log(f"업데이트 {current} -> {m['version']}: {', '.join(changes)}")
        return changes
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _prune_backups(root: Path, keep: int = 3) -> None:
    try:
        dirs = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return
    for p in dirs[keep:]:
        shutil.rmtree(p, ignore_errors=True)


def rollback(base_dir: Path = BASE, state_dir: Path = STATE_DIR) -> tuple[str, list[str]]:
    """가장 최근 백업(업데이트 직전 파일)으로 되돌린다. (되돌린 버전, 파일 경로들)"""
    root = Path(state_dir) / "backup"
    try:
        newest = max((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime)
    except (OSError, ValueError):
        raise UpdateError("되돌릴 백업이 없습니다") from None
    paths = [p.relative_to(newest).as_posix() for p in newest.rglob("*") if p.is_file()]
    paths = [p for p in paths if _safe_path(p)]
    if not paths:
        raise UpdateError("되돌릴 백업이 없습니다")
    _restore(base_dir, newest, paths)
    return newest.name, sorted(paths)


def read_last_update(state_dir: Path = STATE_DIR) -> dict | None:
    """방금 한 업데이트의 기록을 한 번만 읽는다(읽으면 지운다). 지금 실행 중인 버전과 맞을 때만."""
    f = Path(state_dir) / "last_update.json"
    try:
        info = json.loads(f.read_text(encoding="utf-8"))
        f.unlink()
    except (OSError, ValueError):
        return None
    ok = isinstance(info, dict) and info.get("version") == __version__
    return info if ok else None


# ───────────────────── 설치와 제거 (Python 없이 쓰는 exe 배포본) ─────────────────────
# kyeon.exe 는 Python 실행 환경만 담은 껍데기이고 프로그램 본체(kyeon.py)와 자료는 exe 옆 파일이다. 그래서 위의 업데이트가 그대로 통한다.
# 내려받은 exe 를 처음 실행하면 exe 안에 든 설치용 파일을 사용자 폴더에 풀고, 자동 실행·앱 목록·시작 메뉴에 등록한다.
INSTALLED_FILES = ("kyeon.exe", "kyeon.py", "README.md", "CHANGELOG.md", "install.bat", "uninstall.bat", "show.bat")
STATE_FILES = ("state.json", "signal.txt", "widget.log", "last_update.json")
MB_TOP = 0x10000 | 0x40000   # 메시지 창을 맨 앞에(MB_SETFOREGROUND | MB_TOPMOST)


def message_box(text: str, flags: int = 0x40) -> int:
    """윈도우 기본 메시지 창(tkinter 없이). 0x40 안내, 0x10 오류, 0x24 예/아니요. 누른 버튼을 돌려준다(예 = 6)."""
    try:
        return ctypes.windll.user32.MessageBoxW(None, text, "켠", flags | MB_TOP)
    except (OSError, AttributeError):
        return 0


def ask_yes_no(text: str) -> bool:
    return message_box(text, 0x24) == 6


def tell(text: str, error: bool = False) -> None:
    """콘솔에 쓰고, 콘솔이 없는 exe 에서는 메시지 창으로도 알린다."""
    print(text)
    if FROZEN:
        message_box(text, 0x10 if error else 0x40)


def attach_console() -> None:
    """exe 는 콘솔 없이 뜨므로, 터미널에서 옵션을 주어 실행했을 때 결과가 보이도록 부모의 콘솔에 붙는다."""
    if not FROZEN:
        return
    import io
    try:
        if not ctypes.windll.kernel32.AttachConsole(ctypes.c_uint(-1).value):  # ATTACH_PARENT_PROCESS
            return
        for name, mode, wrap in (("CONOUT$", "w", io.BufferedWriter), ("CONIN$", "r", io.BufferedReader)):
            raw = io._WindowsConsoleIO(name, mode)  # 파이썬이 콘솔 글자를 유니코드로 다루는 바로 그 입출력
            stream = io.TextIOWrapper(wrap(raw), encoding="utf-8", errors="replace", line_buffering=True)
            if mode == "w":
                sys.stdout = sys.stderr = stream
            else:
                sys.stdin = stream
    except (OSError, AttributeError, ValueError):
        pass


def make_shortcut(lnk: Path, target: Path, workdir: Path, description: str = "") -> bool:
    """바로가기(.lnk)를 만든다. 파워셸의 WScript.Shell 을 쓰고, 안 되면 조용히 건너뛴다(경로는 환경변수로 넘겨 따옴표 문제를 피함)."""
    script = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:KY_LNK);"
              "$s.TargetPath=$env:KY_TARGET;$s.WorkingDirectory=$env:KY_WD;$s.Description=$env:KY_DESC;"
              "$s.IconLocation=$env:KY_TARGET;$s.Save()")
    try:
        Path(lnk).parent.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, KY_LNK=str(lnk), KY_TARGET=str(target), KY_WD=str(workdir), KY_DESC=description)
        r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                           env=env, capture_output=True, timeout=60, creationflags=0x08000000)
        return r.returncode == 0 and Path(lnk).is_file()
    except (OSError, subprocess.SubprocessError):
        return False


def register_app(exe: Path, base: Path, run_key: str = RUN_KEY, uninstall_key: str = UNINSTALL_KEY,
                 start_menu: Path = START_MENU_DIR) -> None:
    """로그온 때 자동 실행, 설정 > 앱 목록(제거 버튼), 시작 메뉴 바로가기를 등록한다. 모두 현재 사용자 몫이라 관리자 권한이 필요 없다."""
    import winreg
    autostart_set(f'"{exe}" --startup', key_path=run_key)
    size_kb = sum(f.stat().st_size for f in Path(base).rglob("*") if f.is_file()) // 1024
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, uninstall_key) as k:
        for name, value in (("DisplayName", "켠 (kyeon)"), ("DisplayVersion", __version__),
                            ("InstallLocation", str(base)), ("DisplayIcon", str(exe)),
                            ("UninstallString", f'"{exe}" --uninstall --purge')):
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
        for name, value in (("NoModify", 1), ("NoRepair", 1), ("EstimatedSize", size_kb)):
            winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, value)
    make_shortcut(Path(start_menu) / SHORTCUT_NAME, exe, base, "화면 한켠, 마음 한가운데")


def refresh_app_registration(uninstall_key: str = UNINSTALL_KEY) -> None:
    """업데이트로 버전이 바뀌면 앱 목록에 보이는 버전도 맞춘다(등록돼 있을 때만)."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, uninstall_key, 0,
                            winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE) as k:
            if winreg.QueryValueEx(k, "DisplayVersion")[0] != __version__:
                winreg.SetValueEx(k, "DisplayVersion", 0, winreg.REG_SZ, __version__)
    except OSError:
        pass


def remove_app_entries(uninstall_key: str = UNINSTALL_KEY, start_menu: Path = START_MENU_DIR) -> None:
    import winreg
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, uninstall_key)
    except OSError:
        pass
    try:
        (Path(start_menu) / SHORTCUT_NAME).unlink()
    except OSError:
        pass


def seed_files(seed: Path) -> list[str]:
    """설치용 폴더에서 설치할 파일 목록(업데이트가 쓸 수 있는 이름의 파일만)."""
    seed = Path(seed)
    out = [p.relative_to(seed).as_posix() for p in seed.rglob("*") if p.is_file()]
    return sorted(p for p in out if _safe_path(p))


def _copy_atomic(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".kyeon-new")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)


def stop_running_and_wait(state: State, timeout: float = 10.0) -> bool:
    """떠 있는 위젯에 종료 신호를 보내고 끝날 때까지 기다린다. 끝났으면(또는 원래 없었으면) True."""
    handle, running = acquire_single_instance()
    if running:
        state.send("quit")
        release_handle(handle)
        handle, running = wait_for_instance_exit(timeout)
    release_handle(handle)
    return not running


def cmd_setup(state: State, yes: bool, exe: Path, seed: Path = BASE, target: Path = INSTALL_DIR,
              run_key: str = RUN_KEY, uninstall_key: str = UNINSTALL_KEY, start_menu: Path = START_MENU_DIR) -> int:
    """내려받은 kyeon.exe 를 설치한다. exe 안의 설치용 파일을 사용자 폴더에 풀고 등록한다."""
    exe, seed, target = Path(exe), Path(seed), Path(target)
    new_exe, new_py = target / "kyeon.exe", target / "kyeon.py"
    if new_exe.is_file() and new_py.is_file():  # 이미 설치돼 있다: 설치된 켠을 열기만 한다
        spawn_detached(exe=new_exe)
        print("이미 설치되어 있습니다. 설치된 켠을 열었습니다.")
        return 0
    if not (seed / "kyeon.py").is_file():
        tell("설치 파일을 찾지 못했습니다. kyeon.exe 를 다시 내려받아 주세요.", error=True)
        return 2
    if not yes and not ask_yes_no(
            "켠을 이 PC에 설치할까요?\n\n"
            "· 내 사용자 폴더에 설치하므로 관리자 권한이 필요 없습니다.\n"
            "· 컴퓨터를 켤 때마다 하루에 한 번 말씀이 뜹니다.\n"
            "· 지우려면 Windows 설정 > 앱에서 '켠'을 지우면 됩니다."):
        return 1
    try:
        target.mkdir(parents=True, exist_ok=True)
        stop_running_and_wait(state)  # 옛 설치(Python 으로 돌리던 것)가 떠 있으면 먼저 닫는다
        for rel in seed_files(seed):
            _copy_atomic(_local(seed, rel), _local(target, rel))
        _copy_atomic(exe, new_exe)    # 실행 파일을 맨 마지막에 둔다: 중간에 멈춘 설치는 '설치됨' 으로 보이지 않는다
        register_app(new_exe, target, run_key, uninstall_key, start_menu)
    except OSError as e:
        log(f"설치 실패\n{traceback.format_exc()}")
        tell(f"설치하지 못했습니다. ({e.strerror or e})", error=True)
        return 2
    state.dismissed_date = None
    spawn_detached("--first-run", exe=new_exe)
    print("설치했습니다:", target)
    return 0


# 제거 때 쓰는 파워셸 한 줄 묶음. 경로는 환경변수로 넘기므로 사용자 이름이 한글이어도 글자가 깨지지 않는다.
# (.cmd 파일은 코드 페이지 때문에 한글 경로에서 파일을 못 지운다.) 지우기는 우리가 둔 것만, 폴더는 비었을 때만.
PURGE_SCRIPT = (
    "$ErrorActionPreference='SilentlyContinue';Start-Sleep -Seconds 3;$b=$env:KY_BASE;"
    "$exe=Join-Path $b 'kyeon.exe';"
    "for($i=0;$i -lt 20;$i++){Remove-Item -LiteralPath $exe -Force;if(-not(Test-Path -LiteralPath $exe)){break};Start-Sleep -Seconds 1};"
    "foreach($f in $env:KY_FILES.Split('|')){Remove-Item -LiteralPath (Join-Path $b $f) -Force};"
    "Get-ChildItem -LiteralPath $b -Filter '*.kyeon-new' -Force | Remove-Item -Force;"
    "foreach($d in 'data','fonts','__pycache__'){Remove-Item -LiteralPath (Join-Path $b $d) -Recurse -Force};"
    "try{[IO.Directory]::Delete($b,$false)}catch{};"
    "if($env:KY_STATE){$s=$env:KY_STATE;"
    "foreach($f in $env:KY_STATE_FILES.Split('|')){Remove-Item -LiteralPath (Join-Path $s $f) -Force};"
    "foreach($d in 'update','backup'){Remove-Item -LiteralPath (Join-Path $s $d) -Recurse -Force};"
    "try{[IO.Directory]::Delete($s,$false)}catch{}}")


def schedule_purge(base: Path, state_dir: Path | None = None, install_dir: Path = INSTALL_DIR) -> bool:
    """이 프로세스가 끝난 뒤 설치 폴더(와 기록 폴더)를 지우는 파워셸을 띄운다. 설치 폴더가 아닌 곳은 건드리지 않고,
    폴더째 지우지도 않는다(우리가 둔 파일과 하위 폴더만 지우고, 폴더에 남은 것이 있으면 폴더는 둔다)."""
    base = Path(base).resolve()
    if base != Path(install_dir).resolve() or not (base / "kyeon.py").is_file() or len(base.parts) < 3:
        return False
    env = dict(os.environ, KY_BASE=str(base), KY_FILES="|".join(INSTALLED_FILES),
               KY_STATE=str(Path(state_dir).resolve()) if state_dir else "", KY_STATE_FILES="|".join(STATE_FILES))
    try:
        subprocess.Popen(["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", PURGE_SCRIPT],
                         env=env, creationflags=0x08000000 | 0x00000200, close_fds=True)  # NO_WINDOW | NEW_PROCESS_GROUP(파워셸은 콘솔이 있어야 돈다)
    except OSError:
        return False
    return True


def cmd_purge(yes: bool, records: bool) -> int:
    """--uninstall --purge: 프로그램 폴더를 지운다. 읽던 기록(진행 상태)은 묻고 지운다."""
    if not yes and not records:
        records = ask_yes_no("켠을 지웁니다.\n\n읽던 기록(몇 일차인지, 설정)도 함께 지울까요?\n\n"
                             "[예]  기록까지 모두 지움\n[아니요]  기록은 남김 (다시 설치하면 이어서 읽습니다)")
    if schedule_purge(BASE, STATE_DIR if records else None):
        print("설치 폴더를 곧 지웁니다.", "읽던 기록도 지웁니다." if records else "읽던 기록은 남겨 둡니다.")
    else:
        print("설치 폴더가 아니어서 파일은 지우지 않았습니다.")
    return 0


# ───────────────────────── 테마 ─────────────────────────
LIGHT = dict(border="#D8CDB8", card="#FBF8F2", text="#2A2723", muted="#8A8174", accent="#8A6A2F", soft="#F1EBDD",
             btn_fg="#FFFFFF", veil="#DDD1B5", veil_hi="#CDBA8E",
             bar="#FBF8F2", bar_fg="#8A6A2F", bar_mut="#8A8174", tool="#FBF8F2", chip="#F1EBDD",
             grid="#D8CDB8", zebra="#FBF8F2", hdr="#F1EBDD")
DARK = dict(border="#4A443A", card="#24221F", text="#EDE7DB", muted="#9C9488", accent="#D6B26A", soft="#2F2C27",
            btn_fg="#24221F", veil="#4B453A", veil_hi="#6B6050",
            bar="#24221F", bar_fg="#D6B26A", bar_mut="#9C9488", tool="#24221F", chip="#2F2C27",
            grid="#4A443A", zebra="#24221F", hdr="#2F2C27")
# 엑셀 스타일: 스프레드시트처럼 보이는 밝은 화면(업무 중에도 화면 한켠에 두기 좋게). 항상 밝은 색으로 고정
EXCEL = dict(border="#B7B7B7", card="#FFFFFF", text="#1F1F1F", muted="#6B6B6B", accent="#217346", soft="#F0F0F0",
             btn_fg="#FFFFFF", veil="#D0D0D0", veil_hi="#B5B5B5",
             bar="#217346", bar_fg="#FFFFFF", bar_mut="#CFE5D8", tool="#F3F3F3", chip="#FFFFFF",
             grid="#D4D4D4", zebra="#F7F7F7", hdr="#E8E8E8")

# 암송 모드: 단계별 설명. 글자마다 붙은 코드 1=핵심 단어, 2=뜻이 중요한 명사·형용사, 3=그 밖의 내용어(동사, 부사 등),
# 4=조사·어미 등(어느 단계에서도 안 가림). n단계는 코드 1..n 인 글자를 가린다.
RECITE_LEVELS = {1: "핵심 단어를 가림", 2: "중요한 명사·형용사를 가림", 3: "뜻이 있는 말을 모두 가림"}

ASPECT = 1.5  # 창의 세로:가로(3:2). 내용 길이와 상관없이 늘 이 모양으로 열고, 넘치는 내용은 스크롤바로 읽는다


class Scroller:
    """세로로 스크롤되는 영역과 테마색의 얇은 스크롤바. inner 프레임에 내용을 넣으면 된다.
    내용이 영역보다 짧으면 스크롤바는 그려지지 않는다(자리는 그대로 두어 글줄 폭이 흔들리지 않게)."""

    def __init__(self, tk, parent, sc: float):
        self.sc = sc
        self.bar_w = max(8, int(11 * sc))
        self.frame = tk.Frame(parent, bd=0, highlightthickness=0)
        # height=1: 기본 높이를 두면 창의 고정 줄 높이를 잴 때 부풀려 읽는다(실제 높이는 pack 이 채운다)
        self.bar = tk.Canvas(self.frame, width=self.bar_w, height=1, bd=0, highlightthickness=0, cursor="arrow")
        self.bar.pack(side="right", fill="y")
        self.canvas = tk.Canvas(self.frame, height=1, bd=0, highlightthickness=0,
                                yscrollincrement=max(8, int(26 * sc)))
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bd=0, highlightthickness=0)
        self._win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.colors = {"track": "#eeeeee", "thumb": "#cccccc", "hot": "#888888"}
        self._hot = False
        self._grab = None            # 막대를 끌고 있을 때 (시작 y, 시작 위치)
        self._thumb = (0, 0)         # 현재 막대의 위, 아래 y
        self.canvas.bind("<Configure>", self._on_canvas)
        self.inner.bind("<Configure>", self._on_inner)
        self.bar.bind("<Configure>", lambda e: self._draw())
        self.bar.bind("<Button-1>", self._press)
        self.bar.bind("<B1-Motion>", self._motion)
        self.bar.bind("<ButtonRelease-1>", self._release)
        self.bar.bind("<Enter>", lambda e: self._set_hot(True))
        self.bar.bind("<Leave>", lambda e: self._set_hot(bool(self._grab)))

    # ---- 크기와 위치 ----
    def content_height(self) -> int:
        return max(1, self.inner.winfo_reqheight())

    def view_height(self) -> int:
        return max(1, self.canvas.winfo_height())

    def scrollable(self) -> bool:
        return self.content_height() > self.view_height() + 1

    def _on_canvas(self, e) -> None:
        self.canvas.itemconfigure(self._win, width=e.width)
        self.sync()

    def _on_inner(self, e) -> None:
        self.sync()

    def sync(self) -> None:
        """내용 높이에 맞춰 스크롤 범위를 고치고 막대를 다시 그린다."""
        h = self.content_height()
        self.canvas.configure(scrollregion=(0, 0, max(1, self.canvas.winfo_width()), h))
        if not self.scrollable():
            self.canvas.yview_moveto(0)
        self._draw()

    def to_top(self) -> None:
        self.canvas.yview_moveto(0)
        self._draw()

    def scroll(self, units: int) -> None:
        if self.scrollable():
            self.canvas.yview_scroll(units, "units")
            self._draw()

    def first(self) -> float:
        return self.canvas.yview()[0]

    def seen_all(self) -> bool:
        return not self.scrollable() or self.canvas.yview()[1] >= 0.999

    # ---- 막대 ----
    def set_colors(self, bg: str, track: str, thumb: str, hot: str) -> None:
        self.colors = {"track": track, "thumb": thumb, "hot": hot}
        for w in (self.frame, self.canvas, self.inner, self.bar):
            w.configure(bg=bg)
        self._draw()

    def _set_hot(self, on: bool) -> None:
        if on != self._hot:
            self._hot = on
            self._draw()

    def _draw(self) -> None:
        bar = self.bar
        bar.delete("all")
        bh = max(1, bar.winfo_height())
        if not self.scrollable() or bh < 20:
            self._thumb = (0, 0)
            return
        cx, pad = self.bar_w / 2, 3
        first, last = self.canvas.yview()
        length = max(int(28 * self.sc), int((last - first) * (bh - 2 * pad)))
        span = max(1e-6, 1 - (last - first))
        top = pad + int(first / span * (bh - 2 * pad - length))
        top = max(pad, min(top, bh - pad - length))
        self._thumb = (top, top + length)
        bar.create_line(cx, pad, cx, bh - pad, width=max(2, int(2 * self.sc)), fill=self.colors["track"],
                        capstyle="round")
        thick = max(4, int((7 if (self._hot or self._grab) else 5) * self.sc))
        bar.create_line(cx, top, cx, top + length, width=thick, capstyle="round",
                        fill=self.colors["hot"] if (self._hot or self._grab) else self.colors["thumb"])

    def _press(self, e) -> None:
        if not self.scrollable():
            return
        top, bottom = self._thumb
        if top <= e.y <= bottom:
            self._grab = (e.y, self.first())
            self._draw()
        else:  # 막대 밖을 누르면 한 쪽씩 넘긴다
            self.canvas.yview_scroll(-1 if e.y < top else 1, "pages")
            self._draw()

    def _motion(self, e) -> None:
        if not self._grab:
            return
        y0, first0 = self._grab
        bh = max(1, self.bar.winfo_height())
        top, bottom = self._thumb
        room = max(1, bh - 6 - (bottom - top))
        first, last = self.canvas.yview()
        span = max(1e-6, 1 - (last - first))
        self.canvas.yview_moveto(max(0.0, min(span, first0 + (e.y - y0) / room * span)))
        self._draw()

    def _release(self, e) -> None:
        self._grab = None
        self._draw()


# ───────────────────────── 위젯 ─────────────────────────
class Widget:
    W = 480          # 논리 폭(px, 96dpi 기준). 글자 크기 설정에 따라 인스턴스에서 바뀐다
    MAX_BLOCKS = 3   # 해설 블록 최대 개수(형식 2 가 3개, 나머지는 2개)
    FONT_BASE = dict(f_app=9, f_small=9, f_smallb=9, f_ref=15, f_title=10, f_note=9, f_body=12, f_num=8,
                     f_expl=10, f_btn=9)
    FONT_COMPACT = dict(f_expl=-1, f_body=-1)   # 화면이 낮아 안 들어가면 이만큼 줄여 다시 그린다
    FONT_SCALE = {"small": 0.9, "normal": 1.0, "large": 1.2}
    XL_TABS = ("파일", "홈", "삽입", "수식", "데이터", "검토", "보기")  # 엑셀 스타일의 장식용 메뉴 줄

    def __init__(self, plan: dict, state: State, today_fn=date.today, preview_day: int | None = None,
                 recite: int | None = None, skin: str | None = None, route: str | None = None):
        """recite/skin/route: 미리보기용으로 암송 모드(0=끔, 1~3=단계), 화면 스타일, 읽는 길을 강제한다. None 이면 저장된 설정을 따른다."""
        import tkinter as tk
        from tkinter import font as tkfont
        self.tk = tk
        self.days = plan["days"]
        self.plan_routes = build_routes(plan)
        self.route = find_route(self.plan_routes, route if route is not None else state.get("route"))
        self.track: list[int] = self.route["idxs"]   # 지금 길의 날들(plan["days"] 색인). 오늘의 말씀은 이 안에서 고른다
        self.pos = 0                                  # 지금 길 안에서 오늘의 자리(0부터)
        self.routes_win = None
        self.translation = plan.get("translation", "개역한글")
        self.state = state
        self.today_fn = today_fn
        self.preview_day = preview_day
        self.current_date: date | None = None
        self.idx = 0
        self.visible = False
        self._themed: list = []
        self._drag = (0, 0)
        self.settings_win = None
        self._tick_id = self._go_id = None  # 예약된 타이머(종료할 때 취소)
        # 업데이트: start() 가 켜기 전에는(미리보기, 테스트) 네트워크를 쓰지 않는다
        self.updates_enabled = False
        self.update_info: dict | None = None   # 새 버전이 있으면 check_update 가 돌려준 정보
        self.update_state = "idle"             # idle(안내) | working(내려받는 중) | error | done(방금 업데이트함)
        self.update_msg = ""                   # 오류나 확인 결과 문장
        self._upd_q: queue.Queue = queue.Queue()  # 작업 스레드 -> 화면(Tk 는 메인 스레드에서만 만진다)
        self._checking = False
        self._check_manual = False
        self._quitting = False
        self.base_dir = BASE                      # 업데이트가 파일을 바꿔 넣는 폴더(시험에서 바꿈)
        # 암송 모드: 가림 정보(lv)가 있는 계획에서만 쓸 수 있다
        self.can_recite = any(d.get("lv") for d in self.days)
        self._persist = recite is None and skin is None and preview_day is None and route is None
        self.cfg = {k: state.get(k) for k in SETTING_DEFAULTS}
        self.cfg["route"] = self.route["id"]
        if recite is not None:
            self.cfg["recite"] = recite > 0
            if recite:
                self.cfg["recite_level"] = recite
        if skin is not None:
            self.cfg["skin"] = skin
        self.revealed: set[tuple[int, int]] = set()  # 눌러서 보이게 한 (구절 번호, 어절 번호)

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.title("켠")
        self.root.report_callback_exception = self._on_error
        try:
            self.root.attributes("-alpha", 0.98)
        except tk.TclError:
            pass
        self.sc = self.root.winfo_fpixels("1i") / 96.0

        load_bundled_fonts()   # 본문 글꼴(리디바탕)을 쓸 수 있게 등록. 글꼴 이름을 고르기 전에 해 둔다
        self.family = self._pick_family(tkfont)
        self.body_family = self._pick_body_family(tkfont)
        for name, size in self.FONT_BASE.items():
            kw = {"weight": "bold"} if name in ("f_app", "f_smallb", "f_ref", "f_num", "f_btn") else {}
            if name == "f_note":
                kw = {"slant": "italic"}
            fam = self.body_family if name == "f_body" else self.family  # 본문(성경 구절)만 바탕체, 나머지는 화면 글꼴
            setattr(self, name, tkfont.Font(family=fam, size=size, **kw))
        self.compact = False  # 고정 비율의 창에 본문 영역이 너무 좁게 남으면 글자를 줄여 다시 그린다
        self._size = (0, 0)   # 창 크기(폭, 높이). _layout 이 정한다
        self._apply_width()
        self._build()
        self._apply_theme()

    # ---- 설정 값 ----
    @property
    def recite(self) -> bool:
        return bool(self.cfg["recite"]) and self.can_recite

    @property
    def level(self) -> int:
        return self.cfg["recite_level"]

    @property
    def skin(self) -> str:
        return self.cfg["skin"]

    def reload_settings(self) -> None:
        """다른 프로세스(--skin 등)가 바꾼 저장값을 다시 읽는다. 미리보기에서는 하지 않는다."""
        if self._persist:
            for k in SETTING_DEFAULTS:
                self.cfg[k] = self.state.get(k)
            self.cfg["route"] = self.route["id"]   # 길은 _follow_route 가 따라간다(자리 계산이 함께 바뀌어야 해서)

    def set_setting(self, key: str, value) -> None:
        """설정 하나를 바꾸고(미리보기가 아니면 저장) 화면에 바로 반영한다."""
        if key in ("recite", "recite_level") and not self.can_recite:
            return
        self.cfg[key] = value
        if self._persist:
            self.state.set(key, value)
        if key == "recite_level":
            self.revealed.clear()
            self._style_recite_ui()
            self._fill_text()
        elif key == "topmost":
            self.root.attributes("-topmost", bool(value))
        elif key == "update_check":
            pass  # 다음에 로그온할 때부터 적용(화면은 그대로)
        elif key == "corner":
            self.reflow(snap=True)
        else:  # skin, theme, font, recite
            if key == "recite":
                self.revealed.clear()
            self.reflow()
        if self.settings_win is not None and self.settings_win.alive():
            self.settings_win.refresh()

    def autostart_on(self) -> bool:
        return bool(autostart_get())

    def set_autostart(self, on: bool) -> bool:
        """로그온 시 자동 실행을 켜고 끈다(미리보기에서는 레지스트리를 건드리지 않음)."""
        if self.preview_day:
            return False
        try:
            if on:
                autostart_set(autostart_command())
            else:
                autostart_remove()
            return True
        except OSError:
            return False

    def current_day(self) -> int:
        """지금 읽는 길 안에서 오늘이 몇 일차인지(전체 순서에서는 계획표의 일차 번호와 같다)."""
        return self.pos + 1

    def route_label(self) -> str:
        return route_label(self.route)

    def _follow_route(self) -> None:
        """다른 프로세스(--route)가 저장한 길로 바뀌었으면 따라간다. 자리(start_date)는 그쪽에서 이미 맞춰 두었다."""
        if not self._persist:
            return
        rid = self.state.get("route")
        if rid != self.route["id"]:
            self.route = find_route(self.plan_routes, rid)
            self.track = self.route["idxs"]
            self.cfg["route"] = self.route["id"]

    def set_route(self, route_id: str) -> None:
        """읽는 길을 바꾼다. 떠나는 길의 읽던 자리는 기억해 두고, 새 길은 기억한 자리(처음이면 1일차)에서 이어 읽는다."""
        new = find_route(self.plan_routes, route_id)
        if new["id"] == self.route["id"]:
            return
        today = self.current_date or self.today_fn()
        if self._persist:
            switch_route(self.state, self.plan_routes, new["id"], today, cur_id=self.route["id"])
        self.route, self.track = new, new["idxs"]
        self.cfg["route"] = new["id"]
        if self.preview_day:
            self.preview_day = 1
        self.revealed.clear()
        if self.visible:
            self.idx = self.pick(today)
            self.reflow()
        else:
            self.refresh(today, show=True)
        if self.settings_win is not None and self.settings_win.alive():
            self.settings_win.refresh()
        if self.routes_win is not None and self.routes_win.alive():
            self.routes_win.refresh()

    def open_routes(self) -> None:
        if self.routes_win is not None and self.routes_win.alive():
            self.routes_win.top.lift()
            self.routes_win.refresh()
            return
        self.routes_win = RouteWindow(self)

    def jump_to_day(self, n: int) -> None:
        """지금 읽는 길에서 오늘이 n일차가 되도록 시작일을 옮긴다."""
        n = max(1, min(len(self.track), int(n)))
        today = self.current_date or self.today_fn()
        if self.preview_day:
            self.preview_day = n
        else:
            self.state.start_date = today - timedelta(days=n - 1)
            self.state.dismissed_date = None
        self.revealed.clear()
        if self.visible:
            self.idx = self.pick(today)
            self.reflow()
        else:
            self.refresh(today, show=True)
        if self.settings_win is not None and self.settings_win.alive():
            self.settings_win.refresh()

    def open_settings(self) -> None:
        if self.settings_win is not None and self.settings_win.alive():
            self.settings_win.top.lift()
            self.settings_win.refresh()
        else:
            self.settings_win = SettingsWindow(self)

    # ---- 업데이트 ----
    def _upd_visible(self) -> bool:
        """안내 줄을 보일지: 새 버전이 있고 이 버전을 '나중에' 로 미루지 않았을 때(진행 중, 오류, 완료는 항상)."""
        if not self.updates_enabled or self.update_info is None:
            return False
        return self.update_state != "idle" or self.state.update_skipped != self.update_info["version"]

    def _upd_text(self) -> str:
        m, st = self.update_info, self.update_state
        note = (m.get("notes") or [""])[0]
        tail = f"\n{note}" if note else ""
        if st == "working":
            return "내려받아 바꾸는 중입니다…"
        if st == "error":
            return f"업데이트하지 못했습니다. {self.update_msg}"
        if st == "done":
            return f"{m['version']} 으로 업데이트했습니다" + tail
        return f"새 버전 {m['version']} 이 나왔습니다" + tail

    def update_status_text(self) -> str:
        """설정 창의 한 줄 상태."""
        if self.update_state == "working":
            return "내려받아 바꾸는 중입니다…"
        if self._checking:
            return "확인하는 중입니다…"
        if self.update_info is not None and self.update_state != "done":
            return f"새 버전 {self.update_info['version']} 이 있습니다"
        if self.update_msg:
            return self.update_msg
        at = self.state.update_checked_at
        if at is None:
            return f"켠 {__version__} · 아직 확인하지 않았습니다"
        t = datetime.fromtimestamp(at)
        return f"켠 {__version__} · 최신입니다 ({t.month}월 {t.day}일 {t.hour}:{t.minute:02d} 확인)"

    def _upd_notify(self) -> None:
        if self.settings_win is not None and self.settings_win.alive():
            self.settings_win.refresh()

    def _work(self, tag: str, fn) -> None:
        """fn 을 뒤에서 돌리고 결과를 큐에 넣는다. 화면과 상태 파일은 여기서 건드리지 않는다."""
        def run() -> None:
            try:
                self._upd_q.put((tag, True, fn()))
            except UpdateError as e:
                self._upd_q.put((tag, False, str(e)))
            except Exception:  # noqa: BLE001
                log(traceback.format_exc())
                self._upd_q.put((tag, False, "예상하지 못한 오류가 났습니다. widget.log 를 확인하세요"))

        threading.Thread(target=run, daemon=True).start()

    def check_now(self, manual: bool = True) -> None:
        """새 버전 확인을 뒤에서 시작한다. 결과는 tick 이 _poll_update 로 받아 화면에 반영한다."""
        if self._checking or self.update_state == "working":
            return
        if not self.updates_enabled:
            self.update_msg = "미리보기에서는 확인하지 않습니다"
            self._upd_notify()
            return
        self._checking, self._check_manual = True, manual
        if manual:
            self.update_msg = ""
        src = update_source(self.state)
        self._work("check", lambda: check_update(src))
        self._upd_notify()

    def install_update(self) -> None:
        """안내 줄의 '업데이트': 받아서 검증하고 바꿔 넣은 뒤 다시 뜬다."""
        m = self.update_info
        if m is None or self.update_state == "working" or not self.updates_enabled:
            return
        self.update_state, self.update_msg = "working", ""
        self.reflow()
        self._upd_notify()
        base_dir, state_dir = self.base_dir, self.state.dir
        self._work("install", lambda: apply_update(m, base_dir, state_dir))

    def skip_update(self) -> None:
        """'나중에': 이 버전은 더 새 버전이 나오기 전까지 안내하지 않는다. 완료 안내에서는 '확인'."""
        if self.update_info is not None:
            if self.update_state == "done":
                self.update_info, self.update_state = None, "idle"
            elif self._persist:
                self.state.update_skipped = self.update_info["version"]
            else:
                self.update_info = None
        self.reflow()
        self._upd_notify()

    def _upd_action(self) -> None:
        if self.update_state == "done":
            self.skip_update()
        else:
            self.install_update()

    def _poll_update(self) -> None:
        while True:
            try:
                tag, ok, val = self._upd_q.get_nowait()
            except queue.Empty:
                return
            if tag == "check":
                self._checking = False
                if ok:
                    try:
                        self.state.mark_update_checked()
                    except OSError:
                        pass
                    had_bar = bool(self.upd_bar.winfo_manager())
                    self.update_info = val
                    self.update_state = "idle"
                    self.update_msg = ""
                    if self._upd_visible() or had_bar:  # 새로 보이거나, 보이던 안내가 사라져야 할 때
                        self.reflow()
                else:
                    log(f"업데이트 확인 실패: {val}")
                    self.update_msg = val if self._check_manual else ""  # 로그온 때 자동 확인의 실패는 조용히 넘어간다
            elif tag == "install":
                if ok:
                    self._restart()
                    if self._quitting:
                        return
                else:
                    self.update_state, self.update_msg = "error", val
                    self.reflow()
            self._upd_notify()

    def _restart(self) -> None:
        """새 파일로 다시 뜬다: 새 프로세스를 먼저 띄우면(이전 위젯이 끝날 때까지 기다림) 이 위젯은 끝낸다."""
        try:
            spawn_detached("--after-update", *(["--show"] if self.visible else []))
        except OSError:
            log(traceback.format_exc())
            self.update_state, self.update_msg = "error", "업데이트는 끝났습니다. 켠을 다시 실행해 주세요"
            self.reflow()
            return
        self.quit()

    def _announce_update_done(self) -> None:
        """방금 업데이트하고 다시 뜬 것이면 안내 줄에 한 번 알린다."""
        info = read_last_update(self.state.dir)
        if info:
            self.update_info = {"version": info["version"], "notes": [str(n) for n in info.get("notes") or []]}
            self.update_state = "done"

    # ---- 구성 ----
    @staticmethod
    def _pick_family(tkfont) -> str:
        have = set(tkfont.families())
        for f in ("Malgun Gothic", "맑은 고딕", "Noto Sans CJK KR", "NanumGothic", "Apple SD Gothic Neo"):
            if f in have:
                return f
        return tkfont.nametofont("TkDefaultFont").actual("family")

    # 본문 글꼴 후보. 앞에 있는 것부터 쓴다(리디바탕이 없으면 바탕체, 그것도 없으면 화면 글꼴)
    BODY_FAMILIES = ("RIDIBatang", "리디바탕", "Batang", "바탕", "Noto Serif CJK KR", "Noto Serif KR")

    def _pick_body_family(self, tkfont) -> str:
        have = set(tkfont.families())
        for f in self.BODY_FAMILIES:
            if f in have:
                return f
        return self.family

    def _reg(self, w, **opts):
        self._themed.append((w, opts))
        return w

    def _apply_fonts(self) -> None:
        k = self.FONT_SCALE[self.cfg["font"]]
        for name, base in self.FONT_BASE.items():
            size = base + (self.FONT_COMPACT.get(name, 0) if self.compact else 0)
            getattr(self, name).configure(size=max(7, round(size * k)))

    def _apply_width(self) -> None:
        """글자 크기에 맞춰 폭을 정하고, 줄바꿈 폭(wraplength)을 다시 잡는다."""
        self._apply_fonts()
        base = round(480 * self.FONT_SCALE[self.cfg["font"]])
        # 낮은 화면에서는 같은 비율(ASPECT)을 지키려고 폭을 줄인다(기준 폭의 80% 까지)
        left, top, right, bottom = work_area()
        avail_h = (bottom - top) - 2 * int(16 * self.sc)
        self.W = max(round(base * 0.8), min(base, int(avail_h / ASPECT / self.sc)))
        if not hasattr(self, "blocks"):  # 아직 _build 전
            return
        inner = int((self.W - 36) * self.sc)
        for lbl in (self.lbl_title, self.lbl_note, self.lbl_par):
            lbl.configure(wraplength=inner)
        body = self._body_px()
        for lab, txt in self.blocks:
            txt.configure(wraplength=body - int(27 * self.sc))
        self.lbl_upd.configure(wraplength=inner - int(150 * self.sc))  # 오른쪽 버튼 자리를 뺀 폭

    def _body_px(self) -> int:
        """스크롤 영역 안쪽(본문과 해설이 놓이는 곳)의 폭. 왼쪽 여백과 스크롤바 자리를 뺀 값."""
        return int(self.W * self.sc) - int(18 * self.sc) - int(6 * self.sc) - self.scroller.bar_w - 2

    def _build(self) -> None:
        tk, sc = self.tk, self.sc
        pad = int(18 * sc)
        reg = self._reg

        outer = reg(tk.Frame(self.root), bg="border")
        outer.pack(fill="both", expand=True)
        card = reg(tk.Frame(outer), bg="card")
        card.pack(fill="both", expand=True, padx=1, pady=1)

        # 머리줄(엑셀 스타일에서는 초록색 제목 줄): 앱 이름 · 날짜 · 설정 · 닫기
        self.head_wrap = reg(tk.Frame(card), bg="bar")
        self.head = reg(tk.Frame(self.head_wrap), bg="bar")
        self.lbl_app = reg(tk.Label(self.head, text="켠", font=self.f_app), bg="bar", fg="bar_fg")
        self.lbl_app.pack(side="left")
        self.btn_x = reg(tk.Label(self.head, text="✕", font=self.f_small, cursor="hand2"), bg="bar", fg="bar_mut")
        self.btn_x.pack(side="right")
        self.btn_gear = reg(tk.Label(self.head, text="⚙", font=self.f_small, cursor="hand2"), bg="bar", fg="bar_mut")
        self.btn_gear.pack(side="right", padx=(0, int(8 * sc)))
        self.lbl_date = reg(tk.Label(self.head, font=self.f_small), bg="bar", fg="bar_mut")
        self.lbl_date.pack(side="right", padx=(0, int(10 * sc)))
        self.btn_x.bind("<Button-1>", lambda e: self.dismiss())
        self.btn_gear.bind("<Button-1>", lambda e: self.open_settings())
        for b in (self.btn_x, self.btn_gear):
            b.bind("<Enter>", lambda e, b=b: b.configure(fg=self._p["bar_fg"]))
            b.bind("<Leave>", lambda e, b=b: b.configure(fg=self._p["bar_mut"]))
        for w in (self.head_wrap, self.head, self.lbl_app, self.lbl_date):
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)

        # 엑셀 스타일 전용 장식: 메뉴 줄, 수식 입력줄, 열 머리글, 시트 탭
        self.xl_menu = reg(tk.Frame(card), bg="tool")
        self.xl_menu_items = []
        for name in self.XL_TABS:
            lab = reg(tk.Label(self.xl_menu, text=name, font=self.f_small, padx=int(7 * sc), pady=int(3 * sc)),
                      bg="tool", fg="muted")
            lab.pack(side="left")
            if name == "파일":  # 엑셀의 '파일' 메뉴처럼 설정 창을 연다
                lab.configure(cursor="hand2", font=self.f_smallb)
                lab.bind("<Button-1>", lambda e: self.open_settings())
            self.xl_menu_items.append((name, lab))
        self.xl_line1 = reg(tk.Frame(card, height=1), bg="grid")
        self.xl_formula = reg(tk.Frame(card), bg="card")
        name_box = reg(tk.Frame(self.xl_formula), bg="grid")
        name_box.pack(side="left", padx=(int(8 * sc), 0), pady=int(4 * sc))
        self.xl_name = reg(tk.Label(name_box, text="B2", font=self.f_small, width=6, anchor="w", padx=int(4 * sc)),
                           bg="card", fg="text")
        self.xl_name.pack(padx=1, pady=1)
        reg(tk.Label(self.xl_formula, text="fx", font=self.f_note), bg="card", fg="muted").pack(
            side="left", padx=(int(8 * sc), int(6 * sc)))
        cell_box = reg(tk.Frame(self.xl_formula), bg="grid")
        cell_box.pack(side="left", fill="x", expand=True, padx=(0, int(8 * sc)), pady=int(4 * sc))
        self.xl_cell = reg(tk.Label(cell_box, font=self.f_small, anchor="w", padx=int(4 * sc)), bg="card", fg="text")
        self.xl_cell.pack(fill="x", padx=1, pady=1)
        self.xl_line2 = reg(tk.Frame(card, height=1), bg="grid")
        self.xl_cols = reg(tk.Frame(card), bg="hdr")
        self.xl_colA = reg(tk.Frame(self.xl_cols, height=int(17 * sc)), bg="hdr")
        self.xl_colA.pack_propagate(False)
        self.xl_colA.pack(side="left")
        reg(tk.Label(self.xl_colA, text="A", font=self.f_small), bg="hdr", fg="muted").pack(fill="both", expand=True)
        reg(tk.Frame(self.xl_cols, width=1), bg="grid").pack(side="left", fill="y")
        reg(tk.Label(self.xl_cols, text="B", font=self.f_small), bg="hdr", fg="muted").pack(
            side="left", fill="both", expand=True)
        self.xl_tabs_line = reg(tk.Frame(card, height=1), bg="grid")
        self.xl_tabs = reg(tk.Frame(card), bg="tool")
        for g in ("◂", "▸"):
            reg(tk.Label(self.xl_tabs, text=g, font=self.f_small), bg="tool", fg="muted").pack(
                side="left", padx=(int(8 * sc), 0))
        reg(tk.Label(self.xl_tabs, text="Sheet1", font=self.f_smallb, padx=int(12 * sc), pady=int(2 * sc)),
            bg="card", fg="accent").pack(side="left", padx=(int(8 * sc), 0))
        reg(tk.Label(self.xl_tabs, text="+", font=self.f_small), bg="tool", fg="muted").pack(
            side="left", padx=int(8 * sc))
        reg(tk.Label(self.xl_tabs, text="100%", font=self.f_small), bg="tool", fg="muted").pack(
            side="right", padx=(int(8 * sc), pad))
        reg(tk.Label(self.xl_tabs, text="준비", font=self.f_small), bg="tool", fg="muted").pack(side="right")

        # 진행 줄: 구분 · 일차 / 오른쪽에 암송 스위치와 단계(1·2·3)
        self.prog_wrap = reg(tk.Frame(card), bg="tool")
        self.prog = reg(tk.Frame(self.prog_wrap), bg="tool")
        self.lbl_prog = reg(tk.Label(self.prog, font=self.f_small, anchor="w", cursor="hand2"), bg="tool", fg="muted")
        self.lbl_prog.pack(side="left")
        self.lbl_prog.bind("<Button-1>", lambda e: self.open_routes())   # 진행 줄을 누르면 읽는 길을 고르는 창
        if self.can_recite:
            self.chips = {}
            for lv in (3, 2, 1):  # side=right 이므로 3,2,1 순으로 넣으면 화면에는 1 2 3
                chip = reg(tk.Label(self.prog, text=str(lv), font=self.f_btn, cursor="hand2",
                                    padx=int(7 * sc), pady=int(1 * sc)), bg="chip", fg="muted")
                chip.bind("<Button-1>", lambda e, n=lv: self.set_setting("recite_level", n))
                self.chips[lv] = chip
            self.switch = reg(tk.Label(self.prog, font=self.f_btn, cursor="hand2", padx=int(4 * sc)),
                              bg="tool", fg="muted")
            self.switch.pack(side="right", padx=(0, int(2 * sc)))
            self.switch.bind("<Button-1>", lambda e: self._toggle_recite())
        # 암송 안내 줄(암송 모드일 때만 본문 위에 나타남)
        self.rrow = reg(tk.Frame(card), bg="card")
        self.lbl_rhint = reg(tk.Label(self.rrow, font=self.f_small, anchor="w"), bg="card", fg="muted")
        self.lbl_rhint.pack(side="left")
        self.btn_rehide = reg(tk.Label(self.rrow, text="다시 가리기", font=self.f_small, cursor="hand2"),
                              bg="card", fg="accent")
        self.btn_rehide.pack(side="right")
        self.btn_rehide.bind("<Button-1>", lambda e: self._rehide())

        self.lbl_ref = reg(tk.Label(card, font=self.f_ref, anchor="w"), bg="card", fg="text")
        self.lbl_title = reg(tk.Label(card, font=self.f_title, anchor="w", justify="left"), bg="card", fg="muted")
        self.lbl_note = reg(tk.Label(card, font=self.f_note, anchor="w", justify="left"), bg="card", fg="muted")
        self.lbl_par = reg(tk.Label(card, font=self.f_small, anchor="w", justify="left"), bg="card", fg="muted")

        # 본문과 해설은 한 스크롤 영역(scroller.inner) 안에 둔다. 머리줄과 바닥줄은 고정
        self.scroller = Scroller(tk, card, sc)
        scr = self.scroller.inner
        self.text_frame = reg(tk.Frame(scr, height=10), bg="card")  # 높이는 render() 가 내용 전체가 보이는 픽셀로 지정
        self.text_frame.pack_propagate(False)
        self.spacing2 = int(5 * sc)
        self.text = reg(tk.Text(self.text_frame, wrap="word", font=self.f_body, relief="flat", bd=0,
                                highlightthickness=0, padx=0, pady=0, cursor="arrow",
                                spacing2=self.spacing2, spacing3=0, takefocus=0, height=1),
                        bg="card", fg="text", selectbackground="soft", inactiveselectbackground="soft")
        self.text.pack(fill="both", expand=True)
        self.vline = reg(tk.Frame(self.text, width=1), bg="grid")  # 엑셀 스타일: 번호 열과 본문 열 사이의 선
        self.root.bind_all("<MouseWheel>", self._wheel)  # 어느 글자 위에서든 휠로 본문 영역을 넘긴다
        # 가려진 낱말(태그 hid)을 누르면 보인다. break 로 선택 동작이 끼어드는 것을 막는다
        self.text.tag_bind("hid", "<Button-1>", self._reveal)
        self.text.tag_bind("hid", "<Double-Button-1>", lambda e: "break")
        self.text.tag_bind("hid", "<Enter>", lambda e: self.text.configure(cursor="hand2"))
        self.text.tag_bind("hid", "<Leave>", lambda e: self.text.configure(cursor="arrow"))

        # 묵상 상자
        self.box = reg(tk.Frame(scr), bg="soft")
        bar = reg(tk.Frame(self.box, width=3), bg="accent")
        bar.pack(side="left", fill="y")
        body = reg(tk.Frame(self.box), bg="soft")
        body.pack(side="left", fill="both", expand=True, padx=(int(10 * sc), int(12 * sc)), pady=int(10 * sc))
        # 해설 블록(라벨 + 글) 최대 MAX_BLOCKS 개. 쓰지 않는 블록은 숨긴다
        self.blocks = []
        for _ in range(self.MAX_BLOCKS):
            lab = reg(tk.Label(body, font=self.f_app, anchor="w"), bg="soft", fg="accent")
            txt = reg(tk.Label(body, font=self.f_expl, anchor="w", justify="left"), bg="soft", fg="text")
            self.blocks.append((lab, txt))

        # 바닥줄: 번역본 · 닫기 버튼
        self.foot = reg(tk.Frame(card), bg="card")
        reg(tk.Label(self.foot, text=self.translation, font=self.f_small), bg="card", fg="muted").pack(side="left")
        self.btn = reg(tk.Label(self.foot, text="오늘은 닫기", font=self.f_btn, cursor="hand2",
                                padx=int(12 * sc), pady=int(5 * sc)), bg="soft", fg="accent")
        self.btn.pack(side="right")
        self.btn.bind("<Button-1>", lambda e: self.dismiss())
        self.btn.bind("<Enter>", lambda e: self._hover(True))
        self.btn.bind("<Leave>", lambda e: self._hover(False))

        # 업데이트 안내 줄(새 버전이 있을 때만 바닥줄 위에 나타남)
        self.upd_bar = reg(tk.Frame(card), bg="soft")
        self.lbl_upd = reg(tk.Label(self.upd_bar, font=self.f_small, anchor="w", justify="left"), bg="soft", fg="text")
        self.btn_upd = reg(tk.Label(self.upd_bar, text="업데이트", font=self.f_btn, cursor="hand2",
                                    padx=int(10 * sc), pady=int(3 * sc)), bg="accent", fg="btn_fg")
        self.btn_upd_later = reg(tk.Label(self.upd_bar, text="나중에", font=self.f_small, cursor="hand2"),
                                 bg="soft", fg="muted")
        self.btn_upd.bind("<Button-1>", lambda e: self._upd_action())
        self.btn_upd_later.bind("<Button-1>", lambda e: self.skip_update())
        self._apply_width()

    # ---- 테마와 스킨 ----
    def _palette(self) -> dict:
        if self.skin == "excel":
            return EXCEL
        mode = self.cfg["theme"]
        if mode == "auto":
            return DARK if is_dark() else LIGHT
        return DARK if mode == "dark" else LIGHT

    def _anchor(self):
        """본문 위에 끼워 넣는 줄(표제, 병행, 암송 안내)이 놓일 기준 위젯."""
        return self.xl_cols if self.skin == "excel" else self.scroller.frame

    def _pack_card(self) -> None:
        """스킨에 맞게 카드 안의 줄 배치를 새로 한다(표제·병행·암송 안내는 render 가 다시 끼운다).
        위쪽 줄은 위에서부터, 아래쪽 줄은 맨 아래부터 먼저 자리를 잡고, 남는 자리를 본문 스크롤 영역이 채운다."""
        sc, xl = self.sc, self.skin == "excel"
        pad = int(18 * sc)
        for w in (self.head_wrap, self.xl_menu, self.xl_line1, self.xl_formula, self.xl_line2, self.prog_wrap,
                  self.lbl_ref, self.lbl_title, self.lbl_note, self.lbl_par, self.rrow, self.xl_cols,
                  self.scroller.frame, self.upd_bar, self.foot, self.xl_tabs_line, self.xl_tabs):
            w.pack_forget()
        self.head_wrap.pack(fill="x", pady=(0, 0) if xl else (int(pad * 0.8), 0))
        self.head.pack(fill="x", padx=pad, pady=int(6 * sc) if xl else 0)
        if xl:
            self.xl_menu.pack(fill="x")
            self.xl_line1.pack(fill="x")
            self.xl_formula.pack(fill="x")
            self.xl_line2.pack(fill="x")
        self.prog_wrap.pack(fill="x", pady=(0, int(6 * sc)) if xl else (int(2 * sc), int(10 * sc)))
        self.prog.pack(fill="x", padx=pad, pady=int(4 * sc) if xl else 0)
        self.lbl_ref.pack(fill="x", padx=pad, pady=(int(2 * sc), 0) if xl else 0)
        self.lbl_title.pack(fill="x", padx=pad, pady=(0, int(8 * sc)))
        if xl:
            self.xl_cols.pack(fill="x", padx=pad)
        if xl:  # 맨 아래부터: 시트 탭 -> 바닥줄 -> 업데이트 안내
            self.xl_tabs.pack(side="bottom", fill="x")
            self.xl_tabs_line.pack(side="bottom", fill="x")
        self.foot.pack(side="bottom", fill="x", padx=pad, pady=(int(12 * sc), int(8 * sc) if xl else int(pad * 0.8)))
        self._pack_update_bar()
        # 남는 자리는 본문 스크롤 영역이 채운다. 오른쪽 여백은 좁게 두어 스크롤바가 가장자리에 붙게 한다
        self.scroller.frame.pack(fill="both", expand=True, padx=(pad, int(6 * sc)))
        self.scroller.inner.configure(padx=0)
        self.text_frame.pack(fill="x")
        self.box.pack(fill="x", pady=(int(14 * sc), int(10 * sc)))

    def _pack_update_bar(self) -> None:
        """새 버전이 있으면 바닥줄 바로 위에 안내 줄을 놓는다. 오른쪽 버튼부터 놓고 남는 자리를 글이 채운다."""
        sc = self.sc
        self.upd_bar.pack_forget()
        if not self._upd_visible():
            return
        st = self.update_state
        for w in (self.lbl_upd, self.btn_upd, self.btn_upd_later):
            w.pack_forget()
        self.lbl_upd.configure(text=self._upd_text())
        if st != "working":
            self.btn_upd.configure(text={"error": "다시 시도", "done": "확인"}.get(st, "업데이트"))
            self.btn_upd.pack(side="right", padx=(0, int(8 * sc)))
            if st in ("idle", "error"):
                self.btn_upd_later.pack(side="right", padx=(0, int(8 * sc)))
        self.lbl_upd.pack(side="left", fill="x", expand=True, padx=(int(10 * sc), int(6 * sc)), pady=int(7 * sc))
        self.upd_bar.pack(side="bottom", fill="x", padx=int(18 * sc), pady=(int(12 * sc), 0), after=self.foot)

    def _apply_theme(self) -> None:
        self._p = p = self._palette()
        xl, sc = self.skin == "excel", self.sc
        for w, opts in self._themed:
            w.configure(**{k: p[v] for k, v in opts.items()})
        self.scroller.set_colors(p["card"], p["soft"], p["veil_hi"], p["accent"])
        self._pack_card()
        self.lbl_app.configure(text="통합 문서1 - 저장됨" if xl else "켠")
        colx = int(34 * sc)                  # 번호 열(A) 너비 = 구분선 위치
        textx = colx + int(8 * sc)           # 본문 열(B)의 글자 시작 위치(구분선과 간격을 둠)
        t = self.text
        if xl:
            t.configure(padx=int(6 * sc), spacing1=int(3 * sc), spacing3=int(3 * sc), tabs=(textx,))
            self.vline.place(x=colx, y=0, relheight=1.0)  # 본문 글자는 안쪽 여백(6)만큼 더 오른쪽에서 시작
            self.xl_colA.configure(width=colx)
            t.tag_configure("num", font=self.f_smallb, foreground=p["muted"], offset=0)
        else:
            t.configure(padx=0, spacing1=0, spacing3=0, tabs="")
            self.vline.place_forget()
            t.tag_configure("num", font=self.f_num, foreground=p["accent"], offset=int(4 * sc))
        for name, lab in self.xl_menu_items:
            lab.configure(fg=p["accent"] if name == "파일" else p["text"] if name == "홈" else p["muted"])
        t.tag_configure("hang", lmargin1=0, lmargin2=textx if xl else 0)
        t.tag_configure("row0", background=p["card"])
        t.tag_configure("row1", background=p["zebra"])
        # 가린 낱말은 글자색을 배경색과 같게 해 같은 폭의 띠로 보이게 한다(글자 수 힌트가 남음)
        t.tag_configure("hid", foreground=p["veil"], background=p["veil"])
        t.tag_configure("shown", foreground=p["accent"])
        t.tag_raise("shown")
        t.tag_raise("hid")  # 줄무늬(row0/row1)보다 위에 있어야 가린 글자가 비치지 않는다
        self._style_recite_ui()
        self.root.configure(bg=p["border"])

    def _hover(self, on: bool) -> None:
        p = self._p
        self.btn.configure(bg=p["accent"] if on else p["soft"], fg=p["btn_fg"] if on else p["accent"])

    # ---- 이동 / 스크롤 ----
    def _drag_start(self, e) -> None:
        self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _drag_move(self, e) -> None:
        self.root.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    def _wheel(self, e) -> None:
        """본문 영역을 휠로 넘긴다(설정 창 같은 다른 창 위에서는 넘기지 않는다)."""
        try:
            if e.widget.winfo_toplevel() is not self.root:
                return
        except (AttributeError, self.tk.TclError):
            return
        notches = -int(e.delta / 120) or (-1 if e.delta > 0 else 1)  # 터치패드의 작은 값도 한 칸은 움직인다
        self.scroller.scroll(notches * 2)

    # ---- 내용 ----
    def pick(self, today: date) -> int:
        """오늘의 말씀이 계획표(plan["days"])의 몇 번째인지. 지금 읽는 길(self.track) 안에서 날짜대로 하루에 하나씩 나아간다."""
        n = len(self.track)
        if self.preview_day:
            self.pos = (self.preview_day - 1) % n
        else:
            start = self.state.start_date
            if start is None:
                self.state.start_date = start = today
            self.pos = day_index(start, today, n)
        return self.track[self.pos]

    @staticmethod
    def blocks_of(d: dict) -> list[tuple[str, str]]:
        """해설 블록 [(라벨, 글)]. 형식이 있는 계획은 blocks, 이전 형식의 계획은 explain 하나."""
        if d.get("blocks"):
            return [(b["label"], b["text"]) for b in d["blocks"]]
        return [("묵상", d["explain"])]

    def _set_compact(self, on: bool) -> None:
        self.compact = on
        self._apply_fonts()

    # ---- 암송 모드 ----
    def _hidden(self, code: str) -> bool:
        return code in "123" and int(code) <= self.level   # 코드 4(조사·어미)와 0(공백·부호)은 늘 보인다

    def _style_recite_ui(self) -> None:
        """스위치·단계 칩·안내 줄의 겉모양을 현재 설정에 맞춘다."""
        if not self.can_recite:
            return
        p, on = self._p, self.recite
        self.switch.configure(text="◉ 암송" if on else "○ 암송", fg=p["accent"] if on else p["muted"])
        for chip in self.chips.values():
            chip.pack_forget()
        if on:
            for lv in (3, 2, 1):  # 오른쪽부터 3,2,1 을 넣어 화면에는 1 2 3 으로 보이게
                chip = self.chips[lv]
                sel = lv == self.level
                chip.configure(bg=p["accent"] if sel else p["chip"], fg=p["btn_fg"] if sel else p["muted"])
                chip.pack(side="right", padx=(int(3 * self.sc), 0), before=self.switch)
            self.lbl_rhint.configure(text=f"{self.level}단계 · {RECITE_LEVELS[self.level]} · 눌러서 보기")

    def _insert_masked(self, vi: int, tx: str, codes: str) -> None:
        """한 구절을 넣는다. 단계에 해당하는 글자는 hid 태그(띠)로, 이미 눌러 본 낱말은 shown 태그로 넣는다."""
        t = self.text
        if len(codes) != len(tx):  # 가림 정보가 어긋나면 그냥 보여 준다
            t.insert("end", tx)
            return
        wi = -1
        for m in re.finditer(r"\S+|\s+", tx):
            word = m.group(0)
            if word.isspace():
                t.insert("end", word)
                continue
            wi += 1
            seen = (vi, wi) in self.revealed
            word_codes = codes[m.start():m.end()]
            i = 0
            while i < len(word):  # 같은 상태(가림/보임)가 이어지는 글자끼리 묶어서 넣는다
                hide = self._hidden(word_codes[i])
                j = i
                while j < len(word) and self._hidden(word_codes[j]) == hide:
                    j += 1
                if hide:
                    t.insert("end", word[i:j], ("shown" if seen else "hid", f"w{vi}_{wi}"))
                else:
                    t.insert("end", word[i:j])
                i = j

    def _fill_text(self) -> None:
        """본문을 채운다. 암송 모드이면 단계에 해당하는 글자를 가린다. 엑셀 스타일은 구절마다 한 줄(행)로 놓는다."""
        d = self.days[self.idx]
        t = self.text
        xl = self.skin == "excel"
        t.configure(state="normal")
        t.delete("1.0", "end")
        lvs = d.get("lv") if self.recite else None
        prev_c, n = None, len(d["verses"])
        for vi, (c, v, tx) in enumerate(d["verses"]):
            start = t.index("end-1c")
            label = f"{c}:{v}" if (vi > 0 and c != prev_c) else str(v)
            t.insert("end", f"{label}\t" if xl else f"{label} ", "num")
            if lvs and vi < len(lvs):
                self._insert_masked(vi, tx, lvs[vi])
            else:
                t.insert("end", tx)
            if vi < n - 1:
                t.insert("end", "\n" if xl else "  ")
            if xl:  # 번호 열 오른쪽에 맞춰 줄바꿈하고, 한 줄 걸러 옅은 줄무늬
                t.tag_add("hang", start, "end")
                t.tag_add(f"row{vi % 2}", start, "end")
            prev_c = c
        t.configure(state="disabled")

    def _reveal(self, e) -> str:
        """가려진 낱말을 누르면 그 낱말(어절 안의 가려진 부분 전부)을 보여 준다."""
        t = self.text
        for tag in t.tag_names(t.index(f"@{e.x},{e.y}")):
            m = re.fullmatch(r"w(\d+)_(\d+)", tag)
            if m:
                self.revealed.add((int(m[1]), int(m[2])))
                rng = t.tag_ranges(tag)
                for a, b in zip(rng[::2], rng[1::2]):
                    t.tag_remove("hid", a, b)
                    t.tag_add("shown", a, b)
                break
        return "break"

    def _rehide(self) -> None:
        self.revealed.clear()
        self._fill_text()

    def _set_level(self, n: int) -> None:
        self.set_setting("recite_level", n)

    def _toggle_recite(self) -> None:
        if self.can_recite:
            self.set_setting("recite", not self.recite)

    # ---- 배치 ----
    def _fit(self) -> tuple[int, int, bool]:
        """창 크기를 정한다. 폭은 W, 높이는 폭 x ASPECT(낮은 화면이면 화면 높이까지). 머리줄과 바닥줄을 뺀 나머지가
        본문 스크롤 영역이다. 마지막 값은 본문 영역을 최소한(몇 줄)은 확보했는지."""
        left, top, right, bottom = work_area()
        avail = (bottom - top) - 2 * int(16 * self.sc)
        w = int(self.W * self.sc)
        self.root.update_idletasks()
        chrome = self.root.winfo_reqheight() - 1     # 본문 영역(캔버스 높이 1)을 뺀 고정 줄들의 높이
        line_h = self.f_body.metrics("linespace") + self.spacing2
        floor = chrome + 7 * line_h                 # 본문이 적어도 7줄은 보여야 한다
        h = min(max(int(w * ASPECT), floor), avail)
        return w, h, floor <= avail

    def _layout(self) -> None:
        """현재 내용으로 레이아웃을 잡는다. 고정 비율의 창에 본문 영역이 너무 좁게 남으면 글자를 줄여 한 번 더 그린다."""
        self._set_compact(False)
        self.render()
        w, h, ok = self._fit()
        if not ok:
            self._set_compact(True)
            self.render()
            w, h, ok = self._fit()
        self._size = (w, h)

    def _place(self, w: int, h: int, keep: tuple[int, int, int, int] | None = None) -> None:
        """설정한 모서리(corner)에 놓는다. keep=(x, y, w, h) 이면 현재 창의 그 모서리는 그대로 두고 크기만 바꾼다."""
        left, top, right, bottom = work_area()
        m = int(16 * self.sc)
        corner = self.cfg["corner"]
        if keep:
            x0, y0, w0, h0 = keep
            x = x0 if "l" in corner else x0 + w0 - w
            y = y0 if "t" in corner else y0 + h0 - h
        else:
            x = left + m if "l" in corner else right - w - m
            y = top + m if "t" in corner else bottom - h - m
        x = max(left, min(x, right - w))
        y = max(top, min(y, bottom - h))
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.update_idletasks()  # 연달아 설정을 바꿔도 현재 위치를 정확히 읽을 수 있게

    def reflow(self, snap: bool = False) -> None:
        """스킨, 글자 크기, 암송 같은 설정이 바뀐 뒤 다시 그린다. snap 이면 설정한 모서리로 옮긴다."""
        self._apply_width()
        self._apply_theme()
        if not self.visible:
            self._layout()
            return
        keep = None if snap else (self.root.winfo_x(), self.root.winfo_y(),
                                  self.root.winfo_width(), self.root.winfo_height())
        self._layout()
        self._place(*self._size, keep)

    def render(self) -> None:
        d = self.days[self.idx]
        today = self.current_date or self.today_fn()
        pad, sc = int(18 * self.sc), self.sc
        self._style_recite_ui()
        self.lbl_date.configure(text=f"{today.month}월 {today.day}일 ({WEEKDAY[today.weekday()]})")
        if self.route["id"] == ROUTE_ALL:
            self.lbl_prog.configure(text=f"{d['section']} · {d['day']} / {len(self.days)}")
        else:
            self.lbl_prog.configure(text=f"{self.route['name']} · {self.pos + 1} / {len(self.track)}")
        self.lbl_ref.configure(text=d["ref"])
        self.lbl_title.configure(text=d["title"])
        self.xl_cell.configure(text=d["ref"])
        self.xl_name.configure(text=f"B{len(d['verses']) + 1}")
        # 표제(시편)와 병행 본문(복음서)은 본문 바로 위에 순서대로 둔다
        self.lbl_note.pack_forget()
        self.lbl_par.pack_forget()
        self.rrow.pack_forget()
        anchor = self._anchor()
        for lbl, text in ((self.lbl_note, d.get("note")),
                          (self.lbl_par, ("병행: " + " · ".join(d["parallels"])) if d.get("parallels") else "")):
            if text:
                lbl.configure(text=text)
                lbl.pack(fill="x", padx=pad, pady=(0, int(6 * sc)), before=anchor)
        if self.recite:
            self.rrow.pack(fill="x", padx=pad, pady=(0, int(4 * sc)), before=anchor)
        for lab, txt in self.blocks:
            lab.pack_forget()
            txt.pack_forget()
        for i, ((label, text), (lab, txt)) in enumerate(zip(self.blocks_of(d), self.blocks)):
            lab.configure(text=label)
            txt.configure(text=text)
            lab.pack(fill="x", pady=(0 if i == 0 else int(8 * sc), 0))
            txt.pack(fill="x", pady=(int(2 * sc), 0))

        t = self.text
        self._fill_text()
        px = self._body_px()
        t.configure(width=max(10, px // self.f_body.measure("0")))
        self.text_frame.configure(width=px)
        self.root.update_idletasks()
        # 줄 간격(spacing2)까지 반영한 실제 픽셀 높이로 영역을 잡는다(마지막 줄이 잘리지 않게).
        # 본문은 자르지 않고 전부 펼친다. 길면 바깥의 스크롤 영역이 넘긴다
        line_h = self.f_body.metrics("linespace") + self.spacing2
        try:  # Tk 는 줄 높이를 비동기로 계산하므로 읽기 전에 끝내 둔다
            t.tk.call(t._w, "sync")
        except self.tk.TclError:
            pass
        first = lambda r, default: r[0] if isinstance(r, tuple) else int(r or default)  # noqa: E731
        need = first(t.count("1.0", "end", "ypixels"), 0)
        nlines = first(t.count("1.0", "end", "displaylines"), 1)
        need = max(need, nlines * line_h - self.spacing2)  # 계산이 덜 끝난 경우의 하한
        self.text_frame.configure(height=need + 2)
        self.root.update_idletasks()
        self.scroller.to_top()
        self.scroller.sync()

    # ---- 표시 / 닫기 ----
    def show(self) -> None:
        self.reload_settings()
        self.revealed.clear()  # 다시 뜰 때는 처음처럼 가린 상태로
        self._apply_width()
        self._apply_theme()
        # 숨겨진 창은 레이아웃이 확정되지 않아 본문 폭을 잘못 읽는다 → 폭을 먼저 확정한 뒤 줄 수를 잰다
        self.root.geometry(f"{int(self.W * self.sc)}x{int(self.W * self.sc * ASPECT)}+0+0")
        self.root.update_idletasks()
        self._layout()  # 고정 비율의 크기를 정한다(본문 영역이 너무 좁으면 글자를 줄여 다시 그림)
        self._place(*self._size)
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", bool(self.cfg["topmost"]))
        self.root.update_idletasks()
        self._round_corners()
        self.visible = True

    def _round_corners(self) -> None:
        try:  # Windows 11 모서리 둥글게 (실패해도 무시)
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
            pref = ctypes.c_int(2)  # DWMWCP_ROUND
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(pref), ctypes.sizeof(pref))
        except Exception:  # noqa: BLE001
            pass

    def dismiss(self) -> None:
        if self.preview_day:
            self.quit()
            return
        self.state.dismissed_date = self.current_date or self.today_fn()
        if self.settings_win is not None and self.settings_win.alive():
            self.settings_win.close()
        if self.routes_win is not None and self.routes_win.alive():
            self.routes_win.close()
        self.root.withdraw()
        self.visible = False

    def quit(self) -> None:
        self._quitting = True
        for aid in (self._tick_id, self._go_id):  # 예약된 타이머를 정리하고 닫는다
            if aid:
                try:
                    self.root.after_cancel(aid)
                except self.tk.TclError:
                    pass
        try:
            self.root.destroy()
        except self.tk.TclError:
            pass

    # ---- 주기 확인: 자정(날짜 변경), 다른 프로세스의 신호 ----
    def refresh(self, today: date, show: bool) -> None:
        self.current_date = today
        self._follow_route()
        self.idx = self.pick(today)
        self.revealed.clear()
        if show:
            self.show()

    def tick(self) -> None:
        try:
            if not self.preview_day:
                if self.updates_enabled:
                    self._poll_update()
                    if self._quitting:
                        return
                sig = self.state.take_signal()
                today = self.today_fn()
                if sig == "quit":
                    self.quit()
                    return
                if sig == "restart":  # kyeon.py --update 가 파일을 바꾼 뒤 보내는 신호
                    self._restart()
                    if self._quitting:
                        return
                if sig in ("show", "settings"):
                    self.state.reload()   # 신호를 보낸 쪽(--route, --skin 등)이 파일에 쓴 값을 읽는다
                    self.refresh(today, show=True)
                    if sig == "settings":
                        self.open_settings()
                elif today != self.current_date:
                    # 새 날(자정 넘김, 절전 복귀 포함): 새 말씀으로 갱신하고 띄움
                    self.refresh(today, show=self.state.dismissed_date != today)
        except Exception:  # noqa: BLE001
            log(traceback.format_exc())
        if self._tick_id:
            try:
                self.root.after_cancel(self._tick_id)
            except self.tk.TclError:
                pass
        self._tick_id = self.root.after(TICK_MS, self.tick)

    def start(self, mode: str) -> None:
        """mode: 'startup' = 로그온 실행(오늘 이미 닫았으면 조용히, 새 버전도 이때 한 번 확인),
        'manual' = 직접 실행(항상 표시), 'resume' = 업데이트 뒤 다시 뜸(닫아 둔 날은 조용히),
        'first' = 설치 직후(바로 보이고, 새 버전도 한 번 확인)"""
        today = self.today_fn()
        if self.preview_day:
            self.refresh(today, show=True)
            return
        self.updates_enabled = not os.environ.get("KYEON_NO_UPDATE")
        if self.updates_enabled:
            self._announce_update_done()
            if mode in ("startup", "first") and self.cfg["update_check"]:  # 자동 확인은 PC 를 켜고 로그온했을 때(또는 설치 직후) 한 번뿐
                self.root.after(UPDATE_FIRST_CHECK_MS, lambda: self.check_now(manual=False))
        show = mode in ("manual", "first") or self.state.dismissed_date != today
        delay = SHOW_DELAY_STARTUP_MS if mode == "startup" else 0

        def go() -> None:
            self.refresh(today, show=show)
            self._tick_id = self.root.after(TICK_MS, self.tick)

        if not show:  # 조용히 대기만
            self.current_date = today
            self.idx = self.pick(today)
            self._tick_id = self.root.after(TICK_MS, self.tick)
        elif delay:
            self._go_id = self.root.after(delay, go)
        else:
            go()

    def _on_error(self, exc, val, tb) -> None:
        log("".join(traceback.format_exception(exc, val, tb)))

    def run(self, mode: str) -> None:
        self.start(mode)
        self.root.mainloop()


# ───────────────────────── 설정 창 ─────────────────────────
class SettingsWindow:
    """화면 스타일, 테마, 글자 크기, 표시 위치, 암송, 읽기 진행, 자동 실행을 바꾸는 창. 누르는 즉시 적용·저장된다."""

    def __init__(self, widget: Widget):
        from tkinter import font as tkfont
        self.w = widget
        tk = self.tk = widget.tk
        self.top = tk.Toplevel(widget.root)
        self.top.title("켠 설정")
        self.top.resizable(False, False)
        self.top.attributes("-topmost", True)
        self.top.protocol("WM_DELETE_WINDOW", self.close)
        self.top.bind("<Escape>", lambda e: self.close())
        self.f = tkfont.Font(family=widget.family, size=10)
        self.fb = tkfont.Font(family=widget.family, size=10, weight="bold")
        self.fh = tkfont.Font(family=widget.family, size=9, weight="bold")
        self.fs = tkfont.Font(family=widget.family, size=9)
        self.chips: dict[str, dict] = {}   # 설정 키 -> {값: 칩 라벨}
        self.rows: dict[str, list] = {}    # 설정 키 -> 흐리게 만들 라벨들
        self._themed: list = []
        self._entry_route = ""             # 일차 입력칸에 숫자를 넣어 둔 길(길이 바뀌면 다시 넣는다)
        self._build()
        self.refresh()
        self._place()

    def alive(self) -> bool:
        try:
            return bool(self.top.winfo_exists())
        except self.tk.TclError:
            return False

    def close(self) -> None:
        if self.alive():
            self.top.destroy()

    def _reg(self, w, **opts):
        self._themed.append((w, opts))
        return w

    def _segment(self, parent, key: str, options, per_row: int = 99):
        tk = self.tk
        fr = self._reg(tk.Frame(parent), bg="card")
        chips = {}
        for i, (value, text) in enumerate(options):
            lab = tk.Label(fr, text=text, font=self.f, cursor="hand2", padx=10, pady=3)
            lab.grid(row=i // per_row, column=i % per_row, padx=(0, 4), pady=(0, 3), sticky="w")
            lab.bind("<Button-1>", lambda e, v=value: self._choose(key, v))
            chips[value] = lab
        self.chips[key] = chips
        return fr

    def _build(self) -> None:
        tk, w = self.tk, self.w
        reg = self._reg
        body = reg(tk.Frame(self.top), bg="card")
        body.pack(fill="both", expand=True)
        inner = reg(tk.Frame(body), bg="card")
        inner.pack(padx=22, pady=(16, 10))
        r = [0]

        def header(text):
            lab = reg(tk.Label(inner, text=text, font=self.fh), bg="card", fg="accent")
            lab.grid(row=r[0], column=0, columnspan=2, sticky="w", pady=(0 if r[0] == 0 else 14, 4))
            r[0] += 1

        def row(key, label, control, note=None):
            a = reg(tk.Label(inner, text=label, font=self.f), bg="card", fg="text")
            a.grid(row=r[0], column=0, sticky="nw", padx=(0, 18), pady=(3, 0))
            control.grid(row=r[0], column=1, sticky="w")
            self.rows[key] = [a]
            r[0] += 1
            if note:
                n = reg(tk.Label(inner, text=note, font=self.fs, anchor="w"), bg="card", fg="muted")
                n.grid(row=r[0], column=1, sticky="w", pady=(0, 2))
                self.rows[key].append(n)
                r[0] += 1

        on_off = [(True, "켬"), (False, "끔")]
        header("화면")
        row("skin", "스타일", self._segment(inner, "skin", [("default", "기본"), ("excel", "엑셀 (업무용)")]))
        row("theme", "테마", self._segment(inner, "theme", [("auto", "자동"), ("light", "라이트"), ("dark", "다크")]),
            note="엑셀 스타일은 밝은 화면으로 고정됩니다")
        row("font", "글자 크기", self._segment(inner, "font", [("small", "작게"), ("normal", "보통"), ("large", "크게")]))
        row("corner", "표시 위치", self._segment(inner, "corner", [("tl", "왼쪽 위"), ("tr", "오른쪽 위"),
                                                                 ("bl", "왼쪽 아래"), ("br", "오른쪽 아래")], per_row=2))
        row("topmost", "항상 위에", self._segment(inner, "topmost", on_off))
        header("암송")
        row("recite", "암송 모드", self._segment(inner, "recite", on_off),
            note=None if w.can_recite else "이 계획표에는 암송용 가림 정보가 없습니다")
        row("recite_level", "가릴 단계", self._segment(inner, "recite_level",
                                                    [(1, "1 핵심 단어"), (2, "2 중요한 말"), (3, "3 뜻 있는 말 전부")]))
        header("읽기")
        rt = reg(tk.Frame(inner), bg="card")
        self.lbl_route = reg(tk.Label(rt, font=self.f, anchor="w"), bg="card", fg="text")
        self.lbl_route.pack(side="left")
        self.btn_route = tk.Label(rt, text="길 바꾸기", font=self.f, cursor="hand2", padx=10, pady=3)
        self.btn_route.pack(side="left", padx=(10, 0))
        self.btn_route.bind("<Button-1>", lambda e: self.w.open_routes())
        rt.grid(row=r[0], column=0, columnspan=2, sticky="w", pady=(0, 6))
        r[0] += 1
        self.lbl_day = reg(tk.Label(inner, font=self.f, anchor="w"), bg="card", fg="text")
        self.lbl_day.grid(row=r[0], column=0, columnspan=2, sticky="w", pady=(0, 4))
        r[0] += 1
        go = reg(tk.Frame(inner), bg="card")
        self.entry = tk.Entry(go, width=6, font=self.f, relief="flat", justify="center")
        self.entry.pack(side="left", ipady=3)
        self.entry.bind("<Return>", lambda e: self._jump())
        self.btn_go = tk.Label(go, text="일차로 이동", font=self.f, cursor="hand2", padx=10, pady=3)
        self.btn_go.pack(side="left", padx=(6, 0))
        self.btn_go.bind("<Button-1>", lambda e: self._jump())
        self.btn_first = tk.Label(go, text="처음부터 다시", font=self.f, cursor="hand2", padx=10, pady=3)
        self.btn_first.pack(side="left", padx=(6, 0))
        self.btn_first.bind("<Button-1>", lambda e: self._first())
        go.grid(row=r[0], column=0, columnspan=2, sticky="w")
        r[0] += 1
        header("시작")
        row("autostart", "로그온할 때 자동 실행", self._segment(inner, "autostart", on_off))
        header("업데이트")
        row("update_check", "새 버전 확인", self._segment(inner, "update_check", on_off),
            note="PC를 켜고 로그온할 때 한 번, GitHub에 새 버전이 있는지만 확인합니다")
        self.lbl_upd = reg(tk.Label(inner, font=self.fs, anchor="w", justify="left"), bg="card", fg="muted")
        self.lbl_upd.grid(row=r[0], column=0, columnspan=2, sticky="w", pady=(2, 4))
        r[0] += 1
        ub = reg(tk.Frame(inner), bg="card")
        self.btn_chk = tk.Label(ub, text="지금 확인", font=self.f, cursor="hand2", padx=10, pady=3)
        self.btn_chk.pack(side="left")
        self.btn_chk.bind("<Button-1>", lambda e: self.w.check_now())
        self.btn_ins = tk.Label(ub, text="업데이트", font=self.f, cursor="hand2", padx=10, pady=3)
        self.btn_ins.bind("<Button-1>", lambda e: self.w.install_update())
        ub.grid(row=r[0], column=0, columnspan=2, sticky="w")
        r[0] += 1
        header("본문")
        self.lbl_credit = reg(tk.Label(inner, text=TEXT_CREDIT, font=self.fs, anchor="w", justify="left"), bg="card", fg="muted")
        self.lbl_credit.grid(row=r[0], column=0, columnspan=2, sticky="w", pady=(0, 2))
        r[0] += 1
        foot = reg(tk.Frame(body), bg="card")
        foot.pack(fill="x", padx=22, pady=(0, 14))
        self.lbl_msg = reg(tk.Label(foot, font=self.fs, anchor="w"), bg="card", fg="muted")
        self.lbl_msg.pack(side="left")
        close = tk.Label(foot, text="닫기", font=self.fb, cursor="hand2", padx=16, pady=4)
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: self.close())
        self.btn_close = close
        reg(tk.Label(foot, text=f"켠 {__version__}", font=self.fs), bg="card", fg="muted").pack(side="right", padx=12)

    def say(self, text: str) -> None:
        self.lbl_msg.configure(text=text)

    def _current(self, key: str):
        if key == "autostart":
            return self.w.autostart_on()
        return self.w.cfg[key]

    def _choose(self, key: str, value) -> None:
        if key == "autostart":
            ok = self.w.set_autostart(value)
            self.say("" if ok else "자동 실행 설정을 바꾸지 못했습니다")
        else:
            self.w.set_setting(key, value)
        self.refresh()

    def _jump(self) -> None:
        txt = self.entry.get().strip()
        n = len(self.w.track)
        if not txt.isdigit() or not (1 <= int(txt) <= n):
            self.say(f"1 부터 {n} 사이의 숫자를 넣어 주세요")
            return
        self.say("")
        self.w.jump_to_day(int(txt))

    def _first(self) -> None:
        self.say("")
        self.w.jump_to_day(1)

    def refresh(self) -> None:
        if not self.alive():
            return
        p, w = self.w._p, self.w
        self.top.configure(bg=p["card"])
        for wd, opts in self._themed:
            wd.configure(**{k: p[v] for k, v in opts.items()})
        dim = {"theme": w.skin == "excel", "recite": not w.can_recite,
               "recite_level": not (w.can_recite and w.recite)}
        for key, chips in self.chips.items():
            cur = self._current(key)
            off = dim.get(key, False)
            for value, lab in chips.items():
                sel = value == cur and not (key in ("theme", "recite_level") and off)
                lab.configure(bg=p["accent"] if sel else p["soft"],
                              fg=p["btn_fg"] if sel else (p["muted"] if off else p["text"]))
        notes = {"theme": "엑셀 스타일은 밝은 화면으로 고정됩니다" if w.skin == "excel" else "",
                 "recite": "" if w.can_recite else "이 계획표에는 암송용 가림 정보가 없습니다",
                 "update_check": "PC를 켜고 로그온할 때 한 번, GitHub에 새 버전이 있는지만 확인합니다"}
        for key, labs in self.rows.items():
            if len(labs) > 1:  # 설명 줄은 해당할 때만 글을 넣는다
                labs[1].configure(fg=p["muted"], text=notes.get(key, ""))
        self.entry.configure(bg=p["soft"], fg=p["text"], insertbackground=p["text"])
        if not self.entry.get() or self._entry_route != w.route["id"]:  # 입력칸에는 오늘 일차를 미리 넣어 둔다(길이 바뀌면 다시)
            self.entry.delete(0, "end")
            self.entry.insert(0, str(w.current_day()))
            self._entry_route = w.route["id"]
        for b in (self.btn_go, self.btn_first, self.btn_chk, self.btn_route):
            b.configure(bg=p["soft"], fg=p["accent"])
        busy = w.update_state == "working" or w._checking
        self.btn_chk.configure(fg=p["muted"] if busy else p["accent"])
        self.btn_ins.configure(bg=p["accent"], fg=p["btn_fg"])
        if w.update_info is not None and w.update_state in ("idle", "error") and not busy:
            self.btn_ins.pack(side="left", padx=(6, 0))   # 새 버전이 있을 때만 '업데이트' 버튼을 보인다
        else:
            self.btn_ins.pack_forget()
        self.lbl_upd.configure(text=w.update_status_text())
        self.btn_close.configure(bg=p["soft"], fg=p["accent"])
        self.lbl_route.configure(text=f"읽는 길: {w.route_label()}")
        self.lbl_day.configure(text=f"오늘은 {w.current_day()}일차 / {len(w.track)}")

    def _place(self) -> None:
        place_beside(self.top, self.w)


def place_beside(top, widget: "Widget") -> None:
    """보조 창을 위젯 왼쪽에 붙여 연다(자리가 없으면 오른쪽, 위젯이 숨어 있으면 화면 가운데). 작업 영역 밖으로 나가지 않게 한다."""
    top.update_idletasks()
    tw, th = top.winfo_reqwidth(), top.winfo_reqheight()
    left, up, right, bottom = work_area()
    if widget.visible:
        wx, wy, ww, wh = (widget.root.winfo_x(), widget.root.winfo_y(), widget.root.winfo_width(), widget.root.winfo_height())
        x = wx - tw - 10 if wx - tw - 10 >= left else min(wx + ww + 10, right - tw)
        y = wy + wh - th
    else:
        x, y = (left + right - tw) // 2, (up + bottom - th) // 2
    top.geometry(f"+{max(left, x)}+{max(up, min(y, bottom - th))}")


class RouteWindow:
    """읽는 길을 고르는 창. 전체 순서, 시기별, 테마별, 갈래별 길이 세로로 나열되고, 하나를 누르면 그 길로 바뀐다.
    다른 길에서 읽던 자리도 보여 주어서, 그 길로 돌아오면 거기서 이어 읽는다는 것을 알 수 있게 한다."""

    def __init__(self, widget: Widget):
        from tkinter import font as tkfont
        self.w = widget
        tk = self.tk = widget.tk
        self.top = tk.Toplevel(widget.root)
        self.top.title("켠 읽는 길")
        self.top.resizable(False, False)
        self.top.attributes("-topmost", True)
        self.top.protocol("WM_DELETE_WINDOW", self.close)
        self.top.bind("<Escape>", lambda e: self.close())
        self.f = tkfont.Font(family=widget.family, size=10)
        self.fb = tkfont.Font(family=widget.family, size=10, weight="bold")
        self.fh = tkfont.Font(family=widget.family, size=9, weight="bold")
        self.fs = tkfont.Font(family=widget.family, size=9)
        self.rows: dict[str, dict] = {}   # 길 id -> 그 줄의 위젯들
        self.heads: list = []             # '시기별' 같은 묶음 제목
        self._build()
        self.refresh()
        self._place()
        self.top.after(30, self._reveal_selected)

    def alive(self) -> bool:
        try:
            return bool(self.top.winfo_exists())
        except self.tk.TclError:
            return False

    def close(self) -> None:
        if self.alive():
            self.top.destroy()

    def _build(self) -> None:
        tk, w, sc = self.tk, self.w, self.w.sc
        pad = int(14 * sc)
        self.body = tk.Frame(self.top)
        self.body.pack(fill="both", expand=True)
        self.lbl_head = tk.Label(self.body, text="읽는 길을 고르세요", font=self.fb, anchor="w")
        self.lbl_head.pack(fill="x", padx=pad, pady=(pad, 2))
        self.lbl_sub = tk.Label(self.body, text="길을 바꿔도 길마다 읽던 자리를 기억합니다. 하루에 하나씩 읽는 것은 그대로입니다.",
                                font=self.fs, anchor="w", justify="left", wraplength=int(300 * sc))
        self.lbl_sub.pack(fill="x", padx=pad, pady=(0, int(8 * sc)))
        self.scroller = Scroller(tk, self.body, sc)
        self.scroller.canvas.configure(width=int(300 * sc), height=int(400 * sc))
        self.scroller.frame.pack(fill="both", expand=True, padx=(pad, int(6 * sc)))
        for kind in ROUTE_KIND_NAMES:
            routes = [r for r in w.plan_routes if r["kind"] == kind]
            if not routes:
                continue
            if kind != "all":
                head = tk.Label(self.scroller.inner, text=ROUTE_KIND_NAMES[kind], font=self.fh, anchor="w")
                head.pack(fill="x", pady=(int(12 * sc), int(4 * sc)))
                self.heads.append(head)
            for r in routes:
                self._row(self.scroller.inner, r)
        self.foot = tk.Frame(self.body)
        self.foot.pack(fill="x", padx=pad, pady=(int(8 * sc), pad))
        self.btn_close = tk.Label(self.foot, text="닫기", font=self.fb, cursor="hand2", padx=16, pady=4)
        self.btn_close.pack(side="right")
        self.btn_close.bind("<Button-1>", lambda e: self.close())
        self.top.bind("<MouseWheel>", self._wheel)

    def _row(self, parent, r: dict) -> None:
        tk, sc = self.tk, self.w.sc
        box = tk.Frame(parent, cursor="hand2", padx=int(10 * sc), pady=int(6 * sc))
        box.pack(fill="x", pady=(0, int(4 * sc)))
        line = tk.Frame(box, cursor="hand2")
        line.pack(fill="x")
        name = tk.Label(line, text=r["name"], font=self.fb, anchor="w", cursor="hand2")
        name.pack(side="left")
        count = tk.Label(line, text=f"{len(r['idxs'])}일", font=self.fs, cursor="hand2")
        count.pack(side="right")
        about = tk.Label(box, text=r["about"], font=self.fs, anchor="w", justify="left", wraplength=int(270 * sc),
                         cursor="hand2")
        if r["about"]:
            about.pack(fill="x")
        more = tk.Label(box, font=self.fs, anchor="w", cursor="hand2")   # 읽던 자리(있을 때만 보인다)
        for wd in (box, line, name, count, about, more):
            wd.bind("<Button-1>", lambda e, rid=r["id"]: self._pick(rid))
        self.rows[r["id"]] = dict(box=box, line=line, name=name, count=count, about=about, more=more)

    def refresh(self) -> None:
        if not self.alive():
            return
        w, p = self.w, self.w._p
        self.top.configure(bg=p["card"])
        for wd in (self.body, self.foot):
            wd.configure(bg=p["card"])
        self.lbl_head.configure(bg=p["card"], fg=p["text"])
        self.lbl_sub.configure(bg=p["card"], fg=p["muted"])
        self.scroller.set_colors(p["card"], p["soft"], p["veil_hi"], p["accent"])
        for head in self.heads:
            head.configure(bg=p["card"], fg=p["accent"])
        self.btn_close.configure(bg=p["soft"], fg=p["accent"])
        saved = w.state.route_positions
        for r in w.plan_routes:
            row, n = self.rows[r["id"]], len(r["idxs"])
            cur = r["id"] == w.route["id"]
            bg, fg, sub = (p["accent"], p["btn_fg"], p["btn_fg"]) if cur else (p["soft"], p["text"], p["muted"])
            row["box"].configure(bg=bg)
            row["line"].configure(bg=bg)
            row["name"].configure(bg=bg, fg=fg)
            row["count"].configure(bg=bg, fg=sub)
            row["about"].configure(bg=bg, fg=sub)
            more = f"지금 {w.pos + 1}일차" if cur else (f"{saved[r['id']] % n + 1}일차에서 이어 읽기" if r["id"] in saved else "")
            row["more"].configure(text=more, bg=bg, fg=sub)
            if more:
                row["more"].pack(fill="x")
            else:
                row["more"].pack_forget()

    def _pick(self, route_id: str) -> None:
        self.close()
        self.w.set_route(route_id)

    def _wheel(self, e) -> None:
        notches = -int(e.delta / 120) or (-1 if e.delta > 0 else 1)
        self.scroller.scroll(notches * 2)

    def _reveal_selected(self) -> None:
        """고른 길이 목록 아래쪽에 있어도 처음부터 보이게 스크롤해 둔다."""
        row = self.rows.get(self.w.route["id"])
        if not self.alive() or not row:
            return
        self.top.update_idletasks()
        y = row["box"].winfo_y() - int(40 * self.w.sc)
        self.scroller.canvas.yview_moveto(max(0.0, min(1.0, y / max(1, self.scroller.content_height()))))
        self.scroller._draw()

    def _place(self) -> None:
        place_beside(self.top, self.w)


# ───────────────────────── 명령줄 ─────────────────────────
def lv_ok(d: dict) -> bool:
    """암송용 가림 정보(lv)가 있으면 구절마다 본문과 같은 길이의 0~4 숫자열이어야 한다."""
    lv = d.get("lv")
    if lv is None:
        return True
    verses = d.get("verses") or []
    return (isinstance(lv, list) and len(lv) == len(verses)
            and all(isinstance(s, str) and len(s) == len(v[2]) and set(s) <= set("01234") for s, v in zip(lv, verses)))


def day_ok(d: dict) -> bool:
    blocks = d.get("blocks")
    if blocks:
        body = (isinstance(blocks, list) and all(isinstance(b, dict) and b.get("label") and b.get("text")
                                                 for b in blocks) and len(blocks) <= Widget.MAX_BLOCKS)
    else:
        body = bool(d.get("explain"))
    return bool(body and d.get("verses") and d.get("title") and d.get("ref") and lv_ok(d))


def cmd_check(plan: dict, state: State) -> int:
    days = plan["days"]
    bad = [d["day"] for d in days if not day_ok(d)]
    print(f"켠 {__version__} | 번역본: {plan.get('translation')} | 총 {len(days)}일 | 내용 누락: {bad or '없음'}")
    today = date.today()
    start = state.start_date or today
    route = find_route(build_routes(plan), state.get("route"))
    pos = day_index(start, today, len(route["idxs"]))
    d = days[route["idxs"][pos]]
    if route["id"] == ROUTE_ALL:
        print(f"오늘({today}) = {d['day']}일차 · {d['section']} · {d['ref']} · {d['title']}")
    else:
        print(f"오늘({today}) = {route_label(route)} {pos + 1}일차 / {len(route['idxs'])} · {d['section']} · {d['ref']} · {d['title']}")
    if d.get("parallels"):
        print("  병행:", " · ".join(d["parallels"]))
    for c, v, t in d["verses"]:
        print(f"  {v} {t}")
    for label, text in Widget.blocks_of(d):
        print(f"[{label}]", text)
    return 1 if bad else 0


def cmd_routes(plan: dict, state: State) -> int:
    """고를 수 있는 읽는 길과 --route 에 쓰는 id 를 보여 준다."""
    cur = find_route(build_routes(plan), state.get("route"))["id"]
    kind = ""
    for r in build_routes(plan):
        if r["kind"] != kind:
            kind = r["kind"]
            print(f"[{ROUTE_KIND_NAMES[kind]}]")
        print(f"  {'*' if r['id'] == cur else ' '} {r['id']}  {r['name']} ({len(r['idxs'])}일)")
    print("* 는 지금 읽는 길. 바꾸려면: python kyeon.py --route <id>   (id 에 공백이 있으면 따옴표로 감쌉니다)")
    return 0


def cmd_route(plan: dict, state: State, route_id: str) -> int:
    routes = build_routes(plan)
    if route_id not in {r["id"] for r in routes}:
        print(f"그런 읽는 길이 없습니다: {route_id}  (목록은 --routes)")
        return 2
    new = switch_route(state, routes, route_id, date.today())
    pos = day_index(state.start_date or date.today(), date.today(), len(new["idxs"]))
    print(f"읽는 길을 바꿨습니다: {route_label(new)} ({pos + 1}일차 / {len(new['idxs'])})")
    _tell_running(state, "show", "실행 중인 위젯에 바로 반영합니다.")
    return 0


def cmd_status(state: State) -> int:
    print(f"켠 {__version__}")
    print("자동 실행 등록:", autostart_get() or "없음")
    try:
        print("읽는 길:", route_label(find_route(build_routes(load_plan()), state.get("route"))))
    except (OSError, ValueError, KeyError):
        pass
    print("시작일(1일차):", state.start_date or "(아직 실행 전)")
    print("오늘 닫음:", "예" if state.dismissed_date == date.today() else "아니오")
    print("상태 폴더:", STATE_DIR)
    return 0


def _tell_running(state: State, cmd: str, msg: str) -> None:
    """위젯이 떠 있으면 신호를 보낸다(떠 있지 않으면 신호 파일이 남아 다음 실행에 영향을 주므로 보내지 않는다)."""
    _handle, running = acquire_single_instance()
    if running:
        state.send(cmd)
        print(msg)


def cmd_update_check(source: str) -> int:
    try:
        m = check_update(source)
    except UpdateError as e:
        print("확인하지 못했습니다:", e)
        return 2
    if m is None:
        print(f"최신 버전입니다 (켠 {__version__})")
        return 0
    print(f"새 버전이 있습니다: {m['version']} (지금 {__version__})")
    for n in m["notes"]:
        print("  -", n)
    print("업데이트하려면:", "kyeon.exe --update" if FROZEN else "python kyeon.py --update")
    return 0


def cmd_update(state: State, source: str, yes: bool) -> int:
    """새 버전으로 바꾼다. 파일이 빠져 있으면 채운다(빈 폴더에서 실행하면 설치가 된다)."""
    try:
        loc = manifest_location(source)
        m = parse_manifest(fetch(loc, UPDATE_MAX_MANIFEST), loc)
        cur = parse_version(__version__)
        changes = plan_changes(m, BASE)
        if cur and m["vt"] < cur and (BASE / "data" / "plan.json").is_file():
            print(f"이 PC 의 켠({__version__})이 더 새 버전입니다. 받을 업데이트가 없습니다.")
            return 0
        if not changes:
            print(f"이미 최신입니다 (켠 {__version__})")
            return 0
        check_python(m)
        print(f"{__version__} -> {m['version']} : 바꿀 파일 {len(changes)}개 ({', '.join(changes)})")
        for n in m["notes"]:
            print("  -", n)
        if not yes:
            try:
                ok = input("업데이트할까요? [y/N] ").strip().lower() in ("y", "yes")
            except (EOFError, RuntimeError):  # RuntimeError: 콘솔 없는 exe 는 입력을 받을 수 없다
                ok = False
            if not ok:
                print("취소했습니다")
                return 1
        apply_update(m, BASE, state.dir)
    except UpdateError as e:
        print("업데이트하지 못했습니다:", e)
        return 2
    print("업데이트했습니다:", m["version"])
    _tell_running(state, "restart", "실행 중인 위젯은 곧 새 버전으로 다시 뜹니다.")
    return 0


def cmd_rollback(state: State) -> int:
    try:
        ver, paths = rollback(BASE, state.dir)
    except UpdateError as e:
        print("되돌리지 못했습니다:", e)
        return 2
    print(f"{ver} 버전의 파일로 되돌렸습니다: {', '.join(paths)}")
    _tell_running(state, "restart", "실행 중인 위젯은 곧 되돌린 버전으로 다시 뜹니다.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="켠 (kyeon) - 화면 한켠, 마음 한가운데")
    ap.add_argument("--version", action="version", version=f"켠 {__version__}")
    ap.add_argument("--startup", action="store_true", help="로그온 시 자동 실행용")
    ap.add_argument("--quit", action="store_true")
    ap.add_argument("--install", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--day", type=int, help="N일차 미리보기")
    ap.add_argument("--route", metavar="ID", help="읽는 길(all, era:<id>, theme:<id>, section:<갈래>). --day 와 함께 쓰면 그 길의 N일차 미리보기, 혼자 쓰면 저장")
    ap.add_argument("--routes", action="store_true", help="고를 수 있는 읽는 길 목록")
    ap.add_argument("--recite", type=int, choices=(1, 2, 3), help="--day 미리보기를 암송 모드(N단계)로 보기")
    ap.add_argument("--skin", choices=("default", "excel"),
                    help="화면 스타일. --day 와 함께 쓰면 미리보기, 혼자 쓰면 저장")
    ap.add_argument("--settings", action="store_true", help="설정 창을 바로 연다")
    ap.add_argument("--update-check", action="store_true", help="새 버전이 있는지 확인")
    ap.add_argument("--update", action="store_true", help="새 버전으로 업데이트(파일이 없으면 설치)")
    ap.add_argument("--yes", action="store_true", help="--update, --setup, --purge 의 확인 질문을 건너뜀")
    ap.add_argument("--rollback", action="store_true", help="직전 업데이트 전의 파일로 되돌림")
    ap.add_argument("--update-url", help="새 버전 정보(latest.json)의 https 주소나 폴더. 기본은 GitHub")
    ap.add_argument("--setup", action="store_true", help="내려받은 kyeon.exe 를 설치(exe 를 처음 실행하면 저절로 이 단계가 됨)")
    ap.add_argument("--purge", action="store_true", help="--uninstall 과 함께: 설치 폴더도 지움")
    ap.add_argument("--purge-records", action="store_true", help="--purge 와 함께: 읽던 기록도 묻지 않고 지움")
    ap.add_argument("--first-run", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--setup-exe", type=Path, help=argparse.SUPPRESS)
    ap.add_argument("--after-update", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--show", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--plan", type=Path, default=PLAN_FILE, help=argparse.SUPPRESS)
    if argv is None and len(sys.argv) > 1:
        attach_console()  # exe 를 터미널에서 옵션과 함께 실행했을 때 결과가 보이게
    a = ap.parse_args(argv)
    state = State()

    def stop_running() -> None:
        # 실행 중일 때만 신호를 보낸다(아니면 신호 파일이 남아 다음 실행이 곧바로 종료됨)
        _handle, running = acquire_single_instance()
        if running:
            state.send("quit")

    if a.setup:
        return cmd_setup(state, a.yes, a.setup_exe or Path(sys.executable))
    if a.status:
        return cmd_status(state)
    if a.update_check:
        return cmd_update_check(update_source(state, a.update_url))
    if a.update:
        return cmd_update(state, update_source(state, a.update_url), a.yes)
    if a.rollback:
        return cmd_rollback(state)
    if a.check:
        return cmd_check(load_plan(a.plan), state)
    if a.routes:
        return cmd_routes(load_plan(a.plan), state)
    if a.route and not a.day:
        return cmd_route(load_plan(a.plan), state, a.route)
    if a.reset:
        state.start_date = date.today()
        state.dismissed_date = None
        state.forget_route_positions()
        print("지금 읽는 길의 1일차부터 다시 시작합니다(다른 길에서 읽던 자리는 지웠습니다). 실행 중이면 --quit 후 다시 실행하세요.")
        return 0
    if a.skin and not a.day:
        state.set("skin", a.skin)
        print("화면 스타일을 저장했습니다:", a.skin)
        _handle, running = acquire_single_instance()
        if running:
            state.send("show")  # 떠 있는 위젯이 새 스타일로 다시 뜸
        return 0
    if a.quit:
        stop_running()
        return 0
    if a.uninstall:
        print("자동 실행 해제:", "완료" if autostart_remove() else "등록되어 있지 않았습니다")
        if autostart_remove(LEGACY_APP):
            print("이전 이름(DailyVerseWidget)의 자동 실행 값도 지웠습니다.")
        remove_app_entries()
        stop_running()
        return cmd_purge(a.yes, a.purge_records) if a.purge else 0
    if a.install:
        load_plan(a.plan)
        autostart_set(autostart_command())
        print("로그온 시 자동 실행 등록 완료:", autostart_get())
        if autostart_remove(LEGACY_APP):
            print("이전 이름(DailyVerseWidget)의 자동 실행 값은 지웠습니다. 그때 실행 중이던 위젯은 --quit 으로 끄세요.")
        state.dismissed_date = None
        spawn_detached()
        print("지금 위젯을 실행했습니다.")
        return 0

    if a.day:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass
        plan = load_plan(a.plan)
        if a.route and a.route not in {r["id"] for r in build_routes(plan)}:
            print(f"그런 읽는 길이 없습니다: {a.route}  (목록은 --routes)")
            return 2
        w = Widget(plan, state, preview_day=a.day, recite=a.recite, skin=a.skin, route=a.route)
        if a.settings:
            w.root.after(700, w.open_settings)
        w.run("manual")
        return 0

    # 업데이트 뒤 다시 뜰 때는 이전 위젯이 끝나 뮤텍스가 풀릴 때까지 기다린다
    handle, running = wait_for_instance_exit() if a.after_update else acquire_single_instance()
    if running:
        if not (a.startup or a.after_update):  # 직접 다시 실행 = 위젯 다시 보이기(--settings 이면 설정 창도 열기)
            state.send("settings" if a.settings else "show")
        return 0
    state.take_signal()  # 지난번에 남은 신호는 버린다
    if FROZEN and BASE == INSTALL_DIR.resolve():
        refresh_app_registration()  # 업데이트로 바뀐 버전을 앱 목록에도 맞춘다
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001
        pass
    try:
        w = Widget(load_plan(a.plan), state)
        if a.settings:
            w.root.after(700, w.open_settings)
        w.run("startup" if a.startup else "first" if a.first_run else
              "resume" if a.after_update and not a.show else "manual")
    except Exception:  # noqa: BLE001
        log(traceback.format_exc())
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
