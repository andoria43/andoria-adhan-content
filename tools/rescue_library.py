#!/usr/bin/env python3
"""Second, closer look at the adhans that were dropped: the original recording is downloaded again and
listened to with the large speech model (more exact in Arabic), then cut and checked exactly like
clean_library.py. A recording comes back into the library only when the check passes.

  rescue_library.py N PARTS  -> clean-part-N.json   (same format; the merge of clean_library.py applies it)
"""
import json, os, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(__file__))
from clean_library import analyse, verify          # noqa: E402
from audio_cut import duration                     # noqa: E402
from build_library import source_input             # noqa: E402


def main(part, parts):
    from faster_whisper import WhisperModel
    model = WhisperModel(os.environ.get("WHISPER", "large-v3"), device="cpu", compute_type="int8")
    src = json.load(open("sources.json", encoding="utf-8"))
    todo = [a for a in src["adhans"] if a.get("drop")]
    res = []
    tmp = tempfile.mkdtemp()
    for n, a in enumerate(todo):
        if n % parts != part:
            continue
        r = {"id": a["id"], "ok": False, "why": "could not download"}
        try:
            raw = source_input(a, tmp)
            path = os.path.join(tmp, a["id"] + "_full.mp3")
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", raw, "-vn", "-ac", "1", "-ar", "44100",
                            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "libmp3lame", "-b:a", "128k", path], check=True)
            cut, why = analyse(model, path)
            if cut:
                bad = verify(model, path, *cut)
                if bad:
                    cut, why = None, bad
            r = {"id": a["id"], "ok": bool(cut), "why": (why if cut else why + " (large model)")}
            if cut:
                r["trim_start"] = round(cut[0], 2)
                r["trim_end"] = round(cut[1], 2)
                r["cut_front"] = round(cut[0], 1)
                r["cut_back"] = round(duration(path) - cut[1], 1)
        except Exception as e:
            r["why"] = "error: %s" % e
        res.append(r)
        print(r, flush=True)
    json.dump(res, open("clean-part-%d.json" % part, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(int(sys.argv[1]), int(sys.argv[2]))
