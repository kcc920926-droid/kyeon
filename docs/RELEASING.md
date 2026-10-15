# 릴리스 절차

새 버전을 내는 사람(저장소 관리자)을 위한 문서입니다. 사용자는 `latest.json`이 올라간 순간부터 로그온할 때 새 버전을 안내받습니다.

## 배포물이 두 층입니다

| 층 | 무엇 | 얼마나 자주 바뀌나 | 어떻게 배포하나 |
|---|---|---|---|
| 프로그램과 자료 | `kyeon.py`, `data/plan.json`(과 이어 붙는 `data/plan-<첫 일차>.json`), 글꼴, 문서 | 릴리스마다 | 태그 + `latest.json` (사용자 PC가 스스로 받아 바꿈) |
| 실행 환경 | `kyeon.exe` (Python과 tkinter가 든 껍데기) | 거의 안 바뀜 | GitHub Release의 파일 (사용자가 한 번 내려받아 설치) |

`kyeon.exe`는 옆에 있는 `kyeon.py`를 그대로 실행하기만 합니다. 그래서 글을 고치거나 기능을 더하는 릴리스에서는 exe를 다시 만들 필요가 없습니다. 설치된 `kyeon.py`가 스스로 새 버전으로 바뀝니다.

exe를 다시 만들어야 하는 때는 둘뿐입니다. `kyeon.py`가 exe에 없는 표준 라이브러리 모듈을 가져다 쓰기 시작할 때(아래 3번), 그리고 Python 자체를 올리고 싶을 때입니다.

## 순서

1. **고치고 시험합니다.**
   ```
   python -X utf8 -m unittest discover -s tests
   ```
   `LauncherCoversTheProgram` 시험이 `kyeon.py`의 모든 import가 `tools/launcher.py`의 목록에 있는지 지켜 줍니다.
2. **버전을 올립니다.** `kyeon.py`의 `__version__`이 버전의 유일한 원본입니다. 계획표(`data/plan.json`)만 고쳤어도 올립니다. 클라이언트는 `kyeon.py`의 버전 숫자로 새 버전인지 판단합니다.
3. **`kyeon.py`에 새 모듈을 import했다면 `tools/launcher.py`의 목록에도 더합니다.** 안 더하면 업데이트를 받은 사용자의 프로그램이 시작하지 못합니다. 클라이언트는 받은 `kyeon.py`가 쓰는 모듈이 자기 실행 환경에 있는지 확인하고, 없으면 바꾸지 않고 "새로 내려받아 설치해 주세요"라고 알립니다. 이 경우에만 아래 6번의 exe 빌드가 필요합니다.
4. **`CHANGELOG.md`에 `## 0.2.1 (날짜)` 항목을 씁니다.** `-`로 시작하는 줄이 업데이트 정보에 들어가고, 첫 줄이 위젯의 안내 줄에 보입니다.
5. **커밋하고, 태그를 만들고, 둘 다 올립니다.** 태그가 먼저입니다. 사용자가 받는 파일은 태그 시점의 것입니다.
   ```
   git commit -am "켠 0.2.1: ..."
   git tag v0.2.1
   git push origin main v0.2.1
   ```
   저장소에 릴리스 불변성(Settings > General > Releases > Enable release immutability)을 켜 두었습니다. 릴리스를 게시한 뒤에는 그 태그를 옮길 수 없으니, 태그를 올리기 전에 가리키는 커밋이 맞는지 봅니다(`git rev-parse --short v0.2.1^{commit}`).
6. **(exe가 바뀔 때만) `kyeon.exe`를 만들어 GitHub Release에 올립니다.** 이 PC의 Python을 건드리지 않도록 임시 가상환경에서 빌드합니다.
   ```
   python -m venv build/venv
   build/venv/Scripts/python -m pip install pyinstaller
   build/venv/Scripts/python tools/build_exe.py v0.2.1
   ```
   `dist/kyeon.exe`가 만들어지고, 만든 직후 빈 폴더에서 `--version`과 `--check`를 돌려 보는 시험까지 통과해야 끝납니다. exe 안에는 태그의 설치용 파일이 들어갑니다. 작업 폴더로 시험용 exe만 만들려면 `--worktree`를 씁니다(배포하지 않습니다).

   GitHub 웹에서 `Releases > Draft a new release`로 태그 `v0.2.1`을 고르고 `dist/kyeon.exe`를 올립니다. 파일 이름은 반드시 `kyeon.exe`여야 합니다. README의 내려받기 링크(`releases/latest/download/kyeon.exe`)가 이 이름을 가리킵니다.

   > **주의:** GitHub의 `latest`는 가장 최근에 *릴리스*로 올린 것입니다. 태그만 올린 버전은 릴리스가 아니므로 영향이 없지만, 파일 없이 릴리스를 만들면 내려받기 링크가 깨집니다. 릴리스를 만든다면 항상 `kyeon.exe`를 붙이세요.

   > **불변성 주의:** 릴리스 불변성을 켜 두면 **게시(Publish)한 뒤에는 파일을 더하거나 바꿀 수 없습니다.** 먼저 `Save draft`로 저장해서 `kyeon.exe`를 붙이고, 파일 이름과 크기, 해시(빌드 도구가 마지막에 찍어 준 sha256)가 `dist/kyeon.exe`와 같은지 확인한 다음에 게시하세요. 게시한 뒤에 잘못을 발견하면 같은 번호로 고치려 하지 말고 더 높은 번호로 다시 냅니다.
