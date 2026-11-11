#!/usr/bin/env python3
"""Keeps only the adhan itself in every recording: from the first «الله أكبر» to the last «لا إله إلا الله».

Any talk before or after (credits, recording names, du'a, announcements) is cut away, and the cuts fall in
pauses only. The cut is then listened to again: it must start with «الله أكبر» and end with
«لا إله إلا الله», with nothing after. A recording that can't be cleaned this way is dropped from the library.

  clean_library.py N PARTS   -> clean-part-N.json   (trim_start / trim_end, or drop + reason)
  clean_library.py merge     -> sources.json updated (the build applies the trims and skips dropped ones)
"""
import glob, json, os, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(__file__))
from make_alerts import norm, same, transcribe   # noqa: E402
from audio_cut import pauses, pause_before, pause_after, duration   # noqa: E402

OPEN = ["الله", "اكبر"]
CLOSE = ["لا", "اله", "الا", "الله"]


def seq_at(words, i, phrase):
    return i + len(phrase) <= len(words) and all(same(words[i + k][0], norm(phrase[k])) for k in range(len(phrase)))


def analyse(model, path):
    words = transcribe(model, path)
    if len(words) < 12:
        return None, "too few words heard"
    first = next((i for i in range(len(words)) if seq_at(words, i, OPEN)), None)
    last = max((i for i in range(len(words)) if seq_at(words, i, CLOSE)), default=None)
    if first is None or last is None or last <= first:
        return None, "opening «الله أكبر» or closing «لا إله إلا الله» not heard"
    ps = pauses(path)
    t0 = words[first][1]
    t1 = words[last + len(CLOSE) - 1][2]
    start = pause_before(ps, t0)
    end = pause_after(ps, t1)
    if start is None:
        start = max(0.0, t0 - 0.6) if t0 < 1.5 else None
    if end is None:
        end = t1 + 1.2 if t1 + 1.2 >= duration(path) - 0.2 else None
    if start is None or end is None:
        return None, "no pause around the adhan to cut in"
    return (max(0.0, start), end), "ok"


def verify(model, path, start, end):
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "c.mp3")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "%.2f" % start, "-to", "%.2f" % end, "-i", path,
                        "-c:a", "libmp3lame", "-b:a", "96k", out], check=True)
        w = transcribe(model, out)
    if len(w) < 12:
        return "after cutting, too few words heard"
    if not seq_at(w, 0, OPEN):
        return "after cutting, it does not start with «الله أكبر» (heard: %s)" % " ".join(x[0] for x in w[:4])
    if not seq_at(w, len(w) - len(CLOSE), CLOSE):
        return "after cutting, it does not end with «لا إله إلا الله» (heard: %s)" % " ".join(x[0] for x in w[-6:])
    return None


def main(part, parts):
    from faster_whisper import WhisperModel
    model = WhisperModel(os.environ.get("WHISPER", "small"), device="cpu", compute_type="int8")
    src = json.load(open("sources.json", encoding="utf-8"))
    res = []
    todo = [a for a in src["adhans"] if not a.get("drop")]
    for n, a in enumerate(todo):
        if n % parts != part:
            continue
        path = os.path.join("audio", a["id"] + ".mp3")
        if not os.path.exists(path):
            continue
        cut, why = analyse(model, path)
        if cut:
            bad = verify(model, path, *cut)
            if bad:
                cut, why = None, bad
        base = a.get("trim_start", 0.0)   # audio/ already starts at trim_start of the source
        r = {"id": a["id"], "ok": bool(cut), "why": why}
        if cut:
            r["trim_start"] = round(base + cut[0], 2)
            r["trim_end"] = round(base + cut[1], 2)
            r["cut_front"] = round(cut[0], 1)
            r["cut_back"] = round(duration(path) - cut[1], 1)
        res.append(r)
        print(r, flush=True)
    json.dump(res, open("clean-part-%d.json" % part, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def merge():
    res = {}
    for f in glob.glob("clean-part-*.json"):
        for r in json.load(open(f, encoding="utf-8")):
            res[r["id"]] = r
    src = json.load(open("sources.json", encoding="utf-8"))
    lines = []
    for a in src["adhans"]:
        r = res.get(a["id"])
        if not r:
            continue
        if r["ok"]:
            a["trim_start"], a["trim_end"] = r["trim_start"], r["trim_end"]
            a.pop("drop", None)
            lines.append("kept    %-22s cut %4.1f s before, %4.1f s after" % (a["id"], r["cut_front"], r["cut_back"]))
        else:
            a["drop"] = True
            a["drop_reason"] = r["why"]
            lines.append("DROPPED %-22s %s" % (a["id"], r["why"]))
    json.dump(src, open("sources.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    open("clean-report.txt", "w", encoding="utf-8").write("\n".join(sorted(lines)) + "\n")
    print("\n".join(sorted(lines)))


if __name__ == "__main__":
    if sys.argv[1] == "merge":
        merge()
    else:
        main(int(sys.argv[1]), int(sys.argv[2]))
