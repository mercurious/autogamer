#!/usr/bin/env python3
# Runs on the handheld in a fullscreen foot window (run.sh, before RetroArch starts): the player picks the skill level
# the game starts at, so the wanted level loads first instead of SELECT restarts. RUN/levels ("NAME RATIO HUMAN_S" a
# line, from run.sh) and RUN/level (the highlighted start, the last pick); writes the pick to RUN/level. D-pad or left
# stick up/down moves, A, B or START plays, HOME writes RUN/quit (run.sh then ends). With no input for TIMEOUT s the
# highlighted level starts. Shows the model loading (llama-server /health) meanwhile: the load is what we wait for anyway.
# Usage: picker.py RUN TITLE INFO [TIMEOUT] [resume]     INFO: lines above the list, split at |. The loading line names
#   AG_MODEL_LABEL. resume: the in-game menu (level.py, SELECT): SELECT again or the timeout keeps the level.
#   Reads only; never grabs the pad.
import os, select, shutil, struct, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from home import pads, EV_KEY, BTN_MODE
EV_ABS, ABS_Y, ABS_HAT0Y = 3, 1, 17
BTN_SOUTH, BTN_EAST, BTN_START = 304, 305, 315
RUN, TITLE, INFO = sys.argv[1], sys.argv[2], sys.argv[3].split("|"); MODEL = os.environ.get("AG_MODEL_LABEL", "The model"); TIMEOUT = float(sys.argv[4]) if len(sys.argv) > 4 else 30
RESUME = len(sys.argv) > 5 and sys.argv[5] == "resume"; BTN_SELECT = 314
LV = [l.split() for l in open(os.path.join(RUN, "levels")) if l.strip()]
try: cur = min(max(int(open(os.path.join(RUN, "level")).read()), 0), len(LV) - 1)
except (OSError, ValueError): cur = 0
start = cur

def health():
    try: return urllib.request.urlopen("http://127.0.0.1:%s/health" % os.environ.get("VS_PORT", "8099"), timeout=0.3).status == 200
    except Exception: return False

def draw(left, t_load, ready):
    w, h = shutil.get_terminal_size((60, 20))
    out = [TITLE, ""] + INFO + [""]
    for i, (name, r, hs) in enumerate(LV):
        speed = "real time" if float(r) <= 1 else "1/%s speed" % r
        why = "no help" if hs == "0" else "a human's %s s" % hs
        out.append("%s %-8s %-14s %s" % (">" if i == cur else " ", name, speed, why))
    if RESUME: out += ["", "Up/down: level   A or START: play   SELECT: back   HOME: quit", "", "Paused. Back in %.0f s" % left]
    else: out += ["", "Up/down: level   A or START: play   HOME: quit",
                  "SELECT in the game pauses it and shows this menu.", "",
                  "%s ready." % MODEL if ready else "%s loading... %.0f s" % (MODEL, time.time() - t_load),
                  "Starts in %.0f s" % left]
    width = max(len(l) for l in out); pad = " " * max((w - width) // 2, 0)
    top = "\n" * max((h - len(out)) // 2, 0)
    sys.stdout.write("\033[H\033[2J\033[?25l" + top + "\n".join(pad + l for l in out)); sys.stdout.flush()

if __name__ == "__main__":
    fds, seen, t_in, t_load, stick, ready, done = {}, 0, time.time(), time.time(), 0, False, None
    while done is None:
        if time.time() - seen > 2:                       # InputPlumber may (re)create the node during the launch
            for p in pads():
                if p not in fds.values():
                    try: fds[os.open(p, os.O_RDONLY | os.O_NONBLOCK)] = p
                    except OSError: pass
            seen = time.time(); ready = ready or health()
        left = TIMEOUT - (time.time() - t_in)
        if left <= 0: done = "timeout"; cur = start if RESUME else cur; break
        draw(left, t_load, ready)
        r, _, _ = select.select(list(fds), [], [], 0.25)
        for fd in r:
            try: data = os.read(fd, 24 * 64)
            except OSError: os.close(fd); fds.pop(fd, None); continue
            for k in range(0, len(data) - 23, 24):
                _, _, typ, code, val = struct.unpack("qqHHi", data[k:k + 24])
                move = 0
                if typ == EV_KEY and val == 1:
                    if code in (BTN_SOUTH, BTN_EAST, BTN_START): done = "picked"
                    elif code == BTN_MODE: done = "quit"
                    elif code == BTN_SELECT and RESUME: cur = start; done = "back"
                elif typ == EV_ABS and code == ABS_HAT0Y and val: move = val
                elif typ == EV_ABS and code == ABS_Y:    # DualSense stick 0-255, centre 128: once per push
                    s = -1 if val < 48 else 1 if val > 208 else 0
                    if s and not stick: move = s
                    stick = s
                if move: cur = (cur + move) % len(LV)
                if move or done: t_in = time.time()
    sys.stdout.write("\033[?25h"); sys.stdout.flush()
    if done == "quit": open(os.path.join(RUN, "quit"), "w").close()
    else: open(os.path.join(RUN, "level"), "w").write("%d\n" % cur)
    open(os.path.join(RUN, "picker.out"), "a").write("%.1f %s %s\n" % (time.time(), done, LV[cur][0]))
