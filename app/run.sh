#!/bin/sh
# Runs one game (autogamer.sh calls it from the menu; also from ssh): RetroArch runs the game, a script plays it from
# RAM over RetroArch's UDP ports (commands 55355, network remote 55400), and a language model plays or talks.
#   tetris-model  NES Tetris (fceumm): tetris_llm.py, the model picks each placement (E4B if installed). The game does
#                 not stop while it thinks: it runs in RetroArch's slow motion, and the music slows and drops with it.
#                 The game starts at the NES level whose pieces fall in about the model's think time
#                 (AG_TL_GAMELEVEL to choose); Hard, Harder, Hardest slow it so the model gets 2, 1.5, 1.2 times its
#                 think time per piece; Expert is real time. The mean think time comes from state/think_MODEL.txt (each
#                 session saves its own; seeded from measurements). RetroArch reads slowmotion_ratio only at start: a
#                 change saves the state, restarts RetroArch, loads it.
#   ntennis-model NES Tennis (fceumm), singles against the game's computer (level AG_NT_CPU, default 1): the model
#                 (E4B if installed, AG_NTENNIS_MODEL) picks where each return lands, of the two ends it can reach
#                 inside the court (ntennis_llm.py); no answer in time, an impulse return away from the computer.
#                 Slow-motion levels as for tetris-model.
#   excitebike-model  Excitebike (fceumm), Selection A from track AG_EB_TRACK (1-5, default 1): excitebike_llm.py, a
#                 reflex rider (wheelie over hurdles, landings) and the model (E4B if installed, AG_EXCITEBIKE_MODEL)
#                 calling turbo or cruise, each call holding until the next: a turbo it is too slow to call off
#                 overheats the engine. Slow-motion levels as for tetris-model, by a human's 1, 2, 3 s a call.
#   punchout-model  Mike Tyson's Punch-Out!! (fceumm): punchout_llm.py, a reflex loop dodges every punch; the model
#                 (E4B if installed, AG_PUNCHOUT_MODEL) runs the offence: when the opponent is open it calls pummel,
#                 body blows or wait, in bullet time (the game runs in real time and slows down for each call). Levels
#                 by a human's 0.5, 0.75, 1 s to see the opening.
#   contra-coop   Contra (fceumm), 2 players: you play Player 1 on the handheld, contra_llm.py plays Player 2 (a
#                 reflex soldier from RAM, contra.py; RetroArch's network remote for user 2) and the model (E4B if
#                 installed, AG_CONTRA_MODEL) makes its calls: cover, lead or hang back, take or leave a weapon,
#                 borrow a life. Real time, no levels (you are playing too). AG_CT_KONAMI=1: the 30-lives code at the
#                 title; AG_CT_STANDIN=1: a reflex soldier plays Player 1 as well (to watch without a human).
#   tennis        Activision Tennis (Atari 2600, stella): play.py vs the CPU, narrate.py calls the match (E2B, Pocket TTS)
#   tennis-model  Activision Tennis: the model aims every return (tennis_llm.py; E2B, AG_TENNIS_MODEL), play.py's reflex
#                 loop runs to the ball. Slow-motion levels; a ball the model has not answered in time is missed.
#   tetris        NES Tetris: tetris.py, the heuristic, in real time
#   smb           Super Mario Bros. (fceumm): smb.py, a run-and-jump bot
# The level games show the level picker while the model loads (picker.py; the last pick is highlighted; AG_LEVEL 0-3
# skips it, as does AG_PICK=0), and SELECT in the game pauses it for the same menu (level.py).
# Usage: run.sh GAME     HOME quits (home.py; RetroArch's own exit hotkey works too): everything stops with RetroArch.
# On screen: a MangoHud bar across the top (fps, frame times, the model at work), when MangoHud is installed.
# RetroArch gets ROCKNIX's settings for the system (setsettings.sh, as runemu.sh does) plus autogamer.cfg for this
# launch only (network ports on, save-state autoload/autosave off): retroarch.cfg is never edited.
# Env: AG_LLAMA (llama-server, default llamatalk's), AG_TTS (tts-server), AG_MODELS (default llamatalk's shared models
#   directory), AG_ROMS (default /storage/roms), AG_TETRIS_MODEL / AG_TENNIS_MODEL / AG_NTENNIS_MODEL /
#   AG_EXCITEBIKE_MODEL / AG_PUNCHOUT_MODEL / AG_CONTRA_MODEL (gguf basename), AG_EB_TRACK (Excitebike's first track),
#   AG_VOICE (Pocket TTS voice), NR_TTS=0 (silent), AG_RA_CPUS (default 0-3; empty = unpinned), AG_HUD=0 (no MangoHud),
#   AG_60HZ=0 (leave the panel at 120 Hz), AG_RA_CFG (one more RetroArch config file, appended last)
# Cores (SM8250): RetroArch and the players on 0-3, the LLM on 4-7, TTS on 6-7. Unpinned, RetroArch wandered onto
# 4-7 and the LLM's point calls gave it 23 frames over 25 ms a minute; pinned to 0-3, 1.

