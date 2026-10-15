"""릴리스 태그에서 latest.json(업데이트 정보)을 만든다.

  python tools/make_manifest.py v0.2.0            latest.json 을 새로 쓴다
  python tools/make_manifest.py v0.2.0 --check    쓰지 않고, 있는 latest.json 이 태그와 맞는지만 확인한다
  python tools/make_manifest.py v0.2.0 --runtime-exe dist/kyeon.exe   새로 만든 kyeon.exe 의 해시와 주소도 함께 적는다
                                                  (주지 않으면 지금 latest.json 에 적힌 실행 파일 정보를 그대로 둔다)

파일 내용은 작업 폴더가 아니라 태그가 가리키는 커밋(git show)에서 읽는다. 그래서 해시가 사용자가 내려받는 파일과 같다.
절차는 docs/RELEASING.md 를 본다.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "kcc920926-droid/kyeon"
# 업데이트로 받는 파일(kyeon.py 의 UPDATE_PATH_RE 가 허용하는 모양이어야 한다). 앞의 둘은 꼭 있어야 한다.
REQUIRED = ("kyeon.py", "data/plan.json")
OPTIONAL = ("install.bat", "uninstall.bat", "show.bat", "README.md", "CHANGELOG.md")
MIN_PYTHON = "3.8"


def git(*args: str) -> bytes:
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True, capture_output=True).stdout


def changelog_notes(text: str, version: str) -> list:
    """CHANGELOG.md 에서 '## 0.2.0 (날짜)' 아래의 '- ' 항목들을 모은다."""
    notes, inside = [], False
    for line in text.splitlines():
        m = re.match(r"##\s+\[?(\d+\.\d+\.\d+)\]?", line)
        if m:
            if inside:
                break
            inside = m.group(1) == version
            continue
        if inside and line.startswith("- "):
            notes.append(line[2:].strip())
    return notes


def runtime_info(exe: Path, tag: str, repo: str = REPO) -> dict:
    """kyeon.exe 의 해시. 한 줄 설치(install.ps1)가 GitHub 릴리스에서 받은 exe 를 이 값으로 확인한다."""
    data = Path(exe).read_bytes()
    return {"name": "kyeon.exe", "url": f"https://github.com/{repo}/releases/download/{tag}/kyeon.exe",
            "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}


def build_manifest(blobs: dict, version: str, tag: str, released: str, notes: list, repo: str = REPO,
                   runtime: dict | None = None) -> dict:
    """blobs: 경로 -> 파일 내용(bytes). 파일 목록 순서는 고정해 같은 입력이면 같은 결과가 나오게 한다."""
    for need in REQUIRED:
        if need not in blobs:
            raise SystemExit(f"{tag} 에 {need} 가 없습니다")
    m = {
        "schema": 1, "app": "kyeon", "version": version, "tag": tag, "released": released,
        "min_python": MIN_PYTHON, "notes": notes,
        "base_url": f"https://raw.githubusercontent.com/{repo}/{tag}/",
        "files": {p: {"sha256": hashlib.sha256(b).hexdigest(), "size": len(b)} for p, b in sorted(blobs.items())},
    }
    if runtime:
        m["runtime"] = runtime
    return m


def blobs_for_tag(tag: str) -> tuple:
    """태그가 가리키는 커밋에서 배포할 파일들을 읽는다. (버전, {경로: 내용}). kyeon.exe 에 넣는 설치용 파일도 이것을 쓴다."""
    mt = re.fullmatch(r"v(\d+\.\d+\.\d+)", tag)
    if not mt:
        raise SystemExit("태그는 v0.2.0 같은 모양이어야 합니다")
    version = mt.group(1)
    try:
        git("rev-parse", "--verify", "--quiet", f"refs/tags/{tag}^{{commit}}")
    except subprocess.CalledProcessError:
        raise SystemExit(f"태그 {tag} 가 없습니다. 먼저 git tag {tag} 를 만드세요") from None
    blobs = {}
    try:  # fonts/ 아래의 글꼴(.otf .ttf)과 라이선스(.txt)도 함께 배포한다
        listed = git("ls-tree", "-r", "--name-only", tag, "fonts").decode("utf-8").split()
    except subprocess.CalledProcessError:
        listed = []
    fonts = tuple(p for p in listed if re.fullmatch(r"fonts/[A-Za-z0-9_][A-Za-z0-9_-]*\.(?:otf|ttf|txt)", p))
    try:  # 계획표가 해마다 나뉘어 있으면 data/plan-<첫 일차>.json 도 함께 배포한다(kyeon.py 의 PLAN_PART_RE 와 같은 모양)
        listed = git("ls-tree", "-r", "--name-only", tag, "data").decode("utf-8").split()
    except subprocess.CalledProcessError:
        listed = []
    plan_parts = tuple(sorted(p for p in listed if re.fullmatch(r"data/plan-\d+\.json", p)))
    for p in REQUIRED + plan_parts + OPTIONAL + fonts:
        try:
            blobs[p] = git("show", f"{tag}:{p}")
        except subprocess.CalledProcessError:
            if p in REQUIRED:
                raise SystemExit(f"{tag} 에 {p} 가 없습니다") from None
    inside = re.search(rb'^__version__ = "([^"]+)"', blobs["kyeon.py"], re.M)
    if not inside or inside.group(1).decode() != version:
        raise SystemExit(f"태그는 {version} 인데 {tag} 의 kyeon.py 의 __version__ 은 "
                         f"{inside.group(1).decode() if inside else '없음'} 입니다")
    return version, blobs


def blobs_from_dir(root: Path = ROOT) -> tuple:
    """작업 폴더의 파일들(시험용 exe 를 만들 때). 릴리스는 반드시 blobs_for_tag 로 태그에서 읽는다."""
    blobs = {}
    fonts = []
    if (root / "fonts").is_dir():
        fonts = [f"fonts/{f.name}" for f in sorted((root / "fonts").iterdir())
                 if f.is_file() and re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]*\.(?:otf|ttf|txt)", f.name)]
    plan_parts = []
    if (root / "data").is_dir():
        plan_parts = [f"data/{f.name}" for f in sorted((root / "data").iterdir()) if f.is_file() and re.fullmatch(r"plan-\d+\.json", f.name)]
    for p in REQUIRED + tuple(plan_parts) + OPTIONAL + tuple(fonts):
        f = root.joinpath(*p.split("/"))
        if f.is_file():
            blobs[p] = f.read_bytes()
        elif p in REQUIRED:
            raise SystemExit(f"{root} 에 {p} 가 없습니다")
    inside = re.search(rb'^__version__ = "([^"]+)"', blobs["kyeon.py"], re.M)
    if not inside:
        raise SystemExit("kyeon.py 에서 __version__ 을 찾지 못했습니다")
    return inside.group(1).decode(), blobs


def from_tag(tag: str, runtime: dict | None = None) -> dict:
    version, blobs = blobs_for_tag(tag)
    notes = changelog_notes(blobs.get("CHANGELOG.md", b"").decode("utf-8"), version)
    if not notes:
        raise SystemExit(f"CHANGELOG.md 에 '## {version}' 항목(- 로 시작하는 줄)이 없습니다")
    released = git("log", "-1", "--format=%cs", f"{tag}^{{commit}}").decode().strip()
    return build_manifest(blobs, version, tag, released, notes, runtime=runtime)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tag")
    ap.add_argument("--out", type=Path, default=ROOT / "latest.json")
    ap.add_argument("--check", action="store_true", help="쓰지 않고 있는 파일이 태그와 맞는지만 확인")
    ap.add_argument("--runtime-exe", type=Path, help="새로 만든 kyeon.exe (해시와 릴리스 주소를 latest.json 에 적는다)")
    a = ap.parse_args()
    if a.runtime_exe:
        runtime = runtime_info(a.runtime_exe, a.tag)
    else:  # 실행 환경(exe)은 거의 안 바뀌므로 지금 latest.json 의 것을 그대로 둔다
        try:
            runtime = json.loads(a.out.read_text(encoding="utf-8")).get("runtime")
        except (OSError, ValueError, AttributeError):
            runtime = None
    m = from_tag(a.tag, runtime)
    text = json.dumps(m, ensure_ascii=False, indent=2) + "\n"
    if a.check:
        try:
            same = json.loads(a.out.read_text(encoding="utf-8")) == m
        except (OSError, ValueError):
            same = False
        print("맞습니다" if same else f"{a.out.name} 이 {a.tag} 와 다릅니다. 다시 만드세요")
        return 0 if same else 1
    a.out.write_text(text, encoding="utf-8", newline="\n")
    print(f"{a.out} 을 썼습니다: 켠 {m['version']}, 파일 {len(m['files'])}개")
    for n in m["notes"]:
        print("  -", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
