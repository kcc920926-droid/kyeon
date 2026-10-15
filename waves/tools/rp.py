"""조립 충돌 수리 도구(해 폴더 공용): python -X utf8 rp.py <명령> <해 폴더> [인자]
  collide DIR            충돌 쌍(주인 날의 필수어를 다른 날 글이 쓴 곳)과 문장을 보여 줌, DIR/collisions.json 에 저장
  propose DIR            주인 날 오늘 글 속 명사 가운데 다른 날 글이나 필수어에 없는 것(필수어 바꿀 후보)
  wordok DIR 낱말…       낱말이 다른 날 글이나 필수어에 있는지
  show DIR 일차…         그 날의 입력 장면과 해설(link, 오늘)
  apply DIR repair.json  {"text":{일차:[[옛,새]]}, "link":…, "name":{일차:새이름}, "words":{일차:[…]}}
  rewrite DIR rw.json    {"일차": {"scene":id, "link":…, "text":오늘 글, "words":[선택]}}
plan_all/data/plan.json(앞선 해들)과 ledger_all.json(앞선 해들의 필수어)을 기준으로 한다. kiwipiepy venv 의 파이썬으로 돌린다."""
import json
import os
import re
import sys
from pathlib import Path

S = Path(__file__).resolve().parent
REPO = Path(os.environ.get("KYEON_REPO") or S / "kyeon-tools-wt")      # 저장소 위치(환경 변수 KYEON_REPO, 없으면 작업 폴더 안의 kyeon-tools-wt)
sys.path.insert(0, str(REPO / "tools"))


