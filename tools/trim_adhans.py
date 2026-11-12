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
    """(index of the first «الله», index of the «لا» of the closing «لا اله الا الله») or None."""
    first = None
    for i in range(len(words) - 1):
        if is_(words[i][0], "الله") and is_(words[i + 1][0], "اكبر"):
            first = i
            break
    last = None
    span = (words[0][1], words[-1][2]) if words else (0, 0)
    for i in range(len(words) - 4, -1, -1):
        if all(is_(words[i + k][0], TAIL[k]) for k in range(4)):
            # the closing one: comes after «اكبر» (not «اشهد ان»), in the last part of the recording
            near = [words[j][0] for j in range(max(0, i - 3), i)]
            if any(is_(w, "اكبر") for w in near) and not any(is_(w, "اشهد") for w in near) \
                    and words[i][1] > span[0] + 0.6 * (span[1] - span[0]):
                last = i
                break
    if first is None or last is None:
        return None
    return first, last


def first_gap(env, t, limit, below=28.0, min_len=0.35):
    """Start of the first quiet stretch after t (or None)."""
    import numpy as np
    db, hop = env
    thr = float(np.percentile(db, 98)) - below
    i, stop, need, run = int(t / hop), min(len(db), int(limit / hop)), int(min_len / hop), 0
    while i < stop:
        run = run + 1 if db[i] < thr else 0
        if run >= need:
            return (i - need + 1) * hop
        i += 1
    return None


def loud_after(env, t, below=22.0):
    """Seconds of loud sound after time t."""
    import numpy as np
    db, hop = env
    thr = float(np.percentile(db, 98)) - below
    return float((db[int(t / hop):] > thr).sum()) * hop


def trim_one(model, sid, src, out_dir, report):
    words = transcribe(model, src)
    b = find_bounds(words)
    total = duration(src)
    if not b:
        report.append("%s: adhan words not found, left as it is (heard: %s)" % (sid, " ".join(w[0] for w in words[-12:])))
        return None
    i0, la = b
    before = words[:i0]
    env = envelope(src)
    start = words[i0][1]
    # the end: the first real silence once «لا اله الا الله» has begun
    gap = first_gap(env, words[la][1] + 2.5, min(total, words[la][1] + 25.0))
    e = min(total, gap + 0.25) if gap is not None else total
    after = [w for w in words if w[1] > e]
    s = 0.0
    if len(before) >= 3:   # real words before the first «الله اكبر» (not a misheard takbir)
        prev_end = before[-1][2]
        s = valley(env, max(prev_end, start - 6.0), start - 0.02)[0]
    cut_tail = gap is not None and (loud_after(env, e) >= 1.5 or after)
    if not cut_tail:
        e = total
    cut_head = s > 0.6
    if not (cut_head or cut_tail):
        report.append("%s: clean (%.0f s)" % (sid, total))
        return None
    if e - s < 90 or e - s < 0.6 * total:
        report.append("%s: NOT TRIMMED, the cut would leave too little (%.1f-%.1f of %.0f s)" % (sid, s, e, total))
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