7. **`latest.json`을 만들어 올립니다.** 이 파일이 올라가는 순간이 배포 시점입니다.
   ```
   python tools/make_manifest.py v0.2.1 --runtime-exe dist/kyeon.exe     # 6번에서 exe를 새로 만들었을 때
   python tools/make_manifest.py v0.2.1                                  # 아닐 때(지금 latest.json 의 exe 정보를 그대로 둠)
   git add latest.json
   git commit -m "latest.json: 0.2.1"
   git push origin main
   ```
   도구는 태그가 가리키는 커밋에서 파일을 읽어 SHA-256을 계산하고, `kyeon.py`의 `__version__`이 태그와 같은지, `CHANGELOG.md`에 항목이 있는지 확인합니다. `--runtime-exe`를 주면 exe의 해시와 릴리스 주소가 `runtime` 항목으로 들어갑니다. 한 줄 설치(`install.ps1`)가 이 해시로 받은 exe를 확인합니다.
8. **올라간 것을 확인합니다.** `raw.githubusercontent.com`은 5분쯤 캐시합니다. exe를 올렸다면 `https://api.github.com/repos/kcc920926-droid/kyeon/releases/latest`의 `assets[].digest`가 `latest.json`의 `runtime.sha256`과 같은지도 봅니다.
   ```
   python tools/make_manifest.py v0.2.1 --check
   python kyeon.py --update-check --update-url https://raw.githubusercontent.com/kcc920926-droid/kyeon/main/latest.json
   ```
9. **ZIP이 필요하면** 태그에서 만듭니다. Python이 있는 사람이 소스로 돌릴 때 씁니다. GitHub의 `Code > Download ZIP`도 같은 파일 구성입니다(`tools/`와 `latest.json`은 제외됩니다).
   ```
   git archive --format=zip --prefix=kyeon/ -o kyeon-0.2.1.zip v0.2.1
   ```

## exe를 새로 만든 날의 확인 목록

만든 exe를 배포하기 전에, 임시 폴더와 임시 레지스트리 키로 처음부터 끝까지 한 번 돌려 봅니다(이 PC의 실제 설치와 등록은 건드리지 않습니다). 환경변수 `KYEON_INSTALL_DIR`, `KYEON_STATE_DIR`, `KYEON_START_MENU_DIR`, `KYEON_RUN_KEY`, `KYEON_UNINSTALL_KEY`를 임시 값으로 바꾸면 됩니다.

- 내려받은 것처럼 빈 폴더에 둔 exe를 인자 없이 실행하면 "설치할까요?" 창이 뜨고, 예를 누르면 설치된다.
- 설치 폴더에 `kyeon.exe`, `kyeon.py`, `data/plan.json`, `fonts/`가 생기고, 자동 실행·앱 목록·시작 메뉴가 등록되고, 위젯이 뜬다.
- `--update`로 새 버전을 받으면 떠 있던 위젯이 스스로 다시 뜨고, 12초 뒤에도 살아 있다(옛 프로세스의 임시 폴더를 물려받지 않는지 확인).
- `--rollback`, `--uninstall --purge`가 된다. 제거하면 설치 폴더와 등록이 사라진다.
- `install.ps1`이 `latest.json`의 `runtime`으로 exe를 받아 해시를 확인한 뒤 설치하고, 해시가 다르면 설치하지 않는다.

## 잘못 낸 릴리스

- 클라이언트는 **더 높은 버전**일 때만 새 버전으로 안내합니다. 낮은 버전으로 되돌리는 업데이트는 없습니다.
- 아직 받지 않은 사람을 막으려면 `latest.json`을 직전 태그로 다시 만들어 올립니다(`python tools/make_manifest.py v0.2.0`).
- 릴리스 불변성을 켠 뒤에 게시한 릴리스는 파일과 태그를 고칠 수 없습니다. 같은 번호로 고치려 하지 말고 더 높은 번호로 냅니다.
- 이미 받은 사람은 더 높은 번호(0.2.2)로 고쳐서 냅니다. 급하면 사용자가 `kyeon.exe --rollback`(Python으로 돌린다면 `python kyeon.py --rollback`)으로 직전 파일로 돌아갈 수 있습니다.

