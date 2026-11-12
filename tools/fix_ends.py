#!/usr/bin/env python3
"""Gives back the end of every adhan that the cleaning cut too early (the last «الله» cut in the middle).

For each adhan the recording before cleaning is taken from the history, the cleaned adhan is found inside
it (same start), and the end is moved to where the voice really stops: the first stretch of real quiet
after the old end (at most 8 s later), plus a short tail for the echo. The cut is made again from the
recording before cleaning, at the same loudness as the cleaned one.

usage: fix_ends.py <commit before cleaning> [id ...]
"""
import json, os, subprocess, sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from audio_cut import envelope, duration   # noqa: E402


def norm(db):
    return db - np.median(db)


def locate(cur, orig, hop):
    a = norm(cur[:int(20 / hop)])
    b = orig
    best, bk = 1e9, 0
    for k in range(0, max(1, len(b) - len(a))):
        seg = b[k:k + len(a)]
        if len(seg) < len(a):
            break
        d = float(np.mean(np.abs(norm(seg) - a)))
        if d < best:
            best, bk = d, k
    return bk * hop, best


def fix(id_, before, report):
    cur_p = "audio/%s.mp3" % id_
    orig_p = "/tmp/orig/%s.mp3" % id_
    os.makedirs("/tmp/orig", exist_ok=True)
    r = subprocess.run(["git", "show", "%s:audio/%s.mp3" % (before, id_)], capture_output=True)
    if r.returncode != 0 or not r.stdout:
        report.append("%s: no recording before cleaning, left as it is" % id_)
        return None
    open(orig_p, "wb").write(r.stdout)
    c, hop = envelope(cur_p)
    o, _ = envelope(orig_p)
    off, err = locate(c, o, hop)
    end_old = off + len(c) * hop
    if err > 4:
        report.append("%s: could not find it inside the recording (%.1f), left as it is" % (id_, err))
        return None
    pk = float(np.percentile(o, 98))
    thr, need = pk - 28, int(0.3 / hop)
    i, stop, run, quiet = int((end_old - 1.2) / hop), min(len(o), int((end_old + 8) / hop)), 0, None
    while i < stop:
        run = run + 1 if o[i] < thr else 0
        if run >= need:
            quiet = (i - need + 1) * hop
            break
        i += 1
    if quiet is None:
        report.append("%s: the voice doesn't stop within 8 s after the end, left as it is" % id_)
        return None
    new_end = min(duration(orig_p), quiet + 0.35)
    if new_end <= end_old + 0.15:
        report.append("%s: end already complete" % id_)
        return None
    # same loudness as the cleaned file
    seg = o[int(off / hop):int(off / hop) + len(c)]
    gain = float(np.median(c) - np.median(seg))
    tmp = "/tmp/fix_%s.mp3" % id_
    dur = new_end - off
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "%.3f" % off, "-t", "%.3f" % dur, "-i", orig_p,
                    "-af", "volume=%.2fdB,afade=t=out:st=%.2f:d=0.35" % (gain, max(0, dur - 0.35)),
                    "-c:a", "libmp3lame", "-b:a", "128k", tmp], check=True)
    os.replace(tmp, cur_p)
    report.append("%s: end moved %.1f s later (%.1f -> %.1f s)" % (id_, new_end - end_old, end_old - off, dur))
    return round(dur)


def main():
    before = sys.argv[1]
    cat = json.load(open("adhans.json", encoding="utf-8"))
    only = set(sys.argv[2:])
    report = []
    for a in cat["adhans"]:
        if a.get("type") == "alert" or (only and a["id"] not in only):
            continue
        s = fix(a["id"], before, report)
        print(report[-1], flush=True)
        if s:
            a["seconds"] = s
            a["note_ar"] = a["note_en"] = "%d:%02d" % (s // 60, s % 60)
    json.dump(cat, open("adhans.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open("ends-report.txt", "w", encoding="utf-8").write("\n".join(sorted(report)) + "\n")


if __name__ == "__main__":
    main()
