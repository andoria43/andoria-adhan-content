#!/usr/bin/env python3
"""Cuts short alert tones out of the adhans already in audio/ and adds them to adhans.json as
{"type": "alert"} entries, so the app can offer them for the alert before the adhan.

Nothing is cut by guesswork: each recording is transcribed (Arabic speech recognition with word times),
the wanted phrase is located, cut with a short fade, and the CUT FILE IS TRANSCRIBED AGAIN. A clip is kept
only when the second transcript contains the phrase too. What was kept or dropped goes to alerts-report.txt.
"""
import difflib, json, os, re, subprocess, sys

RAW = "https://raw.githubusercontent.com/andoria43/andoria-adhan-content/main/audio/"
# recordings to cut from (ids in adhans.json): the best-known voices, so the list stays easy to browse
SOURCES = ["makkah", "madinah", "alafasy", "abdulbasit", "minshawi", "qatami", "zahrani", "khalaf_1", "khalaf_2", "refaat",
           "nuaina", "fatani", "suraihi", "nufais", "saad_ghamdi", "naqshbandi",
           "malek_fajr", "khalaf_fajr", "malmo_fajr", "alafasy3_fajr", "afasy_hejaz_fajr", "taqi_maliki_fajr",
           "islam_sobhi_fajr", "zahrani_fajr", "fatani_fajr", "doha_fajr", "bilal_fajr", "abdulwali_arkani_fajr"]
# phrase kinds: id part, words to find, how many times said in a row, Arabic / English title, only Fajr
KINDS = [
    ("takbir", ["الله", "اكبر"], 2, "تنبيه: الله أكبر الله أكبر", "Alert: Allahu akbar, Allahu akbar", False),
    ("takbir4", ["الله", "اكبر"], 4, "تنبيه: التكبير كاملاً", "Alert: the four takbirs", False),
    ("hayya", ["حي", "على", "الصلاه"], 2, "تنبيه: حيّ على الصلاة", "Alert: Hayya ala-s-salah", False),
    ("falah", ["حي", "على", "الفلاح"], 2, "تنبيه: حيّ على الفلاح", "Alert: Hayya ala-l-falah", False),
    ("khayr", ["خير", "من", "النوم"], 1, "تنبيه الفجر: الصلاة خير من النوم", "Fajr alert: As-salatu khayrun min an-nawm", True),
    ("khayr2", ["خير", "من", "النوم"], 2, "تنبيه الفجر: الصلاة خير من النوم (مرتين)", "Fajr alert: As-salatu khayrun min an-nawm (twice)", True),
    ("end", ["لا", "اله", "الا", "الله"], 1, "تنبيه: الله أكبر الله أكبر، لا إله إلا الله", "Alert: Allahu akbar, la ilaha illa-llah", False),
]

def norm(w):
    w = re.sub(r"[ً-ٰٟـ]", "", w)          # diacritics, tatweel
    w = re.sub(r"[أإآٱ]", "ا", w).replace("ة", "ه").replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي")
    return re.sub(r"[^ء-ي]", "", w)