[ -f /etc/profile ] && . /etc/profile >/dev/null 2>&1
V=$(cd "$(dirname "$0")" && pwd); H=$(dirname "$V"); ST=$H/state
LLAMA=${AG_LLAMA:-$H/llamatalk/bin/llama-server}; TTSB=${AG_TTS:-$H/llamatalk/bin/tts-server}
M=${AG_MODELS:-$("$H/llamatalk/models.sh" path 2>/dev/null)}; M=${M:-$H/models}
GAME=${1:-tetris-model}; O=$H/logs/$GAME
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/0-runtime-dir} WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-wayland-1} HOME=${HOME:-/storage}
SWAYSOCK=$(ls "$XDG_RUNTIME_DIR"/sway-ipc.*.sock 2>/dev/null | head -1); export SWAYSOCK
ulimit -c 0
rm -rf "$O"; mkdir -p "$O" "$ST" /dev/shm/autogamer; : > /dev/shm/autogamer/hud.txt

# a fullscreen terminal for a command (no RetroArch yet to show things): a message, the level picker
onscreen() {
  ( for i in 1 2 3 4 5 6; do sleep 0.5; swaymsg '[app_id="autogamer"] fullscreen enable' >/dev/null 2>&1 && break; done ) &
  foot --app-id=autogamer -f "monospace:size=20" -o colors.background=030a03 -o colors.foreground=33ff66 "$@"
}
# a message on the screen for a few seconds
fail() {
  echo "autogamer: $*" >&2; echo "$*" > "$O/error.txt"
  onscreen sh -c 'fold -s -w 60 "$1"; sleep 8' sh "$O/error.txt" 2>/dev/null
  exit 1
}

SYS=""; eval "$(python3 "$V/games.py" shell "$GAME" 2>/dev/null)"; [ -n "$SYS" ] || fail "unknown game: $GAME"
[ -n "$ROM" ] || fail "No ROM for $TITLE. Autogamer brings no games. $NEED (see README)."
[ -f /tmp/cores/${CORE}_libretro.so ] || fail "RetroArch core $CORE is missing (/tmp/cores/${CORE}_libretro.so)."

PIDS=""
cleanup() {
  trap - EXIT INT TERM HUP
  for p in $PIDS; do kill "$p" 2>/dev/null; done
  sleep 1; for p in $PIDS; do kill -9 "$p" 2>/dev/null; done
  [ -n "${RESTORE_MODE:-}" ] && wlr-randr --output "$OUT" --mode "$RESTORE_MODE" 2>/dev/null
  : > /dev/shm/autogamer/hud.txt
}
trap cleanup EXIT
trap 'exit 130' INT TERM HUP

