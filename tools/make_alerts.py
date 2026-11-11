#!/usr/bin/env python3
"""Cuts short alert tones out of the adhans already in audio/ and adds them to adhans.json as
{"type": "alert"} entries, so the app can offer them for the alert before the adhan.

Nothing is cut by guesswork: each recording is transcribed (Arabic speech recognition with word times),
the wanted phrase is located, cut with a short fade, and the CUT FILE IS TRANSCRIBED AGAIN. A clip is kept
only when the second transcript contains the phrase too. What was kept or dropped goes to alerts-report.txt.
"""
import difflib, json, os, re, subprocess, sys

RAW = "https://raw.githubusercontent.com/andoria43/andoria-adhan-content/main/audio/"
# recordings to cut from (id in adhans.json)
SOURCES = ["khalaf_1", "khalaf_2", "khalaf_fajr", "malek_fajr", "makkah", "alafasy", "abdulbasit", "minshawi"]
# phrase kinds: id part, words to find, Arabic / English title, only Fajr
KINDS = [
    ("takbir", ["الله", "اكبر"], 2, "تنبيه: الله أكبر", "Alert: Allahu akbar", False),
    ("hayya", ["حي", "على", "الصلاه"], 1, "تنبيه: حيّ على الصلاة", "Alert: Hayya ala-s-salah", False),
    ("khayr", ["خير", "من", "النوم"], 1, "تنبيه الفجر: الصلاة خير من النوم", "Fajr alert: As-salatu khayrun min an-nawm", True),
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


def main():
    from faster_whisper import WhisperModel
    model = WhisperModel(os.environ.get("WHISPER", "small"), device="cpu", compute_type="int8")
    cat = json.load(open("adhans.json", encoding="utf-8"))
    by_id = {a["id"]: a for a in cat["adhans"]}
    keep = [a for a in cat["adhans"] if a.get("type") != "alert"]
    os.makedirs("audio", exist_ok=True)
    report, alerts = [], []
    for sid in SOURCES:
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
            if kind == "takbir":
                hits = hits[:1]                      # the adhan opens with it
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
            if kind == "khayr" and i - 0 > 0:
                start = words[hits[0] - 1][1]           # include «الصلاة» just before (often misheard)
            if end - start > 20:
                report.append("  %s: DROPPED, too long for an alert (%.1f s)" % (kind, end - start))
                continue
            start = max(0.0, start - 0.15)
            end = end + 0.35
            clip_id = "alert_%s_%s" % (kind, sid)
            out = os.path.join("audio", clip_id + ".mp3")
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "%.2f" % start, "-t", "%.2f" % (end - start), "-i", path,
                            "-af", "afade=t=in:d=0.06,afade=t=out:st=%.2f:d=0.25" % max(0.0, end - start - 0.25),
                            "-c:a", "libmp3lame", "-b:a", "96k", out], check=True)
            check = transcribe(model, out)
            if not find(check, phrase):
                report.append("  %s: DROPPED, clip did not contain the phrase (heard: %s)" % (kind, " ".join(w[0] for w in check)))
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
    main()
