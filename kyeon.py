"""켠 (kyeon) - 화면 한켠, 마음 한가운데

조용히 백그라운드에서 돌다가, 로그온할 때와 매일 자정에 오늘의 말씀(개역한글)을 위젯으로 띄웁니다.
읽고 나서 '오늘은 닫기'를 누르면 그날은 다시 뜨지 않습니다.
표준 라이브러리(tkinter)만 사용하며 Windows 에서 동작합니다.

  python kyeon.py              실행(이미 떠 있으면 위젯을 다시 보여 줌)
  python kyeon.py --install    로그온 시 자동 실행 등록 + 지금 실행
  python kyeon.py --uninstall  자동 실행 해제 + 종료
  python kyeon.py --quit       실행 중인 위젯 종료
  python kyeon.py --status     등록/진행 상태 확인
  python kyeon.py --check      데이터 점검 + 오늘의 말씀을 콘솔에 출력
  python kyeon.py --reset      1일차부터 다시 시작
  python kyeon.py --day N      N일차를 미리보기(상태를 바꾸지 않음)
  python kyeon.py --version    버전 표시
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import subprocess
import sys
import traceback
import zlib
from datetime import date, datetime, timedelta
from pathlib import Path

__version__ = "0.1.0"
APP = "Kyeon"
LEGACY_APP = "DailyVerseWidget"  # 켠으로 이름을 바꾸기 전 버전의 자동 실행 값(설치·제거 때 함께 정리)
BASE = Path(__file__).resolve().parent
SCRIPT = BASE / "kyeon.py"
PLAN_FILE = BASE / "data" / "plan.json"
STATE_DIR = Path(os.environ.get("KYEON_STATE_DIR")
                 or (Path(os.environ.get("LOCALAPPDATA") or Path.home()) / APP))
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
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
                    "topmost": ALWAYS_ON_TOP, "recite": False, "recite_level": 1}
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


def load_plan(path: Path = PLAN_FILE) -> dict:
    plan = json.loads(path.read_text(encoding="utf-8"))
    days = plan["days"]
    if not days or [d["day"] for d in days] != list(range(1, len(days) + 1)):
        raise ValueError("plan.json 의 day 번호가 1..N 연속이 아닙니다")
    return plan


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


def pythonw_path() -> str:
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return str(w if w.exists() else exe)


def autostart_command() -> str:
    return f'"{pythonw_path()}" "{SCRIPT}" --startup'


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


def spawn_detached(*args: str) -> None:
    flags = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED | NEW_PROCESS_GROUP | NO_WINDOW
    subprocess.Popen([pythonw_path(), str(SCRIPT), *args],
                     creationflags=flags, close_fds=True)


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

# 암송 모드: 단계별 설명(코드 1=핵심 키워드, 2=그 밖의 내용어, 3=나머지. n단계는 1..n 코드를 가린다)
RECITE_LEVELS = {1: "핵심 단어를 가림", 2: "명사·동사·형용사 등을 가림", 3: "모든 글자를 가림"}


# ───────────────────────── 위젯 ─────────────────────────
class Widget:
    W = 480          # 논리 폭(px, 96dpi 기준). 글자 크기 설정에 따라 인스턴스에서 바뀐다
    MAX_LINES = 20   # 본문 영역이 보여 줄 최대 줄 수(작은 화면에서는 더 줄어듦, 넘으면 스크롤)
    MAX_BLOCKS = 3   # 해설 블록 최대 개수(형식 2 가 3개, 나머지는 2개)
    FONT_BASE = dict(f_app=9, f_small=9, f_smallb=9, f_ref=15, f_title=10, f_note=9, f_body=11, f_num=8,
                     f_expl=10, f_q=10, f_btn=9)
    FONT_COMPACT = dict(f_expl=-1, f_q=-1, f_body=-1)   # 화면이 낮아 안 들어가면 이만큼 줄여 다시 그린다
    FONT_SCALE = {"small": 0.9, "normal": 1.0, "large": 1.2}
    XL_TABS = ("파일", "홈", "삽입", "수식", "데이터", "검토", "보기")  # 엑셀 스타일의 장식용 메뉴 줄

    def __init__(self, plan: dict, state: State, today_fn=date.today, preview_day: int | None = None,
                 recite: int | None = None, skin: str | None = None):
        """recite/skin: 미리보기용으로 암송 모드(0=끔, 1~3=단계)나 화면 스타일을 강제한다. None 이면 저장된 설정을 따른다."""
        import tkinter as tk
        from tkinter import font as tkfont
        self.tk = tk
        self.days = plan["days"]
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
        # 암송 모드: 가림 정보(lv)가 있는 계획에서만 쓸 수 있다
        self.can_recite = any(d.get("lv") for d in self.days)
        self._persist = recite is None and skin is None and preview_day is None
        self.cfg = {k: state.get(k) for k in SETTING_DEFAULTS}
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

        self.family = self._pick_family(tkfont)
        for name, size in self.FONT_BASE.items():
            kw = {"weight": "bold"} if name in ("f_app", "f_smallb", "f_ref", "f_num", "f_btn") else {}
            if name in ("f_note", "f_q"):
                kw = {"slant": "italic"}
            setattr(self, name, tkfont.Font(family=self.family, size=size, **kw))
        self.compact = False  # 화면이 낮아 한 번에 안 들어가면 글자를 줄여 다시 그린다
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
        return self.idx + 1

    def jump_to_day(self, n: int) -> None:
        """오늘이 n일차가 되도록 시작일을 옮긴다."""
        n = max(1, min(len(self.days), int(n)))
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

    # ---- 구성 ----
    @staticmethod
    def _pick_family(tkfont) -> str:
        have = set(tkfont.families())
        for f in ("Malgun Gothic", "맑은 고딕", "Noto Sans CJK KR", "NanumGothic", "Apple SD Gothic Neo"):
            if f in have:
                return f
        return tkfont.nametofont("TkDefaultFont").actual("family")

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
        self.W = round(480 * self.FONT_SCALE[self.cfg["font"]])
        if not hasattr(self, "blocks"):  # 아직 _build 전
            return
        inner = int((self.W - 36) * self.sc)
        for lbl in (self.lbl_title, self.lbl_note, self.lbl_par):
            lbl.configure(wraplength=inner)
        for lab, txt in self.blocks:
            txt.configure(wraplength=inner - int(27 * self.sc))
        self.lbl_q.configure(wraplength=inner - int(27 * self.sc))

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
        self.lbl_prog = reg(tk.Label(self.prog, font=self.f_small, anchor="w"), bg="tool", fg="muted")
        self.lbl_prog.pack(side="left")
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

        # 본문
        self.text_frame = reg(tk.Frame(card, height=10), bg="card")  # 높이는 render() 가 픽셀로 지정
        self.text_frame.pack_propagate(False)
        self.spacing2 = int(5 * sc)
        self.text = reg(tk.Text(self.text_frame, wrap="word", font=self.f_body, relief="flat", bd=0,
                                highlightthickness=0, padx=0, pady=0, cursor="arrow",
                                spacing2=self.spacing2, spacing3=0, takefocus=0, height=1),
                        bg="card", fg="text", selectbackground="soft", inactiveselectbackground="soft")
        self.text.pack(fill="both", expand=True)
        self.vline = reg(tk.Frame(self.text, width=1), bg="grid")  # 엑셀 스타일: 번호 열과 본문 열 사이의 선
        self.text.bind("<MouseWheel>", self._wheel)
        # 가려진 낱말(태그 hid)을 누르면 보인다. break 로 선택 동작이 끼어드는 것을 막는다
        self.text.tag_bind("hid", "<Button-1>", self._reveal)
        self.text.tag_bind("hid", "<Double-Button-1>", lambda e: "break")
        self.text.tag_bind("hid", "<Enter>", lambda e: self.text.configure(cursor="hand2"))
        self.text.tag_bind("hid", "<Leave>", lambda e: self.text.configure(cursor="arrow"))
        self.hint = reg(tk.Label(card, text="▾ 스크롤하여 계속 읽기", font=self.f_small, anchor="w"),
                        bg="card", fg="muted")

        # 묵상 상자
        self.box = reg(tk.Frame(card), bg="soft")
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
        self.sep = reg(tk.Frame(body, height=1), bg="border")
        self.lbl_q = reg(tk.Label(body, font=self.f_q, anchor="w", justify="left"), bg="soft", fg="accent")

        # 바닥줄: 번역본 · 닫기 버튼
        self.foot = reg(tk.Frame(card), bg="card")
        reg(tk.Label(self.foot, text=self.translation, font=self.f_small), bg="card", fg="muted").pack(side="left")
        self.btn = reg(tk.Label(self.foot, text="오늘은 닫기", font=self.f_btn, cursor="hand2",
                                padx=int(12 * sc), pady=int(5 * sc)), bg="soft", fg="accent")
        self.btn.pack(side="right")
        self.btn.bind("<Button-1>", lambda e: self.dismiss())
        self.btn.bind("<Enter>", lambda e: self._hover(True))
        self.btn.bind("<Leave>", lambda e: self._hover(False))
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
        return self.xl_cols if self.skin == "excel" else self.text_frame

    def _pack_card(self) -> None:
        """스킨에 맞게 카드 안의 줄 배치를 새로 한다(표제·병행·암송 안내·스크롤 안내는 render 가 다시 끼운다)."""
        sc, xl = self.sc, self.skin == "excel"
        pad = int(18 * sc)
        for w in (self.head_wrap, self.xl_menu, self.xl_line1, self.xl_formula, self.xl_line2, self.prog_wrap,
                  self.lbl_ref, self.lbl_title, self.lbl_note, self.lbl_par, self.rrow, self.xl_cols,
                  self.text_frame, self.hint, self.box, self.foot, self.xl_tabs_line, self.xl_tabs):
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
        self.text_frame.pack(fill="x", padx=pad)
        self.box.pack(fill="x", padx=pad, pady=(int(14 * sc), 0))
        self.foot.pack(fill="x", padx=pad, pady=(int(12 * sc), int(8 * sc) if xl else int(pad * 0.8)))
        if xl:
            self.xl_tabs_line.pack(fill="x")
            self.xl_tabs.pack(fill="x")

    def _apply_theme(self) -> None:
        self._p = p = self._palette()
        xl, sc = self.skin == "excel", self.sc
        for w, opts in self._themed:
            w.configure(**{k: p[v] for k, v in opts.items()})
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

    def _wheel(self, e) -> str:
        self.text.yview_scroll(-1 if e.delta > 0 else 1, "units")
        self._update_hint()
        return "break"

    def _update_hint(self) -> None:
        more = self._overflow and self.text.yview()[1] < 0.999
        if more:
            self.hint.pack(fill="x", padx=int(18 * self.sc), pady=(int(4 * self.sc), 0), after=self.text_frame)
        else:
            self.hint.pack_forget()

    # ---- 내용 ----
    def pick(self, today: date) -> int:
        if self.preview_day:
            return (self.preview_day - 1) % len(self.days)
        start = self.state.start_date
        if start is None:
            self.state.start_date = start = today
        return day_index(start, today, len(self.days))

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
        return code in "123" and int(code) <= self.level

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
    def _layout(self) -> None:
        """현재 내용으로 레이아웃을 잡는다. 화면보다 높으면 글자를 줄여 한 번 더 그린다."""
        left, top, right, bottom = work_area()
        self._set_compact(False)
        self.render()
        self.root.update_idletasks()
        if self.root.winfo_reqheight() > (bottom - top) - 2 * int(16 * self.sc):
            self._set_compact(True)
            self.render()
            self.root.update_idletasks()

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
        self._place(max(int(self.W * self.sc), self.root.winfo_reqwidth()), self.root.winfo_reqheight(), keep)

    def render(self) -> None:
        d = self.days[self.idx]
        today = self.current_date or self.today_fn()
        pad, sc = int(18 * self.sc), self.sc
        self._style_recite_ui()
        self.lbl_date.configure(text=f"{today.month}월 {today.day}일 ({WEEKDAY[today.weekday()]})")
        self.lbl_prog.configure(text=f"{d['section']} · {d['day']} / {len(self.days)}")
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
        self.sep.pack_forget()
        self.lbl_q.pack_forget()
        for i, ((label, text), (lab, txt)) in enumerate(zip(self.blocks_of(d), self.blocks)):
            lab.configure(text=label)
            txt.configure(text=text)
            lab.pack(fill="x", pady=(0 if i == 0 else int(8 * sc), 0))
            txt.pack(fill="x", pady=(int(2 * sc), 0))
        self.sep.pack(fill="x", pady=(int(10 * sc), int(8 * sc)))
        self.lbl_q.configure(text=d["question"])
        self.lbl_q.pack(fill="x")

        t = self.text
        self._fill_text()
        px = int((self.W - 36) * self.sc)
        t.configure(width=max(10, px // self.f_body.measure("0")))
        self.text_frame.configure(width=px)
        self.root.update_idletasks()
        # 줄 간격(spacing2)까지 반영한 실제 픽셀 높이로 영역을 잡는다(마지막 줄이 잘리지 않게)
        line_h = self.f_body.metrics("linespace") + self.spacing2
        try:  # Tk 는 줄 높이를 비동기로 계산하므로 읽기 전에 끝내 둔다
            t.tk.call(t._w, "sync")
        except self.tk.TclError:
            pass
        first = lambda r, default: r[0] if isinstance(r, tuple) else int(r or default)  # noqa: E731
        need = first(t.count("1.0", "end", "ypixels"), 0)
        nlines = first(t.count("1.0", "end", "displaylines"), 1)
        need = max(need, nlines * line_h - self.spacing2)  # 계산이 덜 끝난 경우의 하한
        # 본문 영역 상한: 화면 작업 영역에서 본문 외 부분(머리·묵상·바닥)을 뺀 만큼, 최대 MAX_LINES 줄
        self.text_frame.configure(height=10)
        self.root.update_idletasks()
        chrome = self.root.winfo_reqheight() - 10
        wa = work_area()
        avail = ((wa[3] - wa[1]) - 2 * int(16 * self.sc) - chrome
                 - self.f_small.metrics("linespace") - int(8 * self.sc))
        cap = max((5 if self.compact else 8) * line_h, min(self.MAX_LINES * line_h, avail))
        self._overflow = need > cap + line_h // 2
        self.text_frame.configure(height=min(need + 2, cap))
        t.yview_moveto(0)
        self._update_hint()

    # ---- 표시 / 닫기 ----
    def show(self) -> None:
        self.reload_settings()
        self.revealed.clear()  # 다시 뜰 때는 처음처럼 가린 상태로
        self._apply_width()
        self._apply_theme()
        # 숨겨진 창은 레이아웃이 확정되지 않아 본문 폭을 잘못 읽는다 → 폭을 먼저 확정한 뒤 줄 수를 잰다
        self.root.geometry(f"{int(self.W * self.sc)}x{int(600 * self.sc)}+0+0")
        self.root.update_idletasks()
        self._layout()  # 낮은 화면이면 글자를 줄여 다시 그림
        self._place(max(int(self.W * self.sc), self.root.winfo_reqwidth()), self.root.winfo_reqheight())
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
        self.root.withdraw()
        self.visible = False

    def quit(self) -> None:
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
        self.idx = self.pick(today)
        self.revealed.clear()
        if show:
            self.show()

    def tick(self) -> None:
        try:
            if not self.preview_day:
                sig = self.state.take_signal()
                today = self.today_fn()
                if sig == "quit":
                    self.quit()
                    return
                if sig in ("show", "settings"):
                    self.refresh(today, show=True)
                    if sig == "settings":
                        self.open_settings()
                elif today != self.current_date:
                    # 새 날(자정 넘김, 절전 복귀 포함): 새 말씀으로 갱신하고 띄움
                    self.refresh(today, show=self.state.dismissed_date != today)
        except Exception:  # noqa: BLE001
            log(traceback.format_exc())
        self._tick_id = self.root.after(TICK_MS, self.tick)

    def start(self, mode: str) -> None:
        """mode: 'startup' = 로그온 실행(오늘 이미 닫았으면 조용히), 'manual' = 직접 실행(항상 표시)"""
        today = self.today_fn()
        if self.preview_day:
            self.refresh(today, show=True)
            return
        show = mode == "manual" or self.state.dismissed_date != today
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
                                                    [(1, "1 핵심 단어"), (2, "2 내용어"), (3, "3 전부")]))
        header("읽기")
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
        n = len(self.w.days)
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
                 "recite": "" if w.can_recite else "이 계획표에는 암송용 가림 정보가 없습니다"}
        for key, labs in self.rows.items():
            if len(labs) > 1:  # 설명 줄은 해당할 때만 글을 넣는다
                labs[1].configure(fg=p["muted"], text=notes.get(key, ""))
        self.entry.configure(bg=p["soft"], fg=p["text"], insertbackground=p["text"])
        if not self.entry.get():  # 입력칸에는 오늘 일차를 미리 넣어 둔다
            self.entry.insert(0, str(w.current_day()))
        for b in (self.btn_go, self.btn_first):
            b.configure(bg=p["soft"], fg=p["accent"])
        self.btn_close.configure(bg=p["soft"], fg=p["accent"])
        self.lbl_day.configure(text=f"오늘은 {w.current_day()}일차 / {len(w.days)}")

    def _place(self) -> None:
        self.top.update_idletasks()
        tw, th = self.top.winfo_reqwidth(), self.top.winfo_reqheight()
        left, top, right, bottom = work_area()
        if self.w.visible:  # 위젯 왼쪽에 붙여 연다(자리가 없으면 오른쪽)
            wx, wy, ww, wh = (self.w.root.winfo_x(), self.w.root.winfo_y(),
                              self.w.root.winfo_width(), self.w.root.winfo_height())
            x = wx - tw - 10 if wx - tw - 10 >= left else min(wx + ww + 10, right - tw)
            y = wy + wh - th
        else:
            x, y = (left + right - tw) // 2, (top + bottom - th) // 2
        self.top.geometry(f"+{max(left, x)}+{max(top, min(y, bottom - th))}")


# ───────────────────────── 명령줄 ─────────────────────────
def lv_ok(d: dict) -> bool:
    """암송용 가림 정보(lv)가 있으면 구절마다 본문과 같은 길이의 0~3 숫자열이어야 한다."""
    lv = d.get("lv")
    if lv is None:
        return True
    verses = d.get("verses") or []
    return (isinstance(lv, list) and len(lv) == len(verses)
            and all(isinstance(s, str) and len(s) == len(v[2]) and set(s) <= set("0123") for s, v in zip(lv, verses)))


def day_ok(d: dict) -> bool:
    blocks = d.get("blocks")
    if blocks:
        body = (isinstance(blocks, list) and all(isinstance(b, dict) and b.get("label") and b.get("text")
                                                 for b in blocks) and len(blocks) <= Widget.MAX_BLOCKS)
    else:
        body = bool(d.get("explain"))
    return bool(body and d.get("question") and d.get("verses") and d.get("title") and d.get("ref") and lv_ok(d))


def cmd_check(plan: dict, state: State) -> int:
    days = plan["days"]
    bad = [d["day"] for d in days if not day_ok(d)]
    print(f"켠 {__version__} | 번역본: {plan.get('translation')} | 총 {len(days)}일 | 내용 누락: {bad or '없음'}")
    today = date.today()
    start = state.start_date or today
    d = days[day_index(start, today, len(days))]
    print(f"오늘({today}) = {d['day']}일차 · {d['section']} · {d['ref']} · {d['title']}")
    if d.get("parallels"):
        print("  병행:", " · ".join(d["parallels"]))
    for c, v, t in d["verses"]:
        print(f"  {v} {t}")
    for label, text in Widget.blocks_of(d):
        print(f"[{label}]", text)
    print("질문:", d["question"])
    return 1 if bad else 0


def cmd_status(state: State) -> int:
    print(f"켠 {__version__}")
    print("자동 실행 등록:", autostart_get() or "없음")
    print("시작일(1일차):", state.start_date or "(아직 실행 전)")
    print("오늘 닫음:", "예" if state.dismissed_date == date.today() else "아니오")
    print("상태 폴더:", STATE_DIR)
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
    ap.add_argument("--recite", type=int, choices=(1, 2, 3), help="--day 미리보기를 암송 모드(N단계)로 보기")
    ap.add_argument("--skin", choices=("default", "excel"),
                    help="화면 스타일. --day 와 함께 쓰면 미리보기, 혼자 쓰면 저장")
    ap.add_argument("--settings", action="store_true", help="설정 창을 바로 연다")
    ap.add_argument("--plan", type=Path, default=PLAN_FILE, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    state = State()

    def stop_running() -> None:
        # 실행 중일 때만 신호를 보낸다(아니면 신호 파일이 남아 다음 실행이 곧바로 종료됨)
        _handle, running = acquire_single_instance()
        if running:
            state.send("quit")

    if a.status:
        return cmd_status(state)
    if a.check:
        return cmd_check(load_plan(a.plan), state)
    if a.reset:
        state.start_date = date.today()
        state.dismissed_date = None
        print("1일차부터 다시 시작합니다. 실행 중이면 --quit 후 다시 실행하세요.")
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
        stop_running()
        return 0
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
        w = Widget(load_plan(a.plan), state, preview_day=a.day, recite=a.recite, skin=a.skin)
        if a.settings:
            w.root.after(700, w.open_settings)
        w.run("manual")
        return 0

    handle, running = acquire_single_instance()
    if running:
        if not a.startup:  # 직접 다시 실행 = 위젯 다시 보이기(--settings 이면 설정 창도 열기)
            state.send("settings" if a.settings else "show")
        return 0
    state.take_signal()  # 지난번에 남은 신호는 버린다
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001
        pass
    try:
        w = Widget(load_plan(a.plan), state)
        if a.settings:
            w.root.after(700, w.open_settings)
        w.run("startup" if a.startup else "manual")
    except Exception:  # noqa: BLE001
        log(traceback.format_exc())
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
