#!/usr/bin/env python3
"""Finds more adhan recordings in public GitHub repositories and checks each one by listening to it.

Step 1 (list):  search GitHub for adhan/azan/athan repositories (plus a fixed list), clone each one,
                collect audio files of 40 s to 7 min, drop exact duplicates; writes .harvest/candidates.json
Step 2 (check): transcribe every candidate (Arabic speech recognition). It is an adhan only when it says
                «الله اكبر», «حي على الصلاه» and «حي على الفلاح»; a Fajr adhan also says «الصلاه خير من النوم».
                Writes .harvest/part-N.json (run in parallel parts).
"""
import glob, hashlib, json, os, re, subprocess, sys, urllib.request

EXTRA = ["AalianKhan/adhans", "rehanhaider/adhan", "achaudhry/adhan", "adeeonline/azaan-clock", "kamranzafar/piprayer",
         "0xzer0x/athany", "d3ffen/Adhan-Alert", "zubir2k/HomeAssistantAdzan", "DBChoco/Muezzin", "HamzaAlsarakbi/AthanApp",
         "esc-0-bar/adhan", "agnanp/praydo", "semaf/adhan-python", "meypod/al-azan", "abodehq/Athan-MP3"]
QUERIES = ["adhan mp3", "azan mp3", "athan mp3", "adhan audio", "azan audio", "athan sounds", "adhan sounds",
           "fajr adhan", "azan fajr", "adzan", "ezan mp3", "prayer times adhan", "muezzin", "azan clock", "adhan player"]
AUDIO = re.compile(r"\.(mp3|ogg|m4a|wav|aac|opus|flac)$", re.I)
TOK = os.environ.get("GH_TOKEN", "")


def api(url):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "Authorization": "Bearer " + TOK})
    return json.load(urllib.request.urlopen(req, timeout=60))


def dur(p):
    o = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p], capture_output=True, text=True).stdout
    try:
        return float(o.strip())
    except ValueError:
        return 0


def listing():
    repos = {r: 0 for r in EXTRA}
    for q in QUERIES:
        try:
            for it in api("https://api.github.com/search/repositories?per_page=50&q=" + urllib.parse.quote(q))["items"]:
                if it["size"] < 400000:
                    repos.setdefault(it["full_name"], it["size"])
        except Exception as e:
            print("search failed", q, e)
    print(len(repos), "repositories")
    seen, out = set(), []
    os.makedirs("/tmp/h", exist_ok=True)
    for r in repos:
        d = "/tmp/h/" + r.replace("/", "__")
        if subprocess.run(["git", "clone", "-q", "--depth", "1", "https://github.com/" + r, d], timeout=600).returncode != 0:
            continue
        for f in glob.glob(d + "/**/*", recursive=True):
            if not (os.path.isfile(f) and AUDIO.search(f)) or os.path.getsize(f) < 150000:
                continue
            md5 = hashlib.md5(open(f, "rb").read()).hexdigest()
            if md5 in seen:
                continue
            seen.add(md5)
            s = dur(f)
            if 40 <= s <= 420:
                out.append({"repo": r, "path": os.path.relpath(f, d), "seconds": round(s), "md5": md5})
        subprocess.run(["bash", "-c", "find '%s' -type f ! -iregex '.*\\.\\(mp3\\|ogg\\|m4a\\|wav\\|aac\\|opus\\|flac\\)' -delete" % d])
    os.makedirs(".harvest", exist_ok=True)
    json.dump(out, open(".harvest/candidates.json", "w"), indent=1)
    print(len(out), "candidates")


def norm(w):
    w = re.sub(r"[ً-ٰـ]", "", w)
    w = re.sub(r"[أإآٱ]", "ا", w).replace("ة", "ه").replace("ى", "ي")
    return re.sub(r"[^ء-ي]", "", w)


