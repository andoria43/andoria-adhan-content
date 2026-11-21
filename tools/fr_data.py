"""French meanings: Muhammad Hamidullah, corrected by Rowwad Translation Center (QuranEnc.com).
QuranEnc allows re-publishing with attribution, unchanged text, no ads, and staying updated from QuranEnc."""
import json, urllib.request, time, os
AYAHS_TOTAL = 6236
os.makedirs("out", exist_ok=True)
lines, ver = [], ""
for s in range(1, 115):
    url = f"https://quranenc.com/api/v1/translation/sura/french_hameedullah/{s}"
    for t in range(6):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Android) AndoriaAdhan/1.0", "Accept": "application/json"})
            d = json.load(urllib.request.urlopen(req, timeout=60)); break
        except Exception as e:
            print("retry", s, e); time.sleep(5)
    else:
        raise SystemExit(f"failed surah {s}")
    for r in d["result"]:
        tx = " ".join(r["translation"].split("\n")).strip().replace("|", "/")
        fn = "\\n".join(x.strip() for x in (r.get("footnotes") or "").split("\n") if x.strip()).replace("|", "/")
        if fn: tx += "\\n\\n" + fn
        lines.append(f'{int(r["sura"])}|{int(r["aya"])}|{tx}')
print("ayat:", len(lines))
assert len(lines) == AYAHS_TOTAL, len(lines)
open("out/fr.txt", "w", encoding="utf-8").write("\n".join(lines) + "\n")
print(lines[0]); print(lines[-1])
