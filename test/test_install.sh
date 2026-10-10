#!/bin/sh
# install.sh in a sandbox: a copy of the release, a temp HOME, Ports and ROM folders, a file:// mirror for the models
# (small fake files). Checks: a device with a shared llamatalk directory (Retro Voice Chat's) downloads only what
# autogamer adds; a fresh one fetches into ./models; the lab's "AI Plays" entries are replaced by one Autogamer entry;
# --no-e4b; --uninstall. No network, no real paths touched.
# Usage: test/test_install.sh [unpacked release dir]   (default: dist/autogamer; runs on the host or on the handheld)
R=${1:-$(cd "$(dirname "$0")/.." && pwd)/dist/autogamer}
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
export LT_HF=file://$T/hf AG_PORTS=$T/ports AG_ROMS=$T/roms; unset AG_MODELS LLAMATALK_MODELS XDG_CONFIG_HOME
grep -v '^#' "$R/llamatalk/models.txt" | while read -r set repo file as; do
  [ -n "$set" ] && mkdir -p "$T/hf/$repo/resolve/main" && echo "$file" > "$T/hf/$repo/resolve/main/$file"
done
n=0; bad=0
ok() { n=$((n + 1)); if [ "$1" = 0 ]; then echo "ok   $2"; else echo "FAIL $2"; bad=$((bad + 1)); fi; }
fresh() { rm -rf "$T/app" "$T/ports" "$T/home" "$T/roms"; cp -r "$R" "$T/app"; mkdir -p "$T/ports" "$T/roms"; export HOME=$T/home; }
E="$T/ports/Autogamer.sh"

# 1. Retro Voice Chat made the shared directory (asr e2b tts); the lab's entries are there, and one unrelated entry
fresh; mkdir -p "$T/shared" "$T/home/.config/llamatalk"; echo "$T/shared" > "$T/home/.config/llamatalk/models-dir"
for f in "$T"/hf/*/*/resolve/main/*; do case $f in *E4B*) ;; *) cp "$f" "$T/shared/" ;; esac; done
printf '#!/bin/sh\nexec "/storage/ollamadreno/retroplay/rp.sh" tetris\n' > "$T/ports/AI Plays Tetris.sh"
printf '#!/bin/sh\nexec "/storage/ollamadreno/retroplay/rp.sh" smb\n' > "$T/ports/AI Plays Super Mario Bros.sh"
printf '#!/bin/sh\nexec firefox\n' > "$T/ports/Firefox.sh"
"$T/app/install.sh" > "$T/out1" 2>&1; ok $? "shared: install.sh runs"
[ "$(grep -c '^get ' "$T/out1")" = 1 ] && grep -q '^get  gemma-4-E4B' "$T/out1"; ok $? "shared: only E4B downloaded"
[ "$("$T/app/llamatalk/models.sh" path)" = "$T/shared" ] && [ ! -e "$T/app/models" ]; ok $? "shared: same directory, no ./models"
[ ! -e "$T/ports/AI Plays Tetris.sh" ] && [ ! -e "$T/ports/AI Plays Super Mario Bros.sh" ]; ok $? "the lab's entries are gone"
[ -f "$T/ports/Firefox.sh" ]; ok $? "other entries stay"
grep -q "exec \"$T/app/app/autogamer.sh\"" "$E"; ok $? "the Autogamer entry runs app/autogamer.sh"
[ "$(grep -c MISSING "$T/out1")" = 9 ]; ok $? "no ROMs: all nine games say what to add"

# 2. fresh device, --no-e4b: ./models with e2b and tts only
fresh; "$T/app/install.sh" --no-e4b > "$T/out2" 2>&1; ok $? "fresh --no-e4b: install.sh runs"
[ "$(ls "$T/app/models" | wc -l)" = 3 ] && [ ! -e "$T/app/models/gemma-4-E4B_q4_0-it.gguf" ]; ok $? "fresh --no-e4b: e2b and tts in ./models"

# 3. --uninstall: the entry goes, the models stay
"$T/app/install.sh" --uninstall > "$T/out3" 2>&1; ok $? "uninstall runs"
[ ! -e "$E" ] && [ -f "$T/app/models/gemma-4-E2B_q4_0-it.gguf" ]; ok $? "uninstall: entry gone, models kept"

echo "$((n - bad))/$n passed"; [ $bad = 0 ]
