"""릴리스 태그에서 kyeon.exe(Python 이 없는 PC 용 단일 실행 파일)를 만든다.

  python tools/build_exe.py v0.2.0              dist/kyeon.exe 를 만든다
  python tools/build_exe.py v0.2.0 --check      만들지 않고 준비 상태(PyInstaller, import 목록)만 확인한다
  python tools/build_exe.py --worktree          태그 대신 작업 폴더의 파일로 시험용 exe 를 만든다(배포하지 않는다)

PyInstaller 가 필요하다. 이 PC 의 Python 을 건드리지 않으려면 임시 가상환경에서 돌린다.
  python -m venv build/venv && build/venv/Scripts/python -m pip install pyinstaller
  build/venv/Scripts/python tools/build_exe.py v0.2.0

exe 에는 Python 실행 환경(tkinter 포함)과 설치용 파일(태그의 kyeon.py, 자료, 글꼴)이 들어간다. 설치된 뒤의 프로그램 본체는
exe 옆의 kyeon.py 라서 업데이트는 exe 를 다시 만들지 않고도 된다. 절차는 docs/RELEASING.md 를 본다.
"""
import argparse
import ast
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_manifest  # noqa: E402

ROOT = make_manifest.ROOT
LAUNCHER = ROOT / "tools" / "launcher.py"
ICON = ROOT / "tools" / "kyeon.ico"


def imported_modules(src: str) -> set:
    """소스가 가져다 쓰는 모듈 이름(import a.b 는 a.b, from a.b import c 는 a.b)."""
    out = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module and node.module != "__future__":
            out.add(node.module)
    return out


def uncovered(app_src: str, launcher_src: str) -> list:
    """kyeon.py 가 쓰는데 launcher.py 의 import 목록에 없어 exe 에 안 들어갈 모듈(내장 모듈은 제외)."""
    have = imported_modules(launcher_src)
    return sorted(m for m in imported_modules(app_src) if m not in have and m.split(".")[0] not in sys.builtin_module_names)


def have_pyinstaller() -> str | None:
    r = subprocess.run([sys.executable, "-m", "PyInstaller", "--version"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def version_file(version: str, path: Path) -> None:
    """exe 의 '자세히' 탭에 보이는 정보(파일 설명, 버전)."""
    v = tuple(int(x) for x in version.split(".")) + (0,)
    path.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={v}, prodvers={v}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('041204b0', [
      StringStruct('FileDescription', 'Kyeon daily verse widget'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'kyeon'),
      StringStruct('OriginalFilename', 'kyeon.exe'),
      StringStruct('ProductName', 'Kyeon'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1042, 1200])])
  ]
)
""", encoding="utf-8")


def smoke(exe: Path, version: str) -> None:
    """만든 exe 를 빈 폴더에 복사해 돌려 본다. 묶이지 않은 모듈이 있으면 여기서 바로 드러난다.
    표준 입출력을 파이프로 받아도 결과가 나오는지, 프로그램 본체가 읽는 설치용 파일과 글꼴이 들어 있는지까지 본다."""
    with tempfile.TemporaryDirectory(prefix="kyeon-smoke-") as d:
        box = Path(d)
        shutil.copyfile(exe, box / "kyeon.exe")
        env = dict(os.environ, KYEON_STATE_DIR=str(box / "state"), KYEON_NO_UPDATE="1", PYTHONIOENCODING="utf-8")
        for args, want in (("--version", f"켠 {version}"), ("--check", "내용 누락: 없음")):
            r = subprocess.run([str(box / "kyeon.exe"), args], env=env, capture_output=True, timeout=180)
            out = r.stdout.decode("utf-8", "replace")
            if r.returncode != 0 or want not in out:
                log = box / "state" / "launcher.log"
                detail = log.read_text(encoding="utf-8")[-600:] if log.is_file() else out[-300:] + r.stderr.decode("utf-8", "replace")[-300:]
                raise SystemExit(f"만든 exe 가 {args} 에서 실패했습니다 (종료 코드 {r.returncode}):\n{detail}")
    print("시험 실행 통과 (--version, --check)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tag", nargs="?")
    ap.add_argument("--worktree", action="store_true", help="태그 대신 작업 폴더의 파일을 쓴다(시험용)")
    ap.add_argument("--check", action="store_true", help="만들지 않고 준비 상태만 확인")
    ap.add_argument("--dist", type=Path, default=ROOT / "dist")
    a = ap.parse_args()

    if a.worktree:
        version, blobs = make_manifest.blobs_from_dir(ROOT)
        a.tag = f"v{version}"
        print("작업 폴더의 파일로 만드는 시험용 exe 입니다. 배포하지 마세요.")
    elif a.tag:
        version, blobs = make_manifest.blobs_for_tag(a.tag)
    else:
        ap.error("태그(v0.2.0)나 --worktree 가 필요합니다")
    miss = uncovered(blobs["kyeon.py"].decode("utf-8"), LAUNCHER.read_text(encoding="utf-8"))
    if miss:
        print("kyeon.py 가 쓰는 모듈이 tools/launcher.py 의 import 목록에 없습니다. 목록에 더한 뒤 다시 하세요:", ", ".join(miss))
        return 1
    pyi = have_pyinstaller()
    if not pyi:
        print("PyInstaller 가 없습니다. 이 파일 맨 위의 설명대로 임시 가상환경에 설치하세요.")
        return 1
    print(f"켠 {version} / PyInstaller {pyi} / Python {sys.version.split()[0]}")
    if a.check:
        print("준비됐습니다")
        return 0

    work = Path(tempfile.mkdtemp(prefix="kyeon-build-"))
    try:
        seed = work / "seed"
        for rel, data in blobs.items():  # 태그의 파일 그대로(해시가 latest.json 과 같아야 첫 업데이트 확인이 '변경 없음' 이 된다)
            dest = seed.joinpath(*rel.split("/"))
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        vf = work / "version_info.txt"
        version_file(version, vf)
        cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--noconsole",
               "--name", "kyeon", "--distpath", str(a.dist), "--workpath", str(work / "pyi"), "--specpath", str(work),
               "--python-option", "X utf8",  # 열고 쓰는 글자를 늘 UTF-8 로(개발 때 시험하던 -X utf8 과 같게)
               "--add-data", f"{seed};seed", "--version-file", str(vf)]
        if ICON.is_file():
            cmd += ["--icon", str(ICON)]
        cmd.append(str(LAUNCHER))
        print(" ".join(cmd))
        r = subprocess.run(cmd)
        if r.returncode != 0:
            return r.returncode
    finally:
        shutil.rmtree(work, ignore_errors=True)
    exe = a.dist / "kyeon.exe"
    smoke(exe, version)
    data = exe.read_bytes()
    print(f"\n{exe}\n  크기 {len(data):,} 바이트\n  sha256 {hashlib.sha256(data).hexdigest()}")
    print(f"다음: python tools/make_manifest.py {a.tag} --runtime-exe {exe}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
