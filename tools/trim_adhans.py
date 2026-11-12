#!/usr/bin/env python3
"""Removes anything said before or after the adhan itself (credits such as «قدم لكم عن طريق...»,
a du'a or a talk), so every full adhan starts with its first «الله أكبر» and ends with its last
«لا إله إلا الله».

Each recording is transcribed with word times. The adhan's start is the first «الله اكبر»; its end is
the last «لا اله الا الله» that comes right after «الله اكبر الله اكبر». The cut is made where the voice has
really stopped (energy valley), with short fades. The trimmed file is transcribed again: it is kept
only when it still starts with «الله اكبر» and ends with «لا اله الا الله» and has nothing after it;
otherwise the recording is listed as DROPPED (it still has talk we can't remove cleanly).

usage: trim_adhans.py <part> <parts>   |   trim_adhans.py merge
"""
import glob, json, os, shutil, subprocess, sys

sys.path.insert(0, os.path.dirname(__file__))
from make_alerts import norm, same, transcribe   # noqa: E402
from audio_cut import envelope, valley, voice_end, duration   # noqa: E402

TAIL = ["لا", "اله", "الا", "الله"]


def is_(w, word):
    return same(w, norm(word))


def find_bounds(words):
    """(start time, end time, extra words before, extra words after) or None."""
    first = None
    for i in range(len(words) - 1):
        if is_(words[i][0], "الله") and is_(words[i + 1][0], "اكبر"):
            first = i
            break
    last = None
    for i in range(len(words) - 4, -1, -1):
        if all(is_(words[i + k][0], TAIL[k]) for k in range(4)):
            # the closing one: «الله اكبر الله اكبر» just before
            if i >= 4 and is_(words[i - 4][0], "الله") and is_(words[i - 2][0], "الله"):
                last = i
                break
    if first is None or last is None:
        return None
    return first, last + 3


def trim_one(model, sid, src, out_dir, report):
    words = transcribe(model, src)
    b = find_bounds(words)
    total = duration(src)
    if not b:
        report.append("%s: adhan words not found, left as it is (heard: %s)" % (sid, " ".join(w[0] for w in words[-12:])))
        return None
    i0, i1 = b
    before, after = words[:i0], words[i1 + 1:]
    env = envelope(src)
    start, end = words[i0][1], words[i1][2]
    prev_end = before[-1][2] if before else 0.0
    next_start = after[0][1] if after else total
    s = 0.0 if not before else valley(env, max(prev_end, start - 6.0), start - 0.02)[0]
    e = voice_end(env, end, min(next_start - 0.05, end + 12.0))
    e = min(e + 0.3, next_start - 0.05, total)
    cut_head, cut_tail = s > 0.6, total - e > 1.5
    if not (cut_head or cut_tail) or (not before and not after and total - e < 4.0):
        report.append("%s: clean (%.0f s)" % (sid, total))
        return None
    out = os.path.join(out_dir, sid + ".mp3")
    fade = "afade=t=in:d=0.05," if cut_head else ""
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "%.2f" % s, "-t", "%.2f" % (e - s), "-i", src,
                    "-af", fade + "afade=t=out:st=%.2f:d=0.6" % max(0.0, e - s - 0.6),
                    "-c:a", "libmp3lame", "-b:a", "128k", out], check=True)
    check = transcribe(model, out)
    heard = [w[0] for w in check]
    # words left before the first «الله اكبر» or after the last «لا اله الا الله» = talk still there
    first = next((i for i in range(len(heard) - 1) if is_(heard[i], "الله") and is_(heard[i + 1], "اكبر")), 0)
    last = next((i + 3 for i in range(len(heard) - 4, -1, -1) if all(is_(heard[i + k], TAIL[k]) for k in range(4))), len(heard) - 1)
    extra = first + (len(heard) - 1 - last)
    if extra >= 2:
        report.append("%s: DROPPED, still not clean after trimming (start: %s ... end: %s)"
                      % (sid, " ".join(heard[:4]), " ".join(heard[-6:])))
        os.remove(out)
        return "drop"
    report.append("%s: trimmed %.1f-%.1f of %.0f s (removed before: %s | after: %s)"
                  % (sid, s, e, total, " ".join(w[0] for w in before[-10:]), " ".join(w[0] for w in after[:12])))
    return round(e - s)


def main(part, parts):
    from faster_whisper import WhisperModel
    model = WhisperModel(os.environ.get("WHISPER", "small"), device="cpu", compute_type="int8")
    cat = json.load(open("adhans.json", encoding="utf-8"))
    full = [a for a in cat["adhans"] if a.get("type") != "alert"]
    os.makedirs("trimmed", exist_ok=True)
    report, res = [], {}
    for n, a in enumerate(full):
        if n % parts != part:
            continue
        src = os.path.join("audio", a["id"] + ".mp3")
        if not os.path.exists(src):
            continue
        r = trim_one(model, a["id"], src, "trimmed", report)
        if r is not None:
            res[a["id"]] = r
        print(report[-1], flush=True)
    json.dump({"res": res, "report": report}, open("trim-part-%d.json" % part, "w", encoding="utf-8"), ensure_ascii=False)


def merge():
    parts = glob.glob("trim-part-*.json")
    if not parts:
        print("no parts, nothing changed")
        return
    cat = json.load(open("adhans.json", encoding="utf-8"))
    res, report = {}, []
    for f in sorted(parts):
        d = json.load(open(f, encoding="utf-8"))
        res.update(d["res"])
        report += d["report"]
    keep = []
    for a in cat["adhans"]:
        r = res.get(a["id"])
        if r == "drop":
            continue
        if isinstance(r, int):
            t = os.path.join("trimmed", a["id"] + ".mp3")
            if os.path.exists(t):
                shutil.copy(t, os.path.join("audio", a["id"] + ".mp3"))
                a["seconds"] = r
                a["note_ar"] = a["note_en"] = "%d:%02d" % (r // 60, r % 60)
        keep.append(a)
    for a in cat["adhans"]:
        if res.get(a["id"]) == "drop":
            p = os.path.join("audio", a["id"] + ".mp3")
            if os.path.exists(p):
                os.remove(p)
    cat["adhans"] = keep
    json.dump(cat, open("adhans.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    report.sort()
    open("trim-report.txt", "w", encoding="utf-8").write("\n".join(report) + "\n")
    print("\n".join(report))


if __name__ == "__main__":
    if sys.argv[1] == "merge":
        merge()
    else:
        main(int(sys.argv[1]), int(sys.argv[2]))