# the model server, text only: $1 gguf basename
start_llm() {
  for f in "$LLAMA" "$M/$1.gguf"; do [ -e "$f" ] || fail "Missing $f (run install.sh)."; done
  export NR_VGAP=0
  ( exec env -u OMP_PROC_BIND -u OMP_PLACES taskset -c 4-7 "$LLAMA" -m "$M/$1.gguf" -dev none -fa off --jinja -rea off \
      -c 4096 -t 4 -np 1 --cache-ram 0 --host 127.0.0.1 --port 8099 ) > "$O/llm.log" 2>&1 &
  PIDS="$PIDS $!"
}
# the model's gguf: $1 the game's wish (AG_*_MODEL), $2 the default; E4B falls back to E2B when it is not installed
pick_model() {
  TM=${1:-$2}; [ -f "$M/$TM.gguf" ] || TM=gemma-4-E2B_q4_0-it
  export AG_MODEL_LABEL=$(echo "$TM" | sed 's/^gemma-4-\([^_]*\)_.*/\1/')
}
llm_up() { curl -sf -m 2 http://127.0.0.1:8099/health >/dev/null 2>&1; }
# wait for the model with a caption every 10 s (E4B is 5 GB: a cold load from the SD card takes minutes); $1 = what
wait_llm() {
  i=0; until llm_up; do
    i=$((i+1)); [ $i -gt 600 ] && exit 1; kill -0 $RAP 2>/dev/null || exit 0
    [ $((i % 10)) = 0 ] && msg "$1 loading... ${i} s"; sleep 1
  done
  msg "$1 ready."
}

# Skill levels by slow motion (tetris-model, tennis-model, ntennis-model, excitebike-model, punchout-model). $1: a human's think seconds for Hard,
# Harder, Hardest (Expert is real time): the game runs at 1/(THINK / that), clamped 1-20. No Easy: a game slow enough
# that the model always keeps up is no contest to watch. $2, $3: the picker's title and lines. The start level:
# AG_LEVEL (0-3), else picked on the screen while the model loads (picker.py), the last pick first, Hardest at first
# (state/level_GAME.txt); AG_PICK=0 takes the last pick without asking. level.py changes it during the game (SELECT).
setup_levels() {
  awk -v t="$THINK" -v hs="$1 0" 'BEGIN { split("Hard Harder Hardest Expert", n, " "); split(hs, h, " ")
    for (i = 1; i <= 4; i++) { r = h[i] ? t / h[i] : 1; if (r < 1) r = 1; if (r > 20) r = 20; printf "%s %.1f %s\n", n[i], r, h[i] } }' > "$O/levels"
  LAST=$(cat "$ST/level_$GAME.txt" 2>/dev/null); case $LAST in [0-3]) ;; *) LAST=2 ;; esac
  echo "${AG_LEVEL:-$LAST}" > "$O/level"; export TL_RUN=$O TL_THINK0=$THINK TL_PAUSE=0 TL_MENU_TITLE="$2" TL_MENU_INFO="$3"
  if [ -z "${AG_LEVEL:-}" ] && [ "${AG_PICK:-1}" != 0 ]; then
    onscreen python3 "$V/picker.py" "$O" "$2" "$3" 2> "$O/foot.log"
    [ -f "$O/quit" ] && exit 0
    cp "$O/level" "$ST/level_$GAME.txt"
  fi
}

# Pocket TTS for the spoken lines, if installed (else captions only)
start_tts() {
  [ "${NR_TTS:-1}" != 0 ] && [ -x "$TTSB" ] && [ -f "$M/pocket-tts-english_2026-09-Q8_0.gguf" ] || { export NR_TTS=0; return; }
  env -u OMP_PROC_BIND -u OMP_PLACES GGML_BACKEND=CPU PT_THREADS=2 nice -n -10 taskset -c 6-7 "$TTSB" \
    --model "$M/pocket-tts-english_2026-09-Q8_0.gguf" --voices "$M/pocket-tts-english_2026-09-voices.gguf" \
    --voice "${AG_VOICE:-alba}" --host 127.0.0.1 --port 8093 > "$O/tts.log" 2>&1 &
  PIDS="$PIDS $!"; export TL_TTS=1
}