## 클라이언트가 지키는 것

`kyeon.py`의 업데이트 코드가 아래를 확인합니다. 릴리스를 만들 때도 같은 전제로 만듭니다.

- `latest.json`의 `files`에는 `kyeon.py`, `data/plan.json`, `data/plan-<첫 일차>.json`, `install.bat`, `uninstall.bat`, `show.bat`, `README.md`, `CHANGELOG.md`, `fonts/*` 같은 **정해진 이름**만 쓸 수 있습니다. 폴더 안의 `data/*.json`, `fonts/*.otf .ttf .txt`와 최상위 `.py .bat .md .txt` 파일만 허용하고, 그 밖의 경로는 목록 전체를 거부합니다. **`.exe`는 업데이트로 받지 않습니다.** 새 파일 형식을 더하려면 `UPDATE_PATH_RE`부터 고쳐서 먼저 내보내야 합니다.
- 파일 주소는 `latest.json`을 받은 서버와 같은 서버여야 하고 `https`여야 합니다.
- 받은 파일은 해시와 크기가 목록과 같아야 하고, `kyeon.py`는 문법과 `__version__`이 목록과 같아야 하며, 쓰는 모듈이 실행 환경에 모두 있어야 하고, 계획표(`plan.json`과 `plan-<첫 일차>.json`을 이어 붙인 것)는 일차 번호가 1부터 빈틈없이 이어져야 합니다. 이번에 안 바뀐 계획표 파일은 지금 설치된 것으로 합쳐서 봅니다. 하나라도 틀리면 아무것도 바꾸지 않습니다.
- 바꾸기 전 파일은 `%LOCALAPPDATA%\Kyeon\backup\<이전 버전>`에 보관합니다(최근 3개).

## 제거가 지우는 것

설정 > 앱의 `켠`을 지우면 `kyeon.exe --uninstall --purge`가 돕니다. 자동 실행 값, 앱 목록 항목, 시작 메뉴 바로가기를 지우고, 프로그램이 끝난 뒤 임시 `.cmd`가 설치 폴더를 정리합니다. 이때 **우리가 둔 파일(`kyeon.exe`, `kyeon.py`, 문서, `data`, `fonts`)과 하위 폴더만** 지우고, 모르는 파일이 남아 있으면 그 폴더는 그대로 둡니다. 설치 폴더(`%LOCALAPPDATA%\Programs\Kyeon`)가 아닌 곳에서는 아무것도 지우지 않습니다. 읽던 기록(`%LOCALAPPDATA%\Kyeon`)은 사용자에게 물어서 지웁니다.

## 신뢰의 범위

사용자 PC는 이 저장소를 믿습니다. 저장소를 통제하는 사람은 모든 사용자의 PC에서 코드를 실행시킬 수 있다는 뜻입니다. 그래서 관리자 계정에 2단계 인증을 켜고, `main`과 `v*` 태그에 보호 규칙을 두기를 권합니다. 코드 서명 검증은 아직 없습니다.

`kyeon.exe`에도 전자서명이 없습니다. 브라우저로 내려받아 실행하면 Windows가 "알 수 없는 게시자" 경고를 보일 수 있고, PC의 보안 설정(스마트 앱 컨트롤, 회사 정책)에 따라 막힐 수 있습니다. 경고 없이 널리 쓰이게 하려면 코드 서명이 필요합니다. 오픈소스 프로젝트에 서명을 무료로 해 주는 곳(예: SignPath Foundation)도 있으니, 사용자가 늘면 신청을 검토하세요.

## GitHub 저장소 설정 (웹에서 한 번만)

저장소가 **Public**이어야 로그인 없이 업데이트를 확인하고 exe를 내려받을 수 있습니다(Settings > General > Danger Zone > Change visibility).

- **About 설명:** `화면 한켠, 마음 한가운데. 하루에 한 덩이, 개역한글 말씀과 그 시대의 뜻을 띄우는 Windows 위젯`
- **Topics:** `bible` `korean` `widget` `windows` `tkinter` `desktop-widget`
- **Social preview:** `docs/social-preview.png`를 올립니다(Settings > General > Social preview). 메신저에 저장소 주소를 붙일 때 미리보기 그림으로 쓰입니다.
- **Releases:** 첫 릴리스(`v0.2.0`)에 `kyeon.exe`를 붙였습니다(위 6번). Settings > General > Releases의 `Enable release immutability`를 켜 두었습니다. `v0.2.0`은 이 설정을 켜기 전에 게시해서 릴리스 API에 `immutable: false`로 나옵니다. 이후 릴리스부터 적용되는지는 다음 릴리스를 게시한 뒤 `immutable` 값으로 확인합니다.
