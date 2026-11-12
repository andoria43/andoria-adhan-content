#!/usr/bin/env python3
"""Builds the Mushaf data package for the app (published as release assets "mushaf-v1").

Outputs in out/:
  meta.txt        s|a|page|juz|hizbQuarter|sajda     (6236 lines)
  muyassar.txt    s|a|tafsir text (Al-Muyassar, King Fahd Complex)
  saddi.txt       s|a|tafsir text (Al-Sa'di)
  en.txt          s|a|English meaning (Saheeh International)
  words.txt       s|a|position|word|english|arabic gloss (gloss only where the short tafsir explains that word)
Then the page images and ayah boxes are mirrored from android.quran.com.
"""
import json, re, sys, time, html, os, urllib.request

OUT = "out"
os.makedirs(OUT, exist_ok=True)

def get(url, tries=6):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "andoria-adhan-data/1.0"})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            print("retry", url, e, file=sys.stderr)
            time.sleep(3 + i * 4)
    raise SystemExit("failed " + url)

def clean(t):
    t = re.sub(r"<sup[^>]*>.*?</sup>", "", t or "")
    t = re.sub(r"<br\s*/?>", "\n", t)
    t = re.sub(r"</p>\s*<p[^>]*>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t).strip()
    return t.replace("|", "/").replace("\r", "")

def one_line(t):
    return clean(t).replace("\n", "\\n")

# 1) meta + Al-Muyassar + English from alquran.cloud (whole editions)
uth = get("https://api.alquran.cloud/v1/quran/quran-uthmani")["data"]["surahs"]
with open(f"{OUT}/meta.txt", "w", encoding="utf-8") as f:
    for s in uth:
        for a in s["ayahs"]:
            sj = a.get("sajda")
            sj = 1 if (sj is True or isinstance(sj, dict)) else 0
            f.write(f'{s["number"]}|{a["numberInSurah"]}|{a["page"]}|{a["juz"]}|{a["hizbQuarter"]}|{sj}\n')

for ed, name in (("ar.muyassar", "muyassar"), ("en.sahih", "en")):
    d = get(f"https://api.alquran.cloud/v1/quran/{ed}")["data"]["surahs"]
    with open(f"{OUT}/{name}.txt", "w", encoding="utf-8") as f:
        for s in d:
            for a in s["ayahs"]:
                f.write(f'{s["number"]}|{a["numberInSurah"]}|{one_line(a["text"])}\n')

# 2) Al-Sa'di (91) and the short tafsir with word glosses (16) from quran.com, chapter by chapter
def tafsir(rid, ch):
    out = {}
    d = get(f"https://api.quran.com/api/v4/tafsirs/{rid}/by_chapter/{ch}?per_page=300")
    for t in d["tafsirs"]:
        out[t["verse_key"]] = t["text"]
    return out

glosses = {}
with open(f"{OUT}/saddi.txt", "w", encoding="utf-8") as f:
    for ch in range(1, 115):
        sd = tafsir(91, ch)
        short = tafsir(16, ch)
        for key in sorted(sd, key=lambda k: int(k.split(":")[1])):
            s, a = key.split(":")
            f.write(f"{s}|{a}|{one_line(sd[key])}\n")
        for key, txt in short.items():
            # "<span class="green">(word)</span> meaning ..." up to the next span
            parts = re.split(r'<span class="green">\s*\(?(.*?)\)?\s*</span>', txt)
            g = []
            for i in range(1, len(parts) - 1, 2):
                w = clean(parts[i]).strip("() ")
                m = clean(parts[i + 1]).strip(" ،,:-")
                if w and m:
                    g.append((w, m[:300]))
            glosses[key] = g
        print("tafsir chapter", ch, flush=True)

# 3) words of every ayah (position as on the page), English meaning, Arabic gloss where available
AR_STRIP = re.compile(r"[ً-ٰٟۖ-ۭـٱاأإآ]")
def plain(w):
    w = AR_STRIP.sub("", w)
    return w.replace("ى", "ي").replace("ة", "ه").replace("ؤ", "و").replace("ئ", "ي")

with open(f"{OUT}/words.txt", "w", encoding="utf-8") as f:
    for ch in range(1, 115):
        page = 1
        while True:
            d = get(f"https://api.quran.com/api/v4/verses/by_chapter/{ch}?words=true&word_fields=text_uthmani&per_page=50&page={page}")
            for v in d["verses"]:
                s, a = v["verse_key"].split(":")
                g = glosses.get(v["verse_key"], [])
                for w in v["words"]:
                    if w.get("char_type_name") != "word":
                        continue
                    txt = w["text_uthmani"]
                    en = (w.get("translation") or {}).get("text") or ""
                    ar = ""
                    pw = plain(txt)
                    for gw, gm in g:
                        pg = plain(gw)
                        if pg and (pg == pw or (len(pg) > 2 and (pg in pw or pw in pg))):
                            ar = gm
                            break
                    f.write(f'{s}|{a}|{w["position"]}|{txt}|{en.replace("|","/")}|{ar.replace("|","/")}\n')
            nxt = d.get("pagination", {}).get("next_page")
            if not nxt:
                break
            page = nxt
        print("words chapter", ch, flush=True)

for n in ("meta", "muyassar", "saddi", "en", "words"):
    print(n, sum(1 for _ in open(f"{OUT}/{n}.txt", encoding="utf-8")))
