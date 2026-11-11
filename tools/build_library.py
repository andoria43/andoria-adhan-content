#!/usr/bin/env python3
"""Builds the muezzin library: downloads each freely licensed recording listed in sources.json,
converts it to a normalised MP3 in audio/, and writes adhans.json (read by the app) and CREDITS.md."""
import glob, json, os, re, shutil, subprocess, sys, tempfile, urllib.parse, urllib.request

UA = "AndoriaAdhanLibrary/1.0 (https://github.com/andoria43/andoria-adhan-content)"
RAW = "https://raw.githubusercontent.com/andoria43/andoria-adhan-content/main/audio/"
ok, failed = [], []


def get(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as r, open(path, "wb") as f:
        shutil.copyfileobj(r, f)


def from_github(spec, tmp):
    _, repo, pattern, which = spec.split(":")
    d = os.path.join(tmp, "gh_" + repo.replace("/", "_"))
    if not os.path.isdir(d):
        subprocess.run(["git", "clone", "--depth", "1", "https://github.com/" + repo, d], check=True)
    files = sorted(f for f in glob.glob(os.path.join(d, "**", pattern), recursive=True) if os.path.isfile(f))
    print("found", [os.path.relpath(f, d) for f in files])
    fajr = [f for f in files if re.search(r"fajr|fajer|subh", os.path.basename(f), re.I)]
    regular = [f for f in files if f not in fajr]
    if which == "fajr":
        if not fajr:
            raise RuntimeError("no fajr file among " + str(files))
        return fajr[0]
    idx = int(which.replace("regular", "")) - 1
    return regular[idx]


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True).stdout.strip()
    try:
        return round(float(out))
    except ValueError:
        return 0


def main():
    src = json.load(open("sources.json", encoding="utf-8"))
    os.makedirs("audio", exist_ok=True)
    tmp = tempfile.mkdtemp()
    catalog = []
    credits = ["# Credits\n", "Every recording here is freely licensed. Converted to MP3 and loudness-normalised;",
               "nothing else was changed except where a trim is noted.\n"]
    for a in src["adhans"]:
        out = os.path.join("audio", a["id"] + ".mp3")
        try:
            s = a["source"]
            if s.startswith("commons:"):
                name = s[len("commons:"):]
                url = "https://commons.wikimedia.org/wiki/Special:FilePath/" + urllib.parse.quote(name.replace(" ", "_"))
                inp = os.path.join(tmp, a["id"] + os.path.splitext(name)[1])
                get(url, inp)
            elif s.startswith("ghfile:"):
                _, repo, path = s.split(":", 2)
                d = os.path.join(tmp, "gh_" + repo.replace("/", "_"))
                if not os.path.isdir(d):
                    subprocess.run(["git", "clone", "--depth", "1", "https://github.com/" + repo, d], check=True)
                inp = os.path.join(d, path)
            elif s.startswith("github:"):
                inp = from_github(s, tmp)
            else:
                raise RuntimeError("unknown source " + s)
            af = "loudnorm=I=-16:TP=-1.5:LRA=11"
            cmd = ["ffmpeg", "-y", "-v", "error", "-i", inp, "-vn", "-ac", "1", "-ar", "44100"]
            if a.get("trim_end"):
                end = a["trim_end"]
                cmd += ["-t", str(end)]
                af = "afade=t=out:st=%d:d=3,%s" % (end - 3, af)
            cmd += ["-af", af, "-c:a", "libmp3lame", "-b:a", "96k", out]
            subprocess.run(cmd, check=True)
            secs = duration(out)
            mins = "%d:%02d" % (secs // 60, secs % 60)
            catalog.append({
                "id": a["id"], "ar": a["ar"], "en": a["en"], "fajr": a["fajr"],
                "url": RAW + a["id"] + ".mp3", "seconds": secs,
                "note_ar": mins if a["license"].startswith("No licence") else "%s · %s" % (mins, a["license"]),
                "note_en": mins if a["license"].startswith("No licence") else "%s · %s" % (mins, a["license"]),
                "author": a["author"], "license": a["license"], "license_url": a["license_url"], "page": a["page"],
            })
            trim = " Trimmed to the first %d seconds (the du'a after the adhan removed)." % a["trim_end"] if a.get("trim_end") else ""
            credits.append("- **%s** (%s): %s, [%s](%s). Source: %s.%s" % (a["en"], a["ar"], a["author"], a["license"], a["license_url"], a["page"], trim))
            ok.append(a["id"])
        except Exception as e:
            print("FAILED", a["id"], e)
            failed.append("%s: %s" % (a["id"], e))
            if os.path.exists(out):
                os.remove(out)
    try:  # keep the alert tones cut by tools/make_alerts.py
        old = json.load(open("adhans.json", encoding="utf-8"))["adhans"]
        catalog += [a for a in old if a.get("type") == "alert"]
    except Exception:
        pass
    json.dump({"version": 1, "adhans": catalog}, open("adhans.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    try:
        tail = open("CREDITS.md", encoding="utf-8").read()
        if "\n## Alert tones" in tail:
            credits.append("\n## Alert tones" + tail.split("\n## Alert tones", 1)[1].rstrip("\n"))
    except Exception:
        pass
    open("CREDITS.md", "w", encoding="utf-8").write("\n".join(credits) + "\n")
    open("build-report.txt", "w").write("ok: %s\nfailed:\n%s\n" % (", ".join(ok), "\n".join(failed)))
    print("ok", ok, "failed", failed)


if __name__ == "__main__":
    main()