def same(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.72


def find(words, phrase):
    phrase = [norm(p) for p in phrase]
    """All start indexes where the phrase's words appear one after another."""
    out = []
    n = len(phrase)
    for i in range(len(words) - n + 1):
        if all(same(words[i + k][0], phrase[k]) for k in range(n)):
            out.append(i)
    return out


def load_audio(path):
    """16 kHz mono float samples via ffmpeg (the PyAV in the runner does not accept faster-whisper's options)."""
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0


def transcribe(model, path):
    segs, _ = model.transcribe(load_audio(path), language="ar", word_timestamps=True, beam_size=5, vad_filter=False)
    words = []
    for s in segs:
        for w in (s.words or []):
            n = norm(w.word)
            if n:
                words.append((n, w.start, w.end))
    return words


def main(part=0, parts=1):
    from faster_whisper import WhisperModel
    model = WhisperModel(os.environ.get("WHISPER", "small"), device="cpu", compute_type="int8")
    cat = json.load(open("adhans.json", encoding="utf-8"))
    by_id = {a["id"]: a for a in cat["adhans"]}
    keep = [a for a in cat["adhans"] if a.get("type") != "alert"]
    os.makedirs("audio", exist_ok=True)
    report, alerts = [], []
    sources = [i for i in SOURCES if i in by_id]
    for n, sid in enumerate(sources):
        if n % parts != part:
            continue
        src = by_id.get(sid)
        path = os.path.join("audio", sid + ".mp3")
        if not src or not os.path.exists(path):
            report.append("%s: missing" % sid)
            continue
        words = transcribe(model, path)
        report.append("%s: %d words heard: %s" % (sid, len(words), " ".join(w[0] for w in words[:60])))
        for kind, phrase, repeat, ar, en, fajr_only in KINDS:
            if fajr_only and not src.get("fajr"):
                continue
            hits = find(words, phrase)
            if kind in ("takbir", "takbir4"):
                hits = hits[:1]                      # the adhan opens with it
            if kind == "end":
                hits = hits[-1:]                     # the last words of the adhan
            if not hits:
                report.append("  %s: phrase not found" % kind)
                continue
            i = hits[0]
            n = len(phrase)
            start = words[i][1]
            end = words[i + n - 1][2]
            # include the immediate repetition ("... ... " said twice in a row)
            for _ in range(repeat - 1):
                nxt = [h for h in hits if h >= i + n and words[h][1] - end < 2.5]
                if nxt:
                    i = nxt[0]
                    end = words[i + n - 1][2]
            if kind == "end":
                # take the «الله اكبر الله اكبر» said just before
                j = hits[0]
                if j >= 4 and same(words[j - 4][0], norm("الله")) and same(words[j - 2][0], norm("الله")):
                    start = words[j - 4][1]
            if kind.startswith("khayr") and i - 0 > 0:
                start = words[hits[0] - 1][1]           # include «الصلاة» just before (often misheard)
            # cut only in pauses, never inside a word (so nothing is clipped at either end)
            from audio_cut import pauses, pause_before, pause_after
            if "ps" not in locals() or ps_for != sid:
                ps, ps_for = pauses(path), sid
            s0, e0 = pause_before(ps, start, 3.0), pause_after(ps, end, 3.0)
            if s0 is None or e0 is None:
                report.append("  %s: DROPPED, no pause to cut in" % kind)
                continue
            if end - start > 20:
                report.append("  %s: DROPPED, too long for an alert (%.1f s)" % (kind, end - start))
                continue
            start, end = max(0.0, s0), e0
            clip_id = "alert_%s_%s" % (kind, sid)
            out = os.path.join("audio", clip_id + ".mp3")
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "%.2f" % start, "-t", "%.2f" % (end - start), "-i", path,
                            "-af", "afade=t=in:d=0.06,afade=t=out:st=%.2f:d=0.25" % max(0.0, end - start - 0.25),
                            "-c:a", "libmp3lame", "-b:a", "96k", out], check=True)
            check = transcribe(model, out)
            # the clip must say exactly the words of the tone, complete, and nothing else
            want = [norm(p) for p in phrase] * repeat
            if kind.startswith("khayr"):
                want = ([norm("الصلاه")] + [norm(p) for p in phrase]) * repeat
            if kind == "end":
                want = [norm(p) for p in ["الله", "اكبر", "الله", "اكبر"]] + want
            heard = [w[0] for w in check]
            exact = len(heard) == len(want) and all(same(h, w) for h, w in zip(heard, want))
            if not exact:
                report.append("  %s: DROPPED, not exactly the words (heard: %s)" % (kind, " ".join(heard)))
                os.remove(out)
                continue
            secs = max(1, round(end - start))
            alerts.append({
                "id": clip_id, "type": "alert", "ar": "%s · %s" % (ar, src["ar"]), "en": "%s · %s" % (en, src["en"]),
                "fajr": fajr_only, "url": RAW + clip_id + ".mp3", "seconds": secs,
                "note_ar": "%d ث" % secs, "note_en": "%d s" % secs,
                "author": src["author"], "license": src["license"], "license_url": src["license_url"], "page": src["page"],
            })
            report.append("  %s: kept %.1f-%.1f s" % (kind, start, end))
    if parts > 1:  # one part of a parallel run: the merge step writes the catalogue
        json.dump({"alerts": alerts, "report": report}, open("alerts-part-%d.json" % part, "w", encoding="utf-8"), ensure_ascii=False)
        return
    finish(cat, keep, alerts, report)


def merge():
    """Joins the parts of a parallel run (alerts-part-*.json) into adhans.json."""
    import glob
    cat = json.load(open("adhans.json", encoding="utf-8"))
    keep = [a for a in cat["adhans"] if a.get("type") != "alert"]
    alerts, report = [], []
    for f in sorted(glob.glob("alerts-part-*.json")):
        d = json.load(open(f, encoding="utf-8"))
        alerts += d["alerts"]
        report += d["report"]
    finish(cat, keep, alerts, report)


def finish(cat, keep, alerts, report):
    # Fajr tones first, then the rest, grouped by kind
    order = {k[0]: i for i, k in enumerate(KINDS)}
    alerts.sort(key=lambda a: (not a["fajr"], order.get(a["id"].split("_")[1], 9), a["id"]))
    cat["adhans"] = keep + alerts
    json.dump(cat, open("adhans.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # credits for the clips
    cr = open("CREDITS.md", encoding="utf-8").read().split("\n## Alert tones")[0].rstrip("\n")
    cr += "\n\n## Alert tones\n\nShort clips cut from the recordings above (same authors and licences):\n\n"
    for a in alerts:
        cr += "- %s: %s, [%s](%s). Source: %s.\n" % (a["en"], a["author"], a["license"], a["license_url"], a["page"])
    open("CREDITS.md", "w", encoding="utf-8").write(cr)
    open("alerts-report.txt", "w", encoding="utf-8").write("\n".join(report) + "\n")
    print("\n".join(report))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "merge":
        merge()
    elif len(sys.argv) > 2:
        main(int(sys.argv[1]), int(sys.argv[2]))
    else:
        main()
