"""python -X utf8 show_menus.py 해폴더 일차…   예: show_menus.py y7 3447 3226
그 날의 본문 첫 블록, 지금 '오늘' 단락, 메뉴 네 후보(현재/후보/버림)를 보여 준다. 비슷한 장면을 다른 후보로 다시 쓸 때 쓴다.
작업 폴더에서 돌린다(해폴더와 wordcheck/rejected_scenes.json 을 작업 폴더 기준으로 읽는다)."""
import glob
import json
import sys

folder, days = sys.argv[1], {int(x) for x in sys.argv[2:]}
rejected = set(json.load(open("wordcheck/rejected_scenes.json", encoding="utf-8")))
for ip in sorted(glob.glob(folder + "/items_*.json")):
    items = json.load(open(ip, encoding="utf-8"))
    comments = json.load(open(ip.replace("items_", "commentary_"), encoding="utf-8"))
    for it, c in zip(items, comments):
        if c["day"] not in days:
            continue
        print(f"== {c['day']} {it['ref']} ({it['category']}) 현재 {c['scene']}")
        print("   본문:", c["blocks"][0]["text"][:150].replace("\n", " "))
        print("   오늘:", c["blocks"][-1]["text"])
        for m in it["menu"]:
            tag = "현재" if m["id"] == c["scene"] else ("버림" if m["id"] in rejected else "후보")
            print(f"   [{tag}] {m['id']} {m['name']} {m['words']}")
