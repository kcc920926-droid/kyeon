"""kyeon.exe 의 진입점. PyInstaller 가 이 파일을 묶어 exe 를 만든다(tools/build_exe.py).

이 파일은 Python 실행 환경만 제공하고, 프로그램 본체는 exe 옆의 kyeon.py 를 그대로 실행한다.
그래서 업데이트(kyeon.py 와 자료 파일 교체)는 exe 를 다시 만들지 않고도 통한다.
exe 옆에 kyeon.py 가 없으면 내려받은 exe 를 처음 실행한 것이므로, exe 안에 든 설치용 파일(seed/)로 설치한다.
"""
import os
import runpy
import sys
import traceback
from pathlib import Path

# kyeon.py 가 쓰는 표준 라이브러리와, 앞으로 쓸 만한 것들. PyInstaller 는 이 파일의 import 만 따라가므로 여기 적어야 exe 에 들어간다.
# tools/build_exe.py 가 kyeon.py 의 import 가 모두 이 목록에 있는지 확인하고, 업데이트도 새 kyeon.py 가 쓰는 모듈이
# 이 실행 환경에 있는지 확인한 뒤에야 바꾼다.
import __future__  # noqa: F401  (kyeon.py 첫 줄의 from __future__ import annotations 가 쓴다)
import argparse  # noqa: F401
import ast  # noqa: F401
import base64  # noqa: F401
import calendar  # noqa: F401
import collections  # noqa: F401
import colorsys  # noqa: F401
import copy  # noqa: F401
import csv  # noqa: F401
import ctypes  # noqa: F401
import ctypes.wintypes  # noqa: F401
import dataclasses  # noqa: F401
import datetime  # noqa: F401
import difflib  # noqa: F401
import enum  # noqa: F401
import fnmatch  # noqa: F401
import functools  # noqa: F401
import glob  # noqa: F401
import hashlib  # noqa: F401
import html  # noqa: F401
import http.client  # noqa: F401
import importlib.util  # noqa: F401
import io  # noqa: F401
import itertools  # noqa: F401
import json  # noqa: F401
import locale  # noqa: F401
import math  # noqa: F401
import pathlib  # noqa: F401
import queue  # noqa: F401
import random  # noqa: F401
import re  # noqa: F401
import shutil  # noqa: F401
import socket  # noqa: F401
import ssl  # noqa: F401
import string  # noqa: F401
import struct  # noqa: F401
import subprocess  # noqa: F401
import tempfile  # noqa: F401
import textwrap  # noqa: F401
import threading  # noqa: F401
import time  # noqa: F401
import tkinter  # noqa: F401
import tkinter.filedialog  # noqa: F401
import tkinter.font  # noqa: F401
import tkinter.messagebox  # noqa: F401
import tkinter.ttk  # noqa: F401
import typing  # noqa: F401
import unicodedata  # noqa: F401
import urllib.error  # noqa: F401
import urllib.parse  # noqa: F401
import urllib.request  # noqa: F401
import uuid  # noqa: F401
import winreg  # noqa: F401
import zlib  # noqa: F401


def crash(text: str) -> None:
    """콘솔이 없는 exe 에서 시작에 실패하면 아무 반응이 없어 보이므로, 기록을 남기고 메시지 창으로 알린다."""
    try:
        import ctypes
        d = Path(os.environ.get("KYEON_STATE_DIR") or (Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Kyeon"))
        d.mkdir(parents=True, exist_ok=True)
        (d / "launcher.log").write_text(text, encoding="utf-8")
        ctypes.windll.user32.MessageBoxW(
            None, f"켠을 시작하지 못했습니다.\n\n자세한 내용은 아래 파일에 적어 두었습니다.\n{d / 'launcher.log'}", "켠", 0x10)
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    exe = Path(sys.executable).resolve()
    script = exe.with_name("kyeon.py")
    if not script.is_file():  # 내려받은 exe 를 처음 실행했다: exe 안의 설치용 파일로 설치한다
        script = Path(getattr(sys, "_MEIPASS", exe.parent)) / "seed" / "kyeon.py"
        if len(sys.argv) == 1:
            sys.argv.append("--setup")
    sys.argv[0] = str(script)
    try:
        runpy.run_path(str(script), run_name="__main__")
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except BaseException:  # noqa: BLE001
        crash(traceback.format_exc())
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
