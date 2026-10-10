#!/bin/sh
# Autogamer installer. Runs ON the handheld, from the unpacked release directory.
#   ./install.sh [--no-e4b] [--no-models]      ./install.sh --uninstall
#   --no-e4b     skip gemma-4-E4B (5.2 GB): Tetris, NES Tennis, Excitebike, Punch-Out!! and Contra then play with E2B, which
#                thinks faster and worse
#   --no-models  skip the downloads (the models directory already has them)
# The models go to llamatalk's shared models directory, which every app that bundles llamatalk uses (Retro Voice
# Chat, for one): models already there are not downloaded again. Which directory: AG_MODELS if set, else the shared
# one if this device has it, else ./models. It brings no games: it says which ROMs it found and which to add.
# Env: AG_MODELS, AG_PORTS (default /storage/roms/ports), AG_ROMS (default /storage/roms).
set -u
H=$(cd "$(dirname "$0")" && pwd); P=${AG_PORTS:-/storage/roms/ports}; LTM=$H/llamatalk/models.sh
ENTRY="Autogamer.sh"
# the lab prototype's entries, one per game ("AI Plays ...", ollamadreno's retroplay/rp.sh): matched by what they exec
STALE_RE="retroplay/rp\.sh"
E4B=1; MODELS=1
for a in "$@"; do
  case $a in
    --no-e4b) E4B="" ;; --no-models) MODELS="" ;;
    --uninstall)
      rm -f "$P/$ENTRY"
      echo "Removed the Ports entry. This directory and the models (shared with other llamatalk apps) are still here:"
      echo "  $H"; echo "  $("$LTM" path 2>/dev/null || echo "$H/models")"; exit 0 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done

chmod +x "$H"/app/*.sh "$H"/llamatalk/bin/* "$LTM" "$H"/test/*.sh 2>/dev/null
for f in llamatalk/bin/llama-server llamatalk/bin/tts-server llamatalk/models.sh app/autogamer.sh app/run.sh app/games.py; do
  [ -e "$H/$f" ] || { echo "missing $H/$f: this is not an unpacked release (see build/build.sh)" >&2; exit 1; }
done

M=${AG_MODELS:-}
[ -n "$M" ] || M=$("$LTM" path 2>/dev/null) || M=""
[ -n "$M" ] || M=$H/models
SETS="e2b tts"; [ -n "$E4B" ] && SETS="$SETS e4b"
if [ -n "$MODELS" ]; then
  "$LTM" fetch --dir "$M" $SETS
elif [ -d "$M" ]; then
  "$LTM" use "$M"; "$LTM" check $SETS >/dev/null || echo "warning: $M still misses: $("$LTM" check $SETS | tr '\n' ' ')"
else
  echo "warning: no models directory yet ($M); run install.sh without --no-models"
fi

mkdir -p "$P"
for f in "$P"/*.sh; do
  [ -f "$f" ] && [ "$f" != "$P/$ENTRY" ] && grep -qsE "$STALE_RE" "$f" && rm -f "$f" && echo "removed the old entry $f"
done
sed -e "s|@AG_HOME@|$H|g" "$H/ports/$ENTRY" > "$P/$ENTRY" && chmod +x "$P/$ENTRY" && echo "port $P/$ENTRY"

echo "Games (autogamer brings none: add your own copies; see README):"
python3 "$H/app/games.py" status
echo "Done. Refresh the game lists in EmulationStation; Autogamer is under Ports."
