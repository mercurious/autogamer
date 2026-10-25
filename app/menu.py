#!/usr/bin/env python3
# Runs on the handheld in a fullscreen foot window (autogamer.sh): the game menu, drawn as an arcade cabinet's
# instruction card. Left, the games (main, then bonus): a status dot, the name, what the model does, the system. The
# highlighted row is lit card yellow and runs into the card on the right: what the model does in pixel letters, who
# plays (1P/2P caps: red is you, blue the model), the game's about text, the orders it takes (hold R1), and at the foot
# its ROM (or which one to add), model and voice. D-pad or left stick up/down moves, A, B or START plays (a game without
# its ROM or model only says what is missing), HOME quits. SELECT turns the HUD bar (MangoHud, run.sh) on or off for
# the games after: STATE/hud says "off", on by default; in a game SELECT is the game's (and the level menu's), so the
# HUD is set here, between games. Left alone for IDLE s it plays attract mode: the cards cycle until a button (which
# only wakes it).
# Writes the game's id, or "quit", to OUT; the last game played is highlighted (STATE/last_game).
# Usage: menu.py OUT STATE      env: AG_MODELS (the models directory), AG_ROMS
#   Reads only; never grabs the pad. The look is cabinet.py's.
import os, select, struct, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from home import pads, EV_KEY, BTN_MODE
from cabinet import INK, CARD, P1, P2, PAPER, DIM, KEY, CARDRULE, DOT, Grid, wrap, bigwrap, header, show, start, end
import games
EV_ABS, ABS_Y, ABS_HAT0Y = 3, 1, 17
BTN_SOUTH, BTN_EAST, BTN_START, BTN_SELECT = 304, 305, 315, 314
OUT, STATE = sys.argv[1], sys.argv[2]
M = os.environ.get("AG_MODELS", "")
GGUF = {"e2b": "gemma-4-E2B_q4_0-it.gguf", "e4b": "gemma-4-E4B_q4_0-it.gguf"}
TTS = "pocket-tts-english_2026-09-Q8_0.gguf"
IDLE, ATTRACT_STEP = 30, 6
SYS = {"nes": "NES", "atari2600": "2600", "genesis": "GEN"}

WHO = {"you": P1, "model": P2}

def have(f): return bool(M) and os.path.isfile(os.path.join(M, f))

def model_status(g):
    """(state, text, playable) for the game's model: the bigger one falls back to E2B, as run.sh does"""
    if not g["model"]: return "none", "none needed", True
    if g["model"] == "e4b" and have(GGUF["e4b"]): return "ok", "Gemma 4 E4B", True
    if have(GGUF["e2b"]):
        return ("unsure", "Gemma 4 E2B (E4B is not installed)", True) if g["model"] == "e4b" else ("ok", "Gemma 4 E2B", True)
    return "miss", "missing: run install.sh", False

ROWS = []
for g in games.GAMES:
    path, ok = games.find(g)
    name, job = g["title"].split(": ", 1)
    rom = (("ok", os.path.basename(path)) if ok else
           ("unsure", "%s (not the version it was made for: it may misread the game)" % os.path.basename(path)) if path
           else ("miss", games.need(g) + "."))
    ms, mt, mok = model_status(g)
    voice = (("ok", "Pocket TTS") if have(TTS) else ("miss", "not installed: no voice")) if g["tts"] else None
    ROWS.append(dict(g=g, name=name.replace(" (Atari 2600)", ""), job=job, rom=rom, model=(ms, mt), voice=voice,
                     ok=bool(path) and mok))
try: last = open(os.path.join(STATE, "last_game")).read().strip()
except OSError: last = ""
cur = next((i for i, r in enumerate(ROWS) if r["g"]["id"] == last), 0)
note = ""
HUD = os.path.join(STATE, "hud"); MANGO = os.access("/usr/bin/mangohud", os.X_OK)
def hud_on():
    try: return open(HUD).read().strip() != "off"
    except OSError: return True