MODEL_GAME=""
case $GAME in
  tennis)
    pick_model "" gemma-4-E2B_q4_0-it; start_llm "$TM"; MODEL_GAME=1; start_tts ;;
  tetris-model)
    pick_model "${AG_TETRIS_MODEL:-}" gemma-4-E4B_q4_0-it; start_llm "$TM"; MODEL_GAME=1; start_tts
    export TL_CALIB="$ST/think_$AG_MODEL_LABEL.txt"
    case $AG_MODEL_LABEL in E4B) THINK=6.8 ;; E2B) THINK=3.9 ;; *) THINK=8 ;; esac   # mean s/pick, cached prompt, 2026-10-09
    [ -s "$TL_CALIB" ] && THINK=$(cat "$TL_CALIB")
    # The game starts at the fastest NES level whose piece (~15 rows, gravity table in frames a row) still falls in
    # the model's think time at real time (E4B 6.8 s: level 4, 7.0 s); the levels give it 2, 1.5, 1.2 and 1 times
    # that. At level 0 (12 s a piece) E4B kept up even slowed only 1/1.4.
    set -- $(awk -v t="$THINK" -v l="${AG_TL_GAMELEVEL:-}" 'BEGIN { split("48 43 38 33 28 23 18 13 8 6", g, " ")
      if (l == "") { l = 0; for (i = 1; i <= 10; i++) if (g[i] * 15 / 60 >= t) l = i - 1 }
      d = g[l + 1] * 15 / 60; printf "%d %.1f %.2g %.2g %.2g\n", l, d, d / 2, d / 1.5, d / 1.2 }')
    export TL_GAMELEVEL=$1
    setup_levels "$3 $4 $5" "AI PLAYS TETRIS (MODEL DECIDES)" \
      "$AG_MODEL_LABEL takes about $THINK s to place a piece. The game starts|at level $1, where a piece falls in about $2 s: Expert is the edge.|Every 10 lines the game speeds up." ;;
  tennis-model)
    pick_model "${AG_TENNIS_MODEL:-}" gemma-4-E2B_q4_0-it; start_llm "$TM"; MODEL_GAME=1; start_tts
    export TL_CALIB="$ST/think_tennis_$AG_MODEL_LABEL.txt" TN_WCALIB="$ST/window_tennis.txt"
    case $AG_MODEL_LABEL in E4B) THINK=4.4 ;; *) THINK=2.5 ;; esac    # mean s/aim, cached prompt, 2026-10-09
    [ -s "$TL_CALIB" ] && THINK=$(cat "$TL_CALIB")
    W=0.8; [ -s "$TN_WCALIB" ] && W=$(cat "$TN_WCALIB")      # game seconds from blue's hit to ours (~36 returns a minute)
    # a human's W/1.2 .. W/0.85 s: Hard answers most shots, Harder about half, Hardest few (blue's shots leave 0.63-1.13
    # s). Unanswered shots are missed (tennis_llm.py), so Expert loses every point.
    setup_levels "$(awk -v w="$W" 'BEGIN { printf "%.2g %.2g %.2g", w / 1.2, w, w / 0.85 }')" "AI PLAYS TENNIS (MODEL AIMS)" \
      "$AG_MODEL_LABEL takes about $THINK s to pick where a return goes.|A shot from blue leaves about $W s to answer;|no answer in time, no shot: blue wins the point." ;;
  ntennis-model)
    pick_model "${AG_NTENNIS_MODEL:-}" gemma-4-E4B_q4_0-it; start_llm "$TM"; MODEL_GAME=1; start_tts
    export TL_CALIB="$ST/think_ntennis_$AG_MODEL_LABEL.txt" TN_WCALIB="$ST/window_ntennis.txt"
    case $AG_MODEL_LABEL in E4B) THINK=2.2 ;; *) THINK=1.5 ;; esac    # E4B 1.9-2.2 s a pick on car12, 2026-10-10; E2B a guess
    [ -s "$TL_CALIB" ] && THINK=$(cat "$TL_CALIB")
    W=1.7; [ -s "$TN_WCALIB" ] && W=$(cat "$TN_WCALIB")      # game seconds from the computer's hit to ours (1.7 at its level 1, 1.1 at 3)
    export NT_CPU=${AG_NT_CPU:-1}                              # the game's own computer level, 1-5
    setup_levels "$(awk -v w="$W" 'BEGIN { printf "%.2g %.2g %.2g", w / 1.2, w, w / 0.85 }')" "AI PLAYS NES TENNIS (MODEL AIMS EVERY RETURN)" \
      "$AG_MODEL_LABEL takes about $THINK s to choose where a return goes.|A shot from the computer leaves about $W s to answer;|no answer in time: it hits on impulse, away from the computer." ;;
  excitebike-model)
    pick_model "${AG_EXCITEBIKE_MODEL:-}" gemma-4-E4B_q4_0-it; start_llm "$TM"; MODEL_GAME=1; start_tts
    export TL_CALIB="$ST/think_excitebike_$AG_MODEL_LABEL.txt" EB_TRACK=${AG_EB_TRACK:-1}
    case $AG_MODEL_LABEL in E4B) THINK=3.7 ;; *) THINK=2.5 ;; esac  # E4B measured 3.4-4.0 s a call on car12, 2026-10-09; E2B a guess
    [ -s "$TL_CALIB" ] && THINK=$(cat "$TL_CALIB")
    # Each call holds until the next, so the game seconds between calls set how finely it can run the turbo (heats 3.5
    # a second, overheats at 32, cruising cools to 17): headless runs with a sensible caller qualified on track 3 with a
    # call every 1-1.5 s, overheated and missed it at 2.5-3.5 s, and were too cautious to qualify at 5 s or more.
    setup_levels "1 2 3" "AI PLAYS EXCITEBIKE (MODEL RIDES THE TURBO)" \
      "$AG_MODEL_LABEL takes about $THINK s to call turbo or cruise; each call|holds until the next. Too slow to ease off, the engine overheats;|too careful, it misses the qualifying time: game over." ;;
  punchout-model)
    pick_model "${AG_PUNCHOUT_MODEL:-}" gemma-4-E4B_q4_0-it; start_llm "$TM"; MODEL_GAME=1; start_tts
    export TL_CALIB="$ST/think_punchout_$AG_MODEL_LABEL.txt" AG_BULLET=1
    case $AG_MODEL_LABEL in E4B) THINK=4.0 ;; *) THINK=2.7 ;; esac  # Excitebike's call times + a longer question: estimates
    [ -s "$TL_CALIB" ] && THINK=$(cat "$TL_CALIB")
    # After a dodge Glass Joe stays open for a pummel 100 frames on (5-6 hits); later opponents close up sooner. A
    # human's 0.5, 0.75, 1 s to see the opening and call it.
    setup_levels "0.5 0.75 1" "AI PLAYS PUNCH-OUT!! (MODEL RUNS THE OFFENCE)" \
      "Mac dodges by himself. $AG_MODEL_LABEL takes about $THINK s to call|pummel, body blows or wait when the opponent is open;|the game slows down for each call. Too late: the opening is gone." ;;
  contra-coop)
    pick_model "${AG_CONTRA_MODEL:-}" gemma-4-E4B_q4_0-it; start_llm "$TM"; MODEL_GAME=1; start_tts
    export TL_CALIB="$ST/think_contra_$AG_MODEL_LABEL.txt" AG_CT_KONAMI=${AG_CT_KONAMI:-0} AG_CT_STANDIN=${AG_CT_STANDIN:-0} \
      AG_CT_RECORD="$ST/contra_record.json"   # what the model learns across games
    case $AG_MODEL_LABEL in E4B) THINK=4.5 ;; *) THINK=3 ;; esac   # Punch-Out!!'s call times + a longer question: estimates
    [ -s "$TL_CALIB" ] && THINK=$(cat "$TL_CALIB"); export TL_THINK0=$THINK ;;
