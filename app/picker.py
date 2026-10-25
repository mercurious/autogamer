#!/usr/bin/env python3
# Runs on the handheld in a fullscreen foot window (run.sh, before RetroArch starts): the player picks the skill level
# the game starts at, so the wanted level loads first instead of SELECT restarts. RUN/levels ("NAME RATIO HUMAN_S" a
# line, from run.sh) and RUN/level (the highlighted start, the last pick); writes the pick to RUN/level. D-pad or left
# stick up/down moves, A, B or START plays, HOME writes RUN/quit (run.sh then ends). With no input for TIMEOUT s the
# highlighted level starts. Shows the model loading meanwhile (llama-server /health, and hud.py's load bar in
# /dev/shm/autogamer/hud.txt): the load is what we wait for anyway.
# Drawn like the game menu (cabinet.py): the levels on the left, the game and INFO under them; the highlighted level
# lit card yellow, running into its card: the level in pixel letters, the game's speed and the model's think time, a
# speed bar, the model's think time against a human's (TL_THINK0, from run.sh), and at the card's foot the model and the countdown in pixel digits. The game is RUN's name (run.sh's
# logs/GAME), else TITLE.
# Usage: picker.py RUN TITLE INFO [TIMEOUT] [resume]     INFO: lines above the list, split at |. The loading line names
#   AG_MODEL_LABEL. resume: the in-game menu (level.py, SELECT): SELECT again or the timeout keeps the level.
#   AG_BULLET=1 (Punch-Out!!): the slow motion is bullet time, for each call. Reads only; never grabs the pad.
import os, re, select, struct, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from home import pads, EV_KEY, BTN_MODE
from cabinet import INK, CARD, P1, P2, PAPER, DIM, KEY, CARDRULE, DOT, Grid, wrap, bigwidth, header, show, start, end
import games
EV_ABS, ABS_Y, ABS_HAT0Y = 3, 1, 17
BTN_SOUTH, BTN_EAST, BTN_START = 304, 305, 315
RUN, TITLE, INFO = sys.argv[1], sys.argv[2], sys.argv[3].split("|"); MODEL = os.environ.get("AG_MODEL_LABEL", "The model"); TIMEOUT = float(sys.argv[4]) if len(sys.argv) > 4 else 30
RESUME = len(sys.argv) > 5 and sys.argv[5] == "resume"; BTN_SELECT = 314
BULLET = os.environ.get("AG_BULLET") == "1"
try: THINK = float(os.environ.get("TL_THINK0", ""))      # the model's think time, s (run.sh)
except ValueError: THINK = None
GAME = games.BY_ID.get(os.path.basename(os.path.normpath(RUN)))
LV = [l.split() for l in open(os.path.join(RUN, "levels")) if l.strip()]
try: cur = min(max(int(open(os.path.join(RUN, "level")).read()), 0), len(LV) - 1)
except (OSError, ValueError): cur = 0
start_lv = cur

def health():
    try: return urllib.request.urlopen("http://127.0.0.1:%s/health" % os.environ.get("VS_PORT", "8099"), timeout=0.3).status == 200
    except Exception: return False

def loaded():
    """the model's load, 0-1, from hud.py's bar (None when it is not loading)"""
    try: m = re.match(r"loading .*?(\d+)%", open("/dev/shm/autogamer/hud.txt").read())
    except OSError: return None
    return int(m.group(1)) / 100 if m else None

def bar(sc, x, y, w, frac, fg, track):
    k = int(round(max(0.0, min(frac, 1.0)) * w)); sc.fill(x, y, k, 1, fg); sc.fill(x + k, y, w - k, 1, CARD, "─", track)