def card(sc, r, x0, y0, x1, y1):
    """the instruction card for row r: one flat yellow field from (x0, y0) to (x1, y1), exclusive"""
    sc.fill(x0, y0, x1 - x0, y1 - y0, CARD)
    g, x, w = r["g"], x0 + 3, x1 - x0 - 6
    foot = [("ROM",) + r["rom"], ("MODEL",) + r["model"]] + ([("VOICE",) + r["voice"]] if r["voice"] else [])
    flines = [(lab if k == 0 else "", st if k == 0 else None, t) for lab, st, txt in foot
              for k, t in enumerate(wrap(txt, w - 24 if lab == "ROM" and st == "ok" else w - 9))]
    ftop = y1 - 1 - len(flines)                            # the status block sits on the card's foot
    body = []                                              # (kind, payload), top down
    head = bigwrap(r["job"].upper(), w)
    if len(head) <= 3: body += [("big", l) for l in head]
    else: body += [("bold", l) for l in wrap(r["job"].upper(), w)]
    body.append(("gap", ""))
    body += [("who", p) for p in g.get("players", ())]
    about = [("text", l) for l in wrap(" ".join(g["about"]), w)]
    say, line = [], "HOLD R1:"                             # some of its orders, whole quotes only
    for o in g.get("say", ()):
        q = '"%s"' % o
        if len(line) + 2 + len(q) > w: say.append(("say", line)); line = " " * 8
        line += "  " + q
    if g.get("say"): say.append(("say", line))
    room = ftop - 2 - (y0 + 2) - sum(3 if k == "big" else 1 for k, _ in body)
    if say and 1 + len(about) + 1 + len(say) > room: say = say[:1]       # one line of orders, then fewer about lines
    if say and 1 + len(about) + 1 + len(say) > room: say = []
    body += [("gap", "")] + about[:max(room - 1 - (len(say) + 1 if say else 0), 0)]
    if say: body += [("gap", "")] + say
    y = y0 + 2
    for kind, v in body:
        if kind == "big": sc.big(x, y, v, INK); y += 3
        elif kind == "bold": sc.put(x, y, v, INK, bold=True); y += 1
        elif kind == "who":
            slot, who, what = v; col = WHO.get(who)
            if slot: sc.fill(x, y, 4, 1, col or INK); sc.put(x + (4 - len(slot) + 1) // 2, y, slot, "#ffffff" if col else CARD, bold=True)
            sc.put(x + 6, y, who.upper(), INK, bold=True); sc.put(x + 15, y, what, INK); y += 1
        elif kind == "say": sc.put(x, y, v, INK); sc.put(x, y, v[:8], INK, bold=True); y += 1
        elif kind == "text": sc.put(x, y, v, INK); y += 1
        else: y += 1
    sc.rule(x, ftop - 1, w, CARD, CARDRULE)
    for k, (lab, st, t) in enumerate(flines):
        if st: sc.put(x, ftop + k, DOT[st][0], DOT[st][2]); sc.put(x + 2, ftop + k, lab, INK, bold=True)
        sc.put(x + 9, ftop + k, t, INK)
    if r["rom"][0] == "ok":                                # the game's name and system, right of a short status block
        sc.right(x + w, ftop, r["name"].upper(), INK, bold=True)
        sc.right(x + w, ftop + 1, games.SYSNAME[g["system"]], INK)

def draw(shown, attract, blink):
    sc = Grid(); w, h = sc.w, sc.h; L, LW = 4, min(56, w // 2 - 4); CX = L + LW
    header(sc, "HUD BAR " + ("ON" if hud_on() else "OFF") if MANGO else "")
    y = 6
    for i, r in enumerate(ROWS):
        if i == 0 or r["g"]["section"] != ROWS[i - 1]["g"]["section"]:
            if i: y += 1
            t = r["g"]["section"].upper(); sc.put(L, y, t, DIM, bold=True); sc.rule(L + len(t) + 1, y, LW - len(t) - 4)
            y += 1
        on = i == shown; st = "ok" if r["ok"] and r["rom"][0] == "ok" else "unsure" if r["ok"] else "miss"
        fg = INK if on else PAPER if r["ok"] else DIM
        if on: sc.fill(L, y, LW, 1, CARD)
        sc.put(L + 1, y, DOT[st][0], DOT[st][2] if on else DOT[st][1])
        nw = 18; sc.put(L + 4, y, r["name"][:nw - 1], fg, bold=on)
        sc.put(L + 4 + nw, y, r["job"][:LW - nw - 11], fg if on or not r["ok"] else "#c9c1b3")
        sc.right(L + LW - 2, y, SYS[r["g"]["system"]], fg if on else DIM)
        y += 1
    miss = sum(not r["ok"] for r in ROWS)
    if miss: sc.put(L + 1, y + 1, ("○ %d %s: the card says what to add." % (miss, "game cannot start" if miss == 1 else "games cannot start"))[:LW - 1], DIM)
    card(sc, ROWS[shown], CX, 6, w - 4, h - 3)
    sc.caps(L, h - 2, [("A", P1, "PLAY"), ("↑↓", KEY, "GAME")] + ([("SELECT", KEY, "HUD BAR")] if MANGO else []) + [("HOME", P2, "QUIT")])
    if attract: sc.right(w - 4, h - 2, "PRESS ANY BUTTON" if blink else "", CARD, bold=True)
    elif note: sc.right(w - 4, h - 2, note, DOT["miss"][1], bold=True)
    return sc.ansi()

if __name__ == "__main__":
    fds, seen, stick, done = {}, 0, 0, None
    t_in, frame = time.time(), None
    start()
    while done is None:
        if time.time() - seen > 2:                       # InputPlumber may (re)create the node during the launch
            for p in pads():
                if p not in fds.values():
                    try: fds[os.open(p, os.O_RDONLY | os.O_NONBLOCK)] = p
                    except OSError: pass
            seen = time.time()
        idle = time.time() - t_in; attract = idle > IDLE
        shown = (cur + 1 + int((idle - IDLE) // ATTRACT_STEP)) % len(ROWS) if attract else cur
        frame = show(draw(shown, attract, int(idle * 2) % 2 == 0), frame)
        r, _, _ = select.select(list(fds), [], [], 0.5)
        for fd in r:
            try: data = os.read(fd, 24 * 64)
            except OSError: os.close(fd); fds.pop(fd, None); continue
            for k in range(0, len(data) - 23, 24):
                _, _, typ, code, val = struct.unpack("qqHHi", data[k:k + 24])
                move, press = 0, typ == EV_KEY and val == 1
                if typ == EV_ABS and code == ABS_HAT0Y and val: move = val
                elif typ == EV_ABS and code == ABS_Y:    # DualSense stick 0-255, centre 128: once per push
                    s = -1 if val < 48 else 1 if val > 208 else 0
                    if s and not stick: move = s
                    stick = s
                if (press or move) and time.time() - t_in > IDLE: t_in = time.time(); continue   # attract mode: wake only
                if press or move: t_in = time.time()
                if press:
                    if code in (BTN_SOUTH, BTN_EAST, BTN_START):
                        if ROWS[cur]["ok"]: done = ROWS[cur]["g"]["id"]
                        else: note = "Not playable yet: the card says what to add."
                    elif code == BTN_MODE: done = "quit"
                    elif code == BTN_SELECT and MANGO:
                        on = not hud_on(); os.makedirs(STATE, exist_ok=True)
                        open(HUD, "w").write("on\n" if on else "off\n")
                if move: cur = (cur + move) % len(ROWS); note = ""
                if done: break
            if done: break
    end()
    open(OUT, "w").write(done + "\n")
    if done != "quit":
        os.makedirs(STATE, exist_ok=True); open(os.path.join(STATE, "last_game"), "w").write(done + "\n")