esac

# The panel at 60 Hz for the session (the Flip 2 runs 120): with autogamer-60hz.cfg RetroArch paces by vsync, not by
# PulseAudio's 20 ms period. Put back on exit. AG_60HZ=0 keeps the panel as it is (and RetroArch's own pacing).
OUT=$(wlr-randr 2>/dev/null | awk 'NR==1 {print $1}'); MODE0=$(wlr-randr 2>/dev/null | awk '/current/ {print $1"@"$3; exit}')
PACE=""
if [ "${AG_60HZ:-1}" != 0 ] && [ -n "$OUT" ] && [ -n "$MODE0" ]; then
  case $MODE0 in
    *@60.0*) PACE="|$V/autogamer-60hz.cfg" ;;
    *) if wlr-randr --output "$OUT" --mode "${MODE0%@*}@60.000000" 2>/dev/null; then
         PACE="|$V/autogamer-60hz.cfg"; RESTORE_MODE="$MODE0"
       fi ;;
  esac
fi

# The level's settings for this RetroArch start: its own save-state folder and slot for the restarts, and slow
# motion, which RetroArch paces by blocking audio, so audio_sync goes back on (autogamer-60hz.cfg turns it off)
level_cfg() {
  [ -f "$O/levels" ] || return 0
  set -- $(awk -v i="$(cat "$O/level")" 'NR == i + 1' "$O/levels")
  mkdir -p "$O/states"     # RetroArch ignores a savestate_directory that does not exist (and saves to its own)
  { echo "savestate_directory = \"$O/states\""; echo 'state_slot = "0"'
    [ "$2" != 1.0 ] && printf 'audio_sync = "true"\nslowmotion_ratio = "%s"\n' "$2"; } > "$O/slow.cfg"
  SLOW="|$O/slow.cfg"; LVL=" $(echo "$1" | tr a-z A-Z) $([ "$2" = 1.0 ] && echo "real time" || echo "1/$2")"
}