def check(part, parts):
    import numpy as np
    from faster_whisper import WhisperModel
    model = WhisperModel(os.environ.get("WHISPER", "base"), device="cpu", compute_type="int8")
    cands = json.load(open(".harvest/candidates.json"))
    res = []
    for i, c in enumerate(cands):
        if i % parts != part:
            continue
        f = "/tmp/h/" + c["repo"].replace("/", "__") + "/" + c["path"]
        if not os.path.exists(f):
            subprocess.run(["git", "clone", "-q", "--depth", "1", "https://github.com/" + c["repo"], "/tmp/h/" + c["repo"].replace("/", "__")])
        try:
            raw = subprocess.run(["ffmpeg", "-v", "error", "-i", f, "-f", "s16le", "-ac", "1", "-ar", "16000", "-"], check=True, capture_output=True).stdout
            segs, _ = model.transcribe(np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0, language="ar", beam_size=1, vad_filter=False)
            text = " ".join(norm(w) for s in segs for w in s.text.split())
        except Exception as e:
            c["error"] = str(e)
            res.append(c)
            continue
        t = text.replace(" ", "")
        c["takbir"] = "اللهاكبر" in t
        c["salah"] = "حيعليالصلاه" in t or "حيعلالصلاه" in t or "حيعلىالصلاه" in t
        c["falah"] = "حيعليالفلاح" in t or "حيعلالفلاح" in t or "حيعلىالفلاح" in t
        c["khayr"] = "خيرمنالنوم" in t or "خيرمنالنو" in t
        c["adhan"] = c["takbir"] and (c["salah"] or c["falah"])
        c["heard"] = text[:400]
        res.append(c)
        print(i, c["repo"], c["path"], c["adhan"], c["khayr"])
    json.dump(res, open(".harvest/part-%d.json" % part, "w"), ensure_ascii=False, indent=1)


def verify(part, parts):
    """Second, careful listen (the larger model) to the selected recordings: whole text, Fajr phrase, how it starts."""
    import numpy as np
    from faster_whisper import WhisperModel
    model = WhisperModel(os.environ.get("WHISPER", "small"), device="cpu", compute_type="int8")
    sel = json.load(open(".harvest/selected.json"))
    res = []
    for i, c in enumerate(sel):
        if i % parts != part:
            continue
        d = "/tmp/h/" + c["repo"].replace("/", "__")
        if not os.path.isdir(d):
            subprocess.run(["git", "clone", "-q", "--depth", "1", "https://github.com/" + c["repo"], d])
        f = d + "/" + c["path"]
        try:
            raw = subprocess.run(["ffmpeg", "-v", "error", "-i", f, "-f", "s16le", "-ac", "1", "-ar", "16000", "-"], check=True, capture_output=True).stdout
            segs, _ = model.transcribe(np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0, language="ar", beam_size=5, vad_filter=False)
            words = [norm(w) for s in segs for w in s.text.split()]
            words = [w for w in words if w]
        except Exception as e:
            c["error"] = str(e); res.append(c); continue
        t = "".join(words)
        c["text"] = " ".join(words)
        c["khayr"] = "خيرمنالنوم" in t or "خيرمنالنو" in t
        c["shahada"] = len(re.findall("اشهد|اشهر|اشعد", t))
        c["salah"] = len(re.findall("حيعل[يى]?الصلا|حياعل[يى]?الصلا|حيالصلا", t))
        c["falah"] = len(re.findall("حيعل[يى]?الفلا|حياعل[يى]?الفلا|حيالفلا", t))
        c["first"] = " ".join(words[:4])
        res.append(c)
        print(i, c["repo"], c["path"], c["khayr"], c["shahada"], c["first"])
    json.dump(res, open(".harvest/verify-%d.json" % part, "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    import urllib.parse
    if sys.argv[1] == "list":
        listing()
    elif sys.argv[1] == "verify":
        verify(int(sys.argv[2]), int(sys.argv[3]))
    else:
        check(int(sys.argv[2]), int(sys.argv[3]))