def draw(left, t_load, ready):
    sc = Grid(); w, h = sc.w, sc.h; L, LW = 4, min(56, w // 2 - 4); CX = L + LW
    header(sc, "PAUSED" if RESUME else "")
    y = 6
    sc.put(L, y, "LEVEL", DIM, bold=True); sc.rule(L + 6, y, LW - 9); y += 1
    for i, (name, r, hs) in enumerate(LV):
        on = i == cur; fg = INK if on else PAPER
        if on: sc.fill(L, y, LW, 1, CARD)
        sc.put(L + 4, y, name, fg, bold=on)
        sc.put(L + 14, y, "real time" if float(r) <= 1 else "1/%s speed" % r, fg if on else "#c9c1b3")
        sc.put(L + 30, y, "no help" if hs == "0" else "a human's %s s" % hs, fg if on else "#c9c1b3")
        if RESUME and i == start_lv: sc.right(L + LW - 2, y, "playing", INK if on else DIM)
        y += 1
    y += 2                                                  # the game, and what the level means in it
    if GAME:
        name, job = GAME["title"].split(": ", 1)
        sc.put(L, y, name.upper(), PAPER, bold=True); sc.put(L + len(name) + 2, y, job, DIM); y += 2
    else: sc.put(L, y, TITLE, PAPER, bold=True); y += 2
    for l in wrap(" ".join(s.strip() for s in INFO), LW - 2)[:h - 4 - y]: sc.put(L, y, l, PAPER); y += 1
    # the card: the highlighted level
    x0, x1, y0, y1 = CX, w - 4, 6, h - 3
    sc.fill(x0, y0, x1 - x0, y1 - y0, CARD); x, cw = x0 + 3, x1 - x0 - 6
    name, r, hs = LV[cur]; r = float(r)
    sc.big(x, y0 + 2, name.upper(), INK)
    if r <= 1:
        sc.put(x, y0 + 6, "THE GAME RUNS IN REAL TIME", INK, bold=True)
        sc.put(x, y0 + 7, "No help: the model has to keep up."[:cw], INK)
    elif BULLET:
        sc.put(x, y0 + 6, "BULLET TIME AT 1/%.1f FOR EACH CALL" % r, INK, bold=True)
        sc.put(x, y0 + 7, ("The model gets a human's %s s to decide." % hs)[:cw], INK)
    else:
        sc.put(x, y0 + 6, "THE GAME RUNS AT 1/%.1f SPEED" % r, INK, bold=True)
        sc.put(x, y0 + 7, ("The model gets a human's %s s to think." % hs)[:cw], INK)
    sc.put(x, y0 + 9, "GAME SPEED", INK, bold=True); sc.right(x + cw, y0 + 9, "%d%%" % round(100 / max(r, 1)), INK)
    bar(sc, x, y0 + 10, cw, 1 / max(r, 1), INK, CARDRULE)
    if THINK and float(hs) > 0:                             # the contest: what the model needs, what a human gets
        top, bw = max(THINK, float(hs)), cw - 27
        for k, (lab, t, col) in enumerate([("THE MODEL", THINK, P2), ("A HUMAN", float(hs), P1)]):
            sc.put(x, y0 + 12 + 2 * k, lab, INK, bold=True); sc.fill(x + 11, y0 + 12 + 2 * k, max(1, round(bw * t / top)), 1, col)
            sc.right(x + cw, y0 + 12 + 2 * k, ("thinks %.1f s" if k == 0 else "gets %s s") % (t if k == 0 else hs), INK)
        sc.put(x, y0 + 16, "The slow motion makes up the difference." if THINK > float(hs) else "No slow motion needed.", INK)
    fy = y1 - 6                                             # the foot: the model, and the countdown in big digits
    sc.rule(x, fy - 1, cw, CARD, CARDRULE)
    secs = "%d" % max(left, 0); sc.right(x + cw, fy - 1, " BACK IN" if RESUME else " STARTS IN", INK, CARD, True)
    sc.big(x + cw - 2 * bigwidth(secs), fy, secs, INK, scale=2)
    if RESUME: sc.put(x, fy + 1, "Game paused.", INK, bold=True)
    else:
        frac = 1.0 if ready else loaded()
        st = "ok" if ready else "unsure"
        sc.put(x, fy + 1, DOT[st][0], DOT[st][2]); sc.put(x + 2, fy + 1, "MODEL", INK, bold=True)
        sc.put(x + 9, fy + 1, "%s ready" % MODEL if ready else "%s loading, %.0f s" % (MODEL, time.time() - t_load), INK)
        if frac is not None: bar(sc, x + 9, fy + 3, cw - 9 - 18, frac, INK, CARDRULE)
    keys = [("A", P1, "PLAY"), ("↑↓", KEY, "LEVEL")] + ([("SELECT", KEY, "BACK")] if RESUME else []) + [("HOME", P2, "QUIT")]
    sc.caps(L, h - 2, keys)
    if not RESUME: sc.right(w - 4, h - 2, "In the game, SELECT pauses it and shows this menu.", DIM)
    return sc.ansi()

if __name__ == "__main__":
    fds, seen, t_in, t_load, stick, ready, done, frame = {}, 0, time.time(), time.time(), 0, False, None, None
    start()
    while done is None:
        if time.time() - seen > 2:                       # InputPlumber may (re)create the node during the launch
            for p in pads():
                if p not in fds.values():
                    try: fds[os.open(p, os.O_RDONLY | os.O_NONBLOCK)] = p
                    except OSError: pass
            seen = time.time(); ready = ready or health()
        left = TIMEOUT - (time.time() - t_in)
        if left <= 0: done = "timeout"; cur = start_lv if RESUME else cur; break
        frame = show(draw(left, t_load, ready), frame)
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
                    elif code == BTN_SELECT and RESUME: cur = start_lv; done = "back"
                elif typ == EV_ABS and code == ABS_HAT0Y and val: move = val
                elif typ == EV_ABS and code == ABS_Y:    # DualSense stick 0-255, centre 128: once per push
                    s = -1 if val < 48 else 1 if val > 208 else 0
                    if s and not stick: move = s
                    stick = s
                if move: cur = (cur + move) % len(LV)
                if move or done: t_in = time.time()
    end()
    if done == "quit": open(os.path.join(RUN, "quit"), "w").close()
    else: open(os.path.join(RUN, "level"), "w").write("%d\n" % cur)
    open(os.path.join(RUN, "picker.out"), "a").write("%.1f %s %s\n" % (time.time(), done, LV[cur][0]))
