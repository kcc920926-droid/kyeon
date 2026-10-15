# 해설을 쓰고 점검하는 도구 (앱이 읽지 않습니다)

3650일 확장에서 해마다 365일(마지막은 95일)을 쓰고 점검하던 도구입니다. `tools/` 의 도구(`assemble.py`, `assign.py`, `dupcheck.py` 등)와 함께 쓰고, 여기 있는 것은 그 위에서 작업 폴더를 기준으로 도는 얇은 도구입니다.

## 작업 폴더 만들기

```bash
python -X utf8 waves/tools/setup_workspace.py 작업폴더
```

이 명령이 다음을 합니다.

- 이 폴더의 도구, `waves/guides/` 의 지침, `waves/wordcheck/` 의 낱말 점검 자료를 작업 폴더로 복사합니다.
- 지금까지 쓴 3650일(`data/plan.json` 과 `waves/pilot`, `waves/year1`~`year8` 의 `days.json`)을 `plan_all/data/` 로, 장면 장부를 `ledger_all.json` 으로 합쳐 둡니다.

그 뒤 환경 변수 `KYEON_REPO` 를 저장소 위치로 정하고 작업 폴더에서 도구를 돌립니다. 낱말 분석에 kiwipiepy 를 쓰는 도구가 있어서 `pip install kiwipiepy` 가 필요합니다. 본문 원본(`build/krv.json`)은 저장소에 올리지 않으므로 따로 두어야 합니다.

## 도구

| 파일 | 하는 일 |
|---|---|
| `wave_check.py 해폴더 조각번호` | 작가가 쓴 한 조각을 점검합니다(형식, 길이, 번역투와 상투 틀의 조각 단위 개수, 말뭉치의 같은 네 어절, 같은 해 다른 날 후보 낱말이 섞였는지 '참고') |
| `rp.py` | 조립에서 걸린 곳을 고칩니다. `collide`(충돌 쌍), `propose`(바꿀 낱말 후보), `wordok`, `show`, `apply`(문장 바꾸기), `rewrite`(같은 범주의 다른 후보로 '오늘' 단락 다시 쓰기) |
| `show_menus.py 해폴더 일차…` | 그 날의 메뉴 후보와 지금 글을 한눈에 봅니다(비슷한 장면을 다시 쓸 때) |
| `scan_names.py 해폴더` | 새 해의 장면 이름을 기존 장면과 견줘 비슷한 쌍(자카드 0.2 이상)과 범주·주제별 묶음을 `scan_names.txt` 로 만듭니다. 눈으로 읽어 비슷한 장면을 찾는 용도입니다 |
| `verify_year.py 첫날 끝날` | 해를 합친 뒤 새 날을 점검합니다(앱의 `day_ok`, 장부 짜임, 이름 비교, 겹친 절, 주제 몰림, 길 순서) |
| `curate_pool.py` | 안 쓴 후보를 지금까지 쓴 글과 장부에 견줘 쓸 수 있는 것만 남기고 `free_pool.json` 을 만듭니다. `wordcheck/bad_words.json` 과 `rejected_scenes.json` 의 후보도 뺍니다 |
| `pool_check2.py 일폴더 파일이름` | 후보 풀을 만들 때 작가가 쓴 후보 파일을 점검합니다(짜임, 주제, 필수어가 기존 글·장부·풀과 겹치는지, 이름이 비슷한 쌍). 작가의 일은 `일폴더/jobs.json` 에서 찾습니다. 풀 지침은 `waves/guides/POOL_GUIDE.md` 와 `POOL2_GUIDE.md` 입니다 |
| `blockfix.py 해폴더 고침.json` | 한 블록 안의 문장을 바꿉니다(`{"일차": [["옛", "새"]]}`, 옛 문장이 정확히 한 번 있어야 합니다) |
| `setup_workspace.py` | 위 작업 폴더를 만듭니다 |

## 한 해를 쓰는 순서

`docs/EXPANSION.md` 의 '한 해(365일)를 쓰는 순서'를 보세요. 작가에게 주는 지침은 `waves/guides/WAVE2_GUIDE.md` 입니다.
