#!/usr/bin/env python3
"""Word times of the last minute of some adhans (to see where the adhan really ends)."""
import os, subprocess, sys
from faster_whisper import WhisperModel
sys.path.insert(0, os.path.dirname(__file__))
from make_alerts import load_audio
m = WhisperModel("small", device="cpu", compute_type="int8")
out = []
for id_ in sys.argv[1:]:
    p = "audio/%s.mp3" % id_
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p], capture_output=True, text=True).stdout)
    st = max(0, dur - 70)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(st), "-i", p, "-ar", "16000", "-ac", "1", "/tmp/x.wav"], check=True)
    segs, _ = m.transcribe(load_audio("/tmp/x.wav"), language="ar", word_timestamps=True, vad_filter=False)
    out.append("== %s (from %.1f of %.1f)" % (id_, st, dur))
    for s in segs:
        for w in s.words or []:
            out.append("%.1f-%.1f %s" % (st + w.start, st + w.end, w.word))
open("probe-words.txt", "w", encoding="utf-8").write("\n".join(out) + "\n")