# RetroArch, as runemu.sh starts it, plus autogamer.cfg (and the level's settings); again after a level change
EXTRA=$(/usr/bin/setsettings.sh "$SYS" "$ROM" "$CORE" --controllers="" --autosave="" --snapshot="" 2>/dev/null)
[ "$EXTRA" = 0 ] && EXTRA=""
sleep 0.5      # setsettings finishes its autosave lines in the background
RUN0="/usr/bin/retroarch"
RA_CPUS=${AG_RA_CPUS-0-3}; [ -n "$RA_CPUS" ] && RUN0="taskset -c $RA_CPUS $RUN0"
msg() { python3 "$V/ra.py" "SHOW_MSG $*" >/dev/null 2>&1; }
start_ra() {
  level_cfg; RUN=$RUN0
  if [ "${AG_HUD:-1}" != 0 ] && [ -x /usr/bin/mangohud ]; then
    LABEL="AUTOGAMER $(echo $GAME | tr a-z- A-Z\ )"; NOMODEL='/^exec=/d'
    [ -n "$MODEL_GAME" ] && { LABEL="$AG_MODEL_LABEL${LVL:-}"; NOMODEL=""; }
    sed -e "s|@LABEL@|$LABEL|" ${NOMODEL:+-e "$NOMODEL"} "$V/mangohud.conf" > "$O/mangohud.conf"
    export MANGOHUD_CONFIGFILE="$O/mangohud.conf"; RUN="/usr/bin/mangohud $RUN"
  fi
  $RUN -L /tmp/cores/${CORE}_libretro.so $EXTRA --config /storage/.config/retroarch/retroarch.cfg \
    --appendconfig "/tmp/.retroarch.cfg|$V/autogamer.cfg$PACE${SLOW:-}${AG_RA_CFG:+|$AG_RA_CFG}" "$ROM" >> "$O/retroarch.log" 2>&1 &
  RAP=$!; PIDS="$PIDS $RAP"
  i=0; until python3 "$V/ra.py" GET_STATUS 2>/dev/null | grep -q "PLAYING\|PAUSED"; do
    i=$((i+1)); kill -0 $RAP 2>/dev/null || exit 1; [ $i -gt 60 ] && fail "RetroArch did not answer on UDP 55355."; sleep 0.5
  done
  RA_PID=$(pidof retroarch | awk '{print $1}')      # the mangohud wrapper execs, so this is RetroArch itself
  python3 "$V/home.py" "${RA_PID:-$RAP}" > "$O/home.out" 2>&1 &
  PIDS="$PIDS $!"
}
start_ra

