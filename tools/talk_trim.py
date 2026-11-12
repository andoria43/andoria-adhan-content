#!/usr/bin/env python3
"""Removes talk said before or after the adhan (credits, a du'a, a speech), carefully.

The recording is split at its real silences. Starting from the end, the last piece is transcribed on
its own (short pieces are heard much better than a whole adhan). It is removed only when it is clearly
speech that is NOT the adhan: at least 4 words, most of them not adhan words. Then the piece before it
is checked, and so on. The same from the start (before the first «الله اكبر»). A piece that is quiet,
unclear or has adhan words is always kept, so the adhan itself is never cut.

usage: talk_trim.py <part> <parts>   |   talk_trim.py merge
"""
import difflib, glob, json, os, shutil, subprocess, sys

sys.path.insert(0, os.path.dirname(__file__))
from make_alerts import norm, transcribe   # noqa: E402
from audio_cut import envelope, duration   # noqa: E402

VOCAB = [norm(w) for w in "الله اكبر اشهد ان لا اله الا محمدا محمد رسول حي على الصلاة الفلاح خير من النوم قد قامت".split()]


def adhan_word(w):
    return any(difflib.SequenceMatcher(None, w, v).ratio() >= 0.6 for v in VOCAB)


def is_talk(words):
    ws = [w[0] for w in words]
    if len(ws) < 4:
        return False
    other = sum(1 for w in ws if not adhan_word(w))
    return other >= 4 and other >= 0.6 * len(ws)


def gaps(path, min_len=0.7, below=30.0):
    import numpy as np
    db, hop = envelope(path)
    thr = float(np.percentile(db, 98)) - below
    out, run = [], 0
    for i, v in enumerate(db):
        if v < thr:
            run += 1
        else:
            if run * hop >= min_len:
                out.append(((i - run) * hop, i * hop))
            run = 0
    return out


def cut(src, s, e, out):
    fi = "afade=t=in:d=0.05," if s > 0 else ""
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "%.2f" % s, "-t", "%.2f" % (e - s), "-i", src,
                    "-af", fi + "afade=t=out:st=%.2f:d=0.5" % max(0.0, e - s - 0.5),
                    "-c:a", "libmp3lame", "-b:a", "128k", out], check=True)


def piece_words(model, src, a, b, tmp):
    cut(src, a, b, tmp)
    return transcribe(model, tmp)


def trim_one(model, sid, src, report):
    total = duration(src)
    g = gaps(src)
    tmp = "/tmp/piece_%s.mp3" % sid
    end, removed_tail = total, []
    # from the end
    tail_gaps = [x for x in g if x[0] > total * 0.5]
    for gs, ge in reversed(tail_gaps):
        if ge >= end - 0.5:
            continue
        w = piece_words(model, src, ge, end, tmp)
        if is_talk(w):
            removed_tail.append(" ".join(x[0] for x in w))
            end = gs + 0.3
        else:
            break
    start, removed_head = 0.0, []
    head_gaps = [x for x in g if x[1] < total * 0.3]
    for gs, ge in head_gaps:
        if gs <= start + 0.5:
            continue
        w = piece_words(model, src, start, gs, tmp)
        if is_talk(w):
            removed_head.append(" ".join(x[0] for x in w))
            start = max(0.0, ge - 0.2)
        else:
            break
    if not removed_tail and not removed_head:
        report.append("%s: clean (%.0f s)" % (sid, total))
        return None
    if end - start < 90:
        report.append("%s: NOT TRIMMED, too little would be left (%.1f-%.1f)" % (sid, start, end))
        return None
    os.makedirs("trimmed", exist_ok=True)
    cut(src, start, end, os.path.join("trimmed", sid + ".mp3"))
    report.append("%s: trimmed to %.1f-%.1f of %.0f s | removed before: %s | removed after: %s"
                  % (sid, start, end, total, " / ".join(removed_head), " / ".join(reversed(removed_tail))))
    return round(end - start)


def main(part, parts):
    from faster_whisper import WhisperModel
    model = WhisperModel(os.environ.get("WHISPER", "small"), device="cpu", compute_type="int8")
    cat = json.load(open("adhans.json", encoding="utf-8"))
    full = [a for a in cat["adhans"] if a.get("type") != "alert"]
    report, res = [], {}
    for n, a in enumerate(full):
        if n % parts != part:
            continue
        src = os.path.join("audio", a["id"] + ".mp3")
        if not os.path.exists(src):
            continue
        r = trim_one(model, a["id"], src, report)
        if r is not None:
            res[a["id"]] = r
        print(report[-1], flush=True)
    json.dump({"res": res, "report": report}, open("trim-part-%d.json" % part, "w", encoding="utf-8"), ensure_ascii=False)


def merge():
    parts = glob.glob("trim-part-*.json")
    if not parts:
        print("no parts")
        return
    cat = json.load(open("adhans.json", encoding="utf-8"))
    res, report = {}, []
    for f in sorted(parts):
        d = json.load(open(f, encoding="utf-8"))
        res.update(d["res"])
        report += d["report"]
    for a in cat["adhans"]:
        r = res.get(a["id"])
        t = os.path.join("trimmed", a["id"] + ".mp3")
        if isinstance(r, int) and os.path.exists(t):
            shutil.copy(t, os.path.join("audio", a["id"] + ".mp3"))
            a["seconds"] = r
            a["note_ar"] = a["note_en"] = "%d:%02d" % (r // 60, r % 60)
    json.dump(cat, open("adhans.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    report.sort()
    open("trim-report.txt", "w", encoding="utf-8").write("\n".join(report) + "\n")
    print("\n".join(report))


if __name__ == "__main__":
    if sys.argv[1] == "merge":
        merge()
    else:
        main(int(sys.argv[1]), int(sys.argv[2]))
