# 라이선스 안내

이 저장소에는 우리가 만든 것과 가져다 쓴 것이 섞여 있습니다. 부분마다 조건이 다르므로 아래처럼 나눠 적습니다.

| 부분 | 라이선스 |
|---|---|
| 프로그램과 도구: `kyeon.py`, `tools/`, `tests/`, `install.ps1`, `install.bat`, `uninstall.bat`, `show.bat`, 그리고 `kyeon.exe`의 우리 쪽 코드 | [MIT](LICENSE) |
| 글과 자료: 해설(`data/plan.json`의 `blocks`), 시기·테마(`era`, `themes`, `routes`), 암송 가림 정보(`lv`), `README.md`, `docs/`, `CHANGELOG.md` | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.ko) |
| 성경 본문(`data/plan.json`의 `verses`) | **이 프로젝트의 라이선스에 포함되지 않습니다.** 아래 '성경 본문'을 보세요 |
| 글꼴 `fonts/RIDIBatang.otf` | SIL Open Font License 1.1 ([`fonts/LICENSE.txt`](fonts/LICENSE.txt)) |
| `kyeon.exe` 안에 든 Python, Tcl/Tk, PyInstaller | 아래 '`kyeon.exe`에 든 것' |

## CC BY 4.0은 이렇게 씁니다
해설과 자료를 가져다 쓰거나 고쳐 쓸 수 있고, 상업적으로 써도 됩니다. 출처만 밝혀 주세요. 예를 들면 이런 한 줄입니다.

> 해설: 켠(kyeon), https://github.com/kcc920926-droid/kyeon, CC BY 4.0

해설은 AI가 썼습니다. AI가 만든 글에 저작권이 생기는지는 나라마다 아직 확실하지 않아서, 위 라이선스는 권리가 있다면 그 범위에서 허락합니다.

## 성경 본문
본문은 대한성서공회의 『성경전서 개역한글판』(1961)입니다. 이 프로젝트가 만든 것이 아니며 위 라이선스에 포함되지 않습니다. 글자는 위키문헌의 [개역한글판](https://ko.wikisource.org/wiki/개역한글판)에서 가져왔습니다.

대한성서공회의 [저작권 안내](https://www.bskorea.or.kr/bbs/content.php?co_id=subpage2_3_4_1)는 이 판(1961년 7월 10일 첫 발행)의 저작재산권 보호기간이 2011년 12월 31일에 소멸했다고 표시하고, [저작권 관련 FAQ](https://www.bskorea.or.kr/bbs/board.php?bo_table=copyright_faq&wr_id=5)는 저작권료 없이 쓸 수 있되 성명표시권과 동일성유지권은 지켜야 한다고 안내합니다(2026년 10월 확인). 이에 따라 저작자를 다음과 같이 밝히고, 본문을 임의로 바꾸지 않습니다. 가져온 판본에서 손본 곳은 [README](README.md)의 '본문 출처'에 모두 적었습니다.

> 성경 본문: 『성경전서 개역한글판』, 대한성서공회, 1961

대한성서공회가 보호기간 소멸로 표시하지 않은 번역본(개역개정판, 새번역 등)은 쓰려면 대한성서공회의 허락이 필요합니다. 이 저장소는 그런 번역본을 담지 않습니다.

## `kyeon.exe`에 든 것
`kyeon.exe`는 PyInstaller로 만든 껍데기라서 아래가 함께 들어 있습니다. 라이선스 전문은 각 주소에서 볼 수 있습니다.

| 구성 | 라이선스 | 주소 |
|---|---|---|
| Python 실행 환경 | PSF License Version 2 | https://docs.python.org/3/license.html |
| Tcl/Tk (tkinter가 쓰는 화면 도구) | Tcl/Tk License(BSD 계열) | https://www.tcl.tk/software/tcltk/license.html |
| PyInstaller | GPL-2.0-or-later. 만들어진 프로그램은 어떤 조건으로든 배포할 수 있다는 예외가 붙어 있음 | https://pyinstaller.org/en/stable/license.html |

## 만들 때만 쓰고 넣지 않은 것
- [kiwipiepy](https://github.com/bab2min/kiwipiepy)(Kiwi 형태소 분석기, LGPL-2.1)는 암송용 가림 정보(`lv`)를 한 번 계산하는 데만 썼습니다. 프로그램과 모델은 이 저장소에도 `kyeon.exe`에도 들어 있지 않습니다.

## 참고한 규칙
`tools/tlint.py`의 번역투 규칙 가운데 A 계열(A-1, A-2, …)은 [im-not-ai](https://github.com/epoko77-ai/im-not-ai)(epoko77-ai)의 한국어 AI 글투 분류표를 참고해 정규식으로 옮겼습니다. 그 프로젝트의 라이선스는 아래와 같습니다.

```
MIT License

Copyright (c) 2026 epoko77-ai

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## 저작권자 이름
`LICENSE`의 저작권자는 "kyeon contributors"로 적었습니다. 개인이나 단체 이름으로 바꾸려면 `LICENSE`의 이 한 줄만 고치면 됩니다.
