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
