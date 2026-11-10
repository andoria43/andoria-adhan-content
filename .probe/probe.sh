set -x
git clone -q --depth 1 https://github.com/abodehq/Athan-MP3 /tmp/a1 && find /tmp/a1 -type f -not -path '*/.git/*' -printf '%s %P\n'
cat /tmp/a1/README.md
for f in /tmp/a1/Sounds/*; do ffprobe -v error -show_entries format=duration -of csv=p=0 "$f" | tr '\n' ' '; echo "$f"; done