# A model game waits, paused, until its model is loaded (the players unpause RetroArch when they start)
if [ -n "$MODEL_GAME" ]; then
  python3 "$V/ra.py" GET_STATUS | grep -q PLAYING && python3 "$V/ra.py" PAUSE_TOGGLE >/dev/null
  echo "loading the model" > /dev/shm/autogamer/hud.txt
  case $GAME in
    tennis) msg "The AI is pink. The commentator ($AG_MODEL_LABEL) is loading; the match starts when it is ready." ;;
    tetris-model) msg "The model ($AG_MODEL_LABEL) is loading. It thinks ${TL_THINK0} s a piece; SELECT changes the level (game speed)." ;;
    tennis-model) msg "The AI is pink. The model ($AG_MODEL_LABEL) is loading; it will aim every return. SELECT changes the level (game speed)." ;;
    ntennis-model) msg "The model ($AG_MODEL_LABEL) is loading; it will aim every return. SELECT changes the level (game speed)." ;;
    excitebike-model) msg "The model ($AG_MODEL_LABEL) is loading; it will run the engine. SELECT changes the level (game speed)." ;;
    punchout-model) msg "The model ($AG_MODEL_LABEL) is loading; it will call the attacks. SELECT changes the level." ;;
    contra-coop) msg "The model ($AG_MODEL_LABEL) is loading; it will be Player 2. You are Player 1: hands off until the game picks 2 PLAYER." ;;
  esac
  wait_llm "The model ($AG_MODEL_LABEL)"
  echo "ready" > /dev/shm/autogamer/hud.txt
fi

P="taskset -c 0-3 python3 -u"; FOREVER=864000
case $GAME in
  tennis)
    $P "$V/play.py" $FOREVER aim -9 > "$O/play.out" 2>&1 &
    PIDS="$PIDS $!"
    $P "$V/narrate.py" $FOREVER "$O" > "$O/narrate.out" 2>&1 &
    PIDS="$PIDS $!" ;;
  ntennis-model)
    $P "$V/ntennis_llm.py" $FOREVER "$O/shots.jsonl" > "$O/play.out" 2>&1 &
    PIDS="$PIDS $!"
    python3 -u "$V/level.py" "$O" > "$O/level.out" 2>&1 & PIDS="$PIDS $!" ;;
  excitebike-model)
    $P "$V/excitebike_llm.py" $FOREVER "$O/race.jsonl" > "$O/play.out" 2>&1 &
    PIDS="$PIDS $!"
    python3 -u "$V/level.py" "$O" > "$O/level.out" 2>&1 & PIDS="$PIDS $!" ;;
  punchout-model)
    $P "$V/punchout_llm.py" $FOREVER "$O/fight.jsonl" > "$O/play.out" 2>&1 &
    PIDS="$PIDS $!"
    python3 -u "$V/level.py" "$O" > "$O/level.out" 2>&1 & PIDS="$PIDS $!" ;;
  contra-coop)
    $P "$V/contra_llm.py" $FOREVER "$O/coop.jsonl" > "$O/play.out" 2>&1 &
    PIDS="$PIDS $!" ;;
  tennis-model)
    $P "$V/tennis_llm.py" $FOREVER "$O/shots.jsonl" > "$O/play.out" 2>&1 &
    PIDS="$PIDS $!"
    python3 -u "$V/level.py" "$O" > "$O/level.out" 2>&1 & PIDS="$PIDS $!" ;;
  tetris)
    $P "$V/tetris.py" $FOREVER "$O/tetris.jsonl" > "$O/play.out" 2>&1 &
    PIDS="$PIDS $!" ;;
  tetris-model)
    $P "$V/tetris_llm.py" $FOREVER "$O/moves.jsonl" > "$O/play.out" 2>&1 &
    PIDS="$PIDS $!"
    python3 -u "$V/level.py" "$O" > "$O/level.out" 2>&1 & PIDS="$PIDS $!" ;;
  smb)
    $P "$V/smb.py" $FOREVER "$O/smb.jsonl" > "$O/play.out" 2>&1 &
    PIDS="$PIDS $!" ;;
esac

# RetroArch ends: HOME or its own quit (the end), or level.py after SELECT (RUN/restart: start again, load the state)
while :; do
  wait $RAP
  [ -f "$O/restart" ] || break
  start_ra
  python3 "$V/ra.py" LOAD_STATE_SLOT 0 >/dev/null; sleep 1
  rm -f "$O/restart"       # the players wait while it is there (the title screen before the load is not a game over)
done
