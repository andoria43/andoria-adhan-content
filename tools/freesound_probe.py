#!/usr/bin/env python3
"""Finds adhans on Freesound with a free licence (CC BY or CC0), checks each one's licence from its own page,
downloads the public MP3 preview, and writes what is heard plus how noisy it is."""
import json, os, re, subprocess, sys, time, urllib.parse, urllib.request
sys.path.insert(0, os.path.dirname(__file__))
from make_alerts import load_audio   # noqa: E402
import numpy as np
from faster_whisper import WhisperModel

UA = {"User-Agent": "Mozilla/5.0 (AndoriaAdhanLibraryCheck; https://github.com/andoria43/andoria-adhan-content)"}
GIVEN = [807484, 832525, 830349, 146743, 62020, 277335, 161728, 705292, 19029, 28775, 255761, 262229]
QUERIES = ["adhan", "azan", "ezan", "call to prayer", "muezzin", "athan", "adhan fajr"]
LIC = '(license:"Attribution" OR license:"Creative Commons 0")'

def get(url):
    for i in range(4):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read().decode("utf-8", "replace")
        except Exception as e:
            print("retry", url, e, flush=True); time.sleep(5 * (i + 1))
    return ""

ids = list(GIVEN)
for q in QUERIES:
    for page in (1, 2, 3):
        url = "https://freesound.org/search/?" + urllib.parse.urlencode({"q": q, "f": LIC, "page": page})
        html = get(url)
        found = [int(x) for x in re.findall(r'/people/[^/"]+/sounds/(\d+)/', html)]
        for x in found:
            if x not in ids: ids.append(x)
        time.sleep(1)
        if not found: break
print(len(ids), "sounds to check", flush=True)

m = WhisperModel("small", device="cpu", compute_type="int8")
os.makedirs("freesound_raw", exist_ok=True)
report = []
for sid in ids[:90]:
    html = get("https://freesound.org/s/%d/" % sid)
    time.sleep(1)
    if not html: report.append({"id": sid, "error": "page"}); continue
    title = (re.search(r'<meta property="og:title" content="([^"]*)"', html) or re.search(r"<title>([^<]*)", html)).group(1)
    page = (re.search(r'<meta property="og:url" content="([^"]*)"', html) or [None, "https://freesound.org/s/%d/" % sid])[1]
    author = (re.search(r'/people/([^/"]+)/sounds/%d' % sid, html) or [None, "?"])[1]
    lic = re.search(r'(Attribution NonCommercial[^<\n]*|Attribution[^<\n]{0,8}\d\.\d|Attribution|Creative Commons 0|Sampling\+)', html)
    lic = lic.group(1).strip() if lic else "?"
    dur = re.search(r'Duration</dt>\s*<dd[^>]*>\s*([\d:.]+)', html) or re.search(r'>(\d+:\d\d\.\d+)<', html)
    prev = re.search(r'https://cdn\.freesound\.org/previews/[^"\']+?-hq\.mp3', html)
    row = {"id": sid, "title": title, "author": author, "license": lic, "duration": dur.group(1) if dur else "?",
           "page": page}
    free = lic.startswith("Attribution") and "NonCommercial" not in lic or lic == "Creative Commons 0"
    row["free"] = free
    if free and prev:
        dst = "freesound_raw/fs_%d.mp3" % sid
        try:
            open("/tmp/p.mp3", "wb").write(urllib.request.urlopen(urllib.request.Request(prev.group(0), headers=UA), timeout=120).read())
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", "/tmp/p.mp3", "-ac", "1", "-ar", "44100",
                            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "libmp3lame", "-b:a", "128k", dst], check=True)
            y = load_audio(dst)
            fr = y[: len(y) // 2205 * 2205].reshape(-1, 2205)
            db = 20 * np.log10(np.sqrt((fr ** 2).mean(1)) + 1e-9)
            row["range_db"] = round(float(np.percentile(db, 95) - np.percentile(db, 10)), 1)  # small = constant noise
            segs, _ = m.transcribe(y, language="ar", word_timestamps=True, vad_filter=False)
            words = [(round(w.start, 1), round(w.end, 1), w.word.strip()) for s in segs for w in (s.words or [])]
            row["text"] = " ".join(w[2] for w in words)
            row["words"] = words
        except Exception as e:
            row["error"] = str(e)
    elif free:
        row["error"] = "no preview"
    report.append(row)
    print(sid, lic, row.get("range_db"), (row.get("text") or "")[:80], flush=True)
json.dump(report, open("freesound-report.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
