#!/bin/sh
# Autogamer never carries a game: no ROM, no archive, no save state, no RAM or screen dump. Fails if the tree has a
# file with a ROM's extension, an iNES header, or a binary over 64 KB (the bundled llamatalk/ excepted). build/build.sh and
# CI run it. Usage: test/check_no_roms.sh [DIR]   (default: the repository's tracked files, else the directory)
R=${1:-$(cd "$(dirname "$0")/.." && pwd)}; cd "$R" || exit 2
if [ -z "${1:-}" ] && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then L=$(git ls-files)
else L=$(find . -path ./build/work -prune -o -path ./dist -prune -o -path ./llamatalk -prune -o -path ./.git -prune -o -type f -print | sed 's|^\./||'); fi
bad=0
echo "$L" | while IFS= read -r f; do
  [ -f "$f" ] || continue
  case $(echo "$f" | tr A-Z a-z) in
    *.nes|*.fds|*.a26|*.bin|*.rom|*.sfc|*.smc|*.gb|*.gbc|*.gba|*.gen|*.sms|*.gg|*.z64|*.n64|*.iso|*.cue|*.chd)
      echo "ROM-like file: $f"; exit 1 ;;
    *.zip|*.7z|*.rar|*.state*|*.srm|*.sav|*.png|*.jpg|*.wav) echo "archive, save or capture: $f"; exit 1 ;;
  esac
  [ "$(head -c 4 "$f" | od -An -tx1 | tr -d ' ')" = "4e45531a" ] && { echo "iNES header: $f"; exit 1; }
  [ "$(wc -c < "$f")" -gt 65536 ] && ! grep -qI . "$f" && { echo "large binary: $f"; exit 1; }
  :
done || bad=1
[ $bad = 0 ] && echo "no ROMs, saves or captures in the tree"
exit $bad
