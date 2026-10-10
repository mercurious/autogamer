#!/bin/sh
# Autogamer (the ROCKNIX Port): the game menu (menu.py, full screen in foot), then the game (run.sh); when the game
# ends (HOME), the menu again; HOME in the menu returns to EmulationStation.
# Env: everything run.sh takes (AG_MODELS, AG_ROMS, ...). AG_GAME=<id> plays that game once, without the menu.
[ -f /etc/profile ] && . /etc/profile >/dev/null 2>&1
V=$(cd "$(dirname "$0")" && pwd); H=$(dirname "$V"); ST=$H/state
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/0-runtime-dir} WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-wayland-1} HOME=${HOME:-/storage}
SWAYSOCK=$(ls "$XDG_RUNTIME_DIR"/sway-ipc.*.sock 2>/dev/null | head -1); export SWAYSOCK
M=${AG_MODELS:-$("$H/llamatalk/models.sh" path 2>/dev/null)}; export AG_MODELS=${M:-$H/models}
mkdir -p "$ST" "$H/logs"
[ -n "${AG_GAME:-}" ] && exec sh "$V/run.sh" "$AG_GAME"
while :; do
  rm -f "$ST/menu.out"
  ( for i in 1 2 3 4 5 6; do sleep 0.5; swaymsg '[app_id="autogamer"] fullscreen enable' >/dev/null 2>&1 && break; done ) &
  foot --app-id=autogamer -f "monospace:size=20" -o colors.background=030a03 -o colors.foreground=33ff66 \
    python3 "$V/menu.py" "$ST/menu.out" "$ST" 2> "$H/logs/menu.log"
  G=$(cat "$ST/menu.out" 2>/dev/null)
  case $G in ""|quit) exit 0 ;; esac
  sh "$V/run.sh" "$G" 2> "$H/logs/run.log"
done
