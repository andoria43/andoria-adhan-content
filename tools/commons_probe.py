#!/usr/bin/env python3
"""Lists the adhan recordings on Wikimedia Commons with their licence and length."""
import json, urllib.error, urllib.parse, urllib.request

API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "AndoriaAdhanLibraryCheck/1.0 (https://github.com/andoria43/andoria-adhan-content)"}


def get(params):
    import time
    params = dict(params, format="json", maxlag=5)
    for attempt in range(8):
        time.sleep(1.5)
        try:
            req = urllib.request.Request(API + "?" + urllib.parse.urlencode(params), headers=UA)
            return json.load(urllib.request.urlopen(req, timeout=60))
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):
                time.sleep(10 * (attempt + 1))
                continue
            raise
    raise RuntimeError("Commons kept refusing")


files = set()
# categories, walked a few levels deep
seen, todo = set(), ["Category:Adhan", "Category:Audio files of adhan", "Category:Call to prayer", "Category:Azan"]
depth = {c: 0 for c in todo}
while todo:
    c = todo.pop()
    if c in seen:
        continue
    seen.add(c)
    cont = {}
    while True:
        try:
            r = get(dict({"action": "query", "list": "categorymembers", "cmtitle": c, "cmlimit": 500, "cmtype": "file|subcat"}, **cont))
        except Exception:
            break
        for m in r.get("query", {}).get("categorymembers", []):
            t = m["title"]
            if t.startswith("Category:") and depth[c] < 3:
                depth[t] = depth[c] + 1
                todo.append(t)
            elif t.startswith("File:"):
                files.add(t)
        if "continue" not in r:
            break
        cont = r["continue"]
# text search too
for q in ["adhan", "azan", "athan", "adhaan", "ezan", "call to prayer", "أذان", "اذان", "muezzin"]:
    try:
        r = get({"action": "query", "list": "search", "srsearch": q + " filetype:audio", "srnamespace": 6, "srlimit": 500})
        for s in r["query"]["search"]:
            files.add(s["title"])
    except Exception:
        pass

out = []
fl = sorted(files)
for i in range(0, len(fl), 40):
    r = get({"action": "query", "titles": "|".join(fl[i:i + 40]), "prop": "imageinfo",
             "iiprop": "url|size|mime|extmetadata|mediatype"})
    for p in r["query"]["pages"].values():
        ii = (p.get("imageinfo") or [{}])[0]
        if ii.get("mediatype") not in ("AUDIO", "VIDEO") and not str(ii.get("mime", "")).startswith(("audio", "video", "application/ogg")):
            continue
        md = ii.get("extmetadata", {})
        v = lambda k: (md.get(k) or {}).get("value", "")
        out.append({"title": p["title"], "url": ii.get("url"), "mime": ii.get("mime"), "size": ii.get("size"),
                    "seconds": ii.get("duration"), "license": v("LicenseShortName"), "artist": v("Artist")[:200],
                    "desc": v("ImageDescription")[:300], "categories": v("Categories")[:300]})
json.dump(out, open("commons-adhan.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(len(fl), "files found,", len(out), "audio/video")
