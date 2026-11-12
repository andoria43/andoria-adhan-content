#!/usr/bin/env python3
"""Downloads the freely licensed adhans from Wikimedia Commons, converts them, and writes what is heard
(word times) so each can be checked: a full adhan? anything said before or after? Shia additions?"""
import json, os, subprocess, sys, time, urllib.parse, urllib.request
sys.path.insert(0, os.path.dirname(__file__))
from make_alerts import load_audio   # noqa: E402
from faster_whisper import WhisperModel

FILES = json.load(open("licensed.json", encoding="utf-8"))
UA = {"User-Agent": "AndoriaAdhanLibraryCheck/1.0 (https://github.com/andoria43/andoria-adhan-content)"}
os.makedirs("licensed_raw", exist_ok=True)
m = WhisperModel("small", device="cpu", compute_type="int8")
out = []
for a in FILES:
    url = "https://commons.wikimedia.org/wiki/Special:FilePath/" + urllib.parse.quote(a["file"].replace(" ", "_"))
    src = "/tmp/" + a["id"] + os.path.splitext(a["file"])[1]
    for attempt in range(5):
        try:
            data = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120).read()
            open(src, "wb").write(data)
            break
        except Exception as e:
            time.sleep(15 * (attempt + 1))
    dst = "licensed_raw/%s.mp3" % a["id"]
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src, "-vn", "-ac", "1", "-ar", "44100",
                    "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "libmp3lame", "-b:a", "128k", dst], check=True)
    segs, _ = m.transcribe(load_audio(dst), language="ar", word_timestamps=True, vad_filter=False)
    out.append("== %s (%s)" % (a["id"], a["file"]))
    for s in segs:
        for w in s.words or []:
            out.append("%.1f-%.1f %s" % (w.start, w.end, w.word))
    print(a["id"], "done", flush=True)
open("licensed-words.txt", "w", encoding="utf-8").write("\n".join(out) + "\n")
