"""Shared helpers: pauses in a recording, and words placed between them.

A recording is cut only in the middle of a pause (silence), never inside a word, so a clip can't lose
the start or the end of what is said."""
import re, subprocess


def pauses(path, db=-30, min_len=0.25):
    """[(start, end)] of the quiet stretches (ffmpeg silencedetect)."""
    out = subprocess.run(["ffmpeg", "-v", "info", "-i", path, "-af", "silencedetect=noise=%ddB:d=%.2f" % (db, min_len),
                          "-f", "null", "-"], capture_output=True, text=True, errors="replace").stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", out)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", out)]
    res = list(zip(starts, ends))
    if len(starts) > len(ends):
        res.append((starts[-1], starts[-1] + 5))
    return res


def pause_before(ps, t, max_back=6.0):
    """Middle of the last pause that ends before time t (within max_back seconds), or None."""
    best = None
    for s, e in ps:
        if e <= t + 0.05 and t - e <= max_back:
            best = (s + e) / 2 if e - s < 1.2 else e - 0.3
    return best


def pause_after(ps, t, max_fwd=6.0):
    """Middle of the first pause that starts after time t (within max_fwd seconds), or None."""
    for s, e in ps:
        if s >= t - 0.05 and s - t <= max_fwd:
            return (s + e) / 2 if e - s < 1.2 else s + 0.3
    return None


def duration(path):
    o = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True).stdout.strip()
    try:
        return float(o)
    except ValueError:
        return 0.0


# ---- energy valleys: where the voice really stops (works under echo and music too) ----

def envelope(path, hop=0.02):
    """Loudness in dB per 20 ms frame (16 kHz mono), smoothed over 100 ms."""
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                         check=True, capture_output=True).stdout
    x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
    n = int(16000 * hop)
    frames = len(x) // n
    if frames == 0:
        return np.zeros(1), hop
    rms = np.sqrt(np.mean(x[:frames * n].reshape(frames, n) ** 2, axis=1) + 1e-10)
    db = 20 * np.log10(rms)
    k = 5
    db = np.convolve(db, np.ones(k) / k, mode="same")
    return db, hop


def valley(env, a, b):
    """Time of the quietest moment between a and b seconds, and its level in dB."""
    db, hop = env
    i0, i1 = max(0, int(a / hop)), min(len(db), int(b / hop) + 1)
    if i1 <= i0:
        return a, float(db[min(len(db) - 1, max(0, i0))])
    seg = db[i0:i1]
    j = int(seg.argmin())
    return (i0 + j) * hop, float(seg[j])


def voice_end(env, t, limit, floor_below_peak=28.0):
    """From time t, the first moment the sound falls well below the voice (peak - floor) for 0.25 s,
    looking no further than limit. Falls back to the quietest point before limit."""
    import numpy as np
    db, hop = env
    peak = float(np.percentile(db, 98))
    thr = peak - floor_below_peak
    i, stop, need = int(t / hop), min(len(db), int(limit / hop)), int(0.25 / hop)
    run = 0
    while i < stop:
        run = run + 1 if db[i] < thr else 0
        if run >= need:
            return (i - need + 1) * hop + 0.08
        i += 1
    return valley(env, t, limit)[0]


def quiet_edges(path, edge=0.08, below_peak=18.0):
    """True when the first and the last 80 ms of a clip are well below its loud parts (nothing cut off)."""
    import numpy as np
    db, hop = envelope(path)
    if len(db) < 10:
        return False
    peak = float(np.percentile(db, 95))
    k = max(1, int(edge / hop))
    head, tail = float(db[:k].max()), float(db[-k:].max())
    return head < peak - below_peak and tail < peak - below_peak


def quiet_cut(env, a, b, below_peak=14.0):
    """True when the recording is quiet at both cut points a and b (well below the loudest part between)."""
    import numpy as np
    db, hop = env
    i0, i1 = int(a / hop), min(len(db) - 1, int(b / hop))
    if i1 - i0 < 10:
        return False
    peak = float(np.percentile(db[i0:i1], 95))
    at = lambda i: float(db[max(0, i - 2):min(len(db), i + 3)].max())
    return at(i0) < peak - below_peak and at(i1) < peak - below_peak