def read(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def write(p, v):
    Path(p).write_text(json.dumps(v, ensure_ascii=False, indent=1), encoding="utf-8")


def chunks(d):
    return sorted(d.glob("items_*.json"))


def sents(t):
    return [x for x in re.split(r"(?<=[.!])\s+", t) if x]


def load_new(d):
    """새 해: texts{일차:오늘}, scene{일차:{...}}"""
    texts, scene = {}, {}
    for ip in chunks(d):
        its, cs = read(ip), read(d / ip.name.replace("items_", "commentary_"))
        for it, c in zip(its, cs):
            m = next(x for x in it["menu"] if x["id"] == c["scene"])
            texts[c["day"]] = next(b["text"] for b in c["blocks"] if b["label"] == "오늘")
            scene[c["day"]] = {"id": m["id"], "name": m["name"], "words": m["words"], "cat": it["category"], "link": c["link"],
                               "ref": it["ref"]}
    return texts, scene


def base_texts():
    import dupcheck
    import planio
    plan = planio.read_plan(S / "plan_all" / "data" / "plan.json")
    return {d: t for d, _l, t in dupcheck.blocks_of(plan, "오늘")}


def cmd_collide(d):
    texts = base_texts()
    new_texts, scene = load_new(d)
    texts.update(new_texts)
    pairs = []
    for b, s in sorted(scene.items()):
        for w in s["words"]:
            for day, t in texts.items():
                if day != b and w in t:
                    pairs.append((b, w, day))
    write(d / "collisions.json", pairs)
    print(len(pairs), "쌍")
    for b, w, day in pairs:
        s = scene[b]
        hit = [x for x in sents(texts[day]) if w in x]
        kind = "새날" if day in scene else "앞선 해"
        print(f"[{b}] {s['cat']} · {s['name']} · 필수어 {s['words']}")
        print(f"   '{w}' 를 쓴 {day}일({kind}, {scene.get(day, {}).get('name', '앞선 해')[:30]}): {hit[0][:110]}")


def cmd_propose(d):
    import make_lv
    texts = base_texts()
    new_texts, scene = load_new(d)
    texts.update(new_texts)
    led = read(S / "ledger_all.json")["scenes"]
    allwords = {str(k): v["words"] for k, v in led.items()}
    allwords.update({str(k): v["words"] for k, v in scene.items()})
    tok, _many = make_lv.kiwi_tokenizer()
    pairs = read(d / "collisions.json")
    for b in sorted({p[0] for p in pairs}):
        t = texts[b]
        first = " ".join(sents(t)[:2])
        cand = []
        for form, tag, _st, _ln in tok(t):
            if tag not in ("NNG", "NNP") or len(form) < 2 or not re.fullmatch(r"[가-힣]+", form) or form in cand:
                continue
            if any(form in tt for day, tt in texts.items() if day != b):
                continue
            if any((form in w or w in form) for k, ws in allwords.items() if k != str(b) for w in ws):
                continue
            cand.append(form)
        bad = sorted({w for bb, w, _x in pairs if bb == b})
        print(f"{b}: 현재 {scene[b]['words']} 겹침 {bad} 후보 " + ", ".join(f"{c}{'*' if c in first else ''}" for c in cand))


def cmd_wordok(d, words):
    texts = base_texts()
    new_texts, scene = load_new(d)
    texts.update(new_texts)
    led = read(S / "ledger_all.json")["scenes"]
    allw = {int(k): v["words"] for k, v in led.items()}
    allw.update({k: v["words"] for k, v in scene.items()})
    for w in words:
        hits = [k for k, t in texts.items() if w in t]
        wh = [k for k, ws in allw.items() if any(w in x or x in w for x in ws)]
        print(f"{w}: 글 {hits[:6]} 필수어 {wh[:6]}")


def cmd_show(d, days):
    want = {int(x) for x in days}
    for ip in chunks(d):
        its, cs = read(ip), read(d / ip.name.replace("items_", "commentary_"))
        for it, c in zip(its, cs):
            if c["day"] in want:
                m = next(x for x in it["menu"] if x["id"] == c["scene"])
                print(f"== {c['day']} {it['ref']} · {it['category']} · 장면 {m['name']} {m['words']}")
                print("   link:", c["link"])
                print("   오늘:", c["blocks"][-1]["text"])


def cmd_apply(d, patch_path):
    patch = read(patch_path)
    done = {"text": 0, "link": 0, "name": 0, "words": 0}
    miss = []
    for ip in chunks(d):
        cp = d / ip.name.replace("items_", "commentary_")
        items, comments = read(ip), read(cp)
        for it, c in zip(items, comments):
            day = str(c["day"])
            entry = next((m for m in it.get("menu", []) if m["id"] == c.get("scene")), None)
            for old, new in patch.get("text", {}).get(day, []):
                t = c["blocks"][-1]["text"]
                if t.count(old) != 1:
                    miss.append(f"{day}: 본문에서 '{old}' 가 {t.count(old)}번")
                    continue
                c["blocks"][-1]["text"] = t.replace(old, new)
                done["text"] += 1
            for old, new in patch.get("link", {}).get(day, []):
                if old not in c["link"]:
                    miss.append(f"{day}: link 에 '{old}' 가 없습니다")
                    continue
                c["link"] = c["link"].replace(old, new)
                done["link"] += 1
            if day in patch.get("name", {}) and entry:
                entry["name"] = patch["name"][day]
                done["name"] += 1
            if day in patch.get("words", {}) and entry:
                entry["words"] = patch["words"][day]
                done["words"] += 1
        write(ip, items)
        write(cp, comments)
    print(done)
    for m in miss:
        print("문제:", m)


def cmd_rewrite(d, patch_path):
    pool = {x["id"]: x for x in read(REPO / "waves" / "pool.json")}
    patch = read(patch_path)
    seen = set()
    for ip in chunks(d):
        cp = d / ip.name.replace("items_", "commentary_")
        items, comments = read(ip), read(cp)
        for it, c in zip(items, comments):
            day = str(c["day"])
            if day not in patch:
                continue
            p = patch[day]
            sid = p["scene"]
            menu = it["menu"]
            if not any(m["id"] == sid for m in menu):
                if sid not in pool:
                    print(f"{day}: 장면 {sid} 가 풀에 없습니다")
                    continue
                if pool[sid]["category"] != it["category"]:
                    print(f"{day}: 장면 {sid} 의 범주 {pool[sid]['category']} 가 {it['category']} 와 다릅니다")
                    continue
                slot = next(i for i, m in enumerate(menu) if m["id"] == c["scene"])
                menu[slot] = {"id": sid, "name": pool[sid]["name"], "words": list(pool[sid]["words"]),
                              **({"theme": pool[sid]["theme"]} if pool[sid].get("theme") else {})}
            if p.get("words"):
                next(m for m in menu if m["id"] == sid)["words"] = p["words"]
            c["scene"] = sid
            c["link"] = p["link"]
            c["blocks"][-1]["text"] = p["text"]
            seen.add(day)
        write(ip, items)
        write(cp, comments)
    print("적용", len(seen), "일", sorted(set(patch) - seen) or "")


if __name__ == "__main__":
    cmd, d, rest = sys.argv[1], S / sys.argv[2], sys.argv[3:]
    {"collide": lambda: cmd_collide(d), "propose": lambda: cmd_propose(d), "wordok": lambda: cmd_wordok(d, rest),
     "show": lambda: cmd_show(d, rest), "apply": lambda: cmd_apply(d, rest[0]), "rewrite": lambda: cmd_rewrite(d, rest[0])}[cmd]()
