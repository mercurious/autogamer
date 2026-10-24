#!/usr/bin/env python3
# Runs on the handheld in a fullscreen foot window (autogamer.sh): the game menu. The main games first, then the
# bonus ones; under the list, what the highlighted game is, its ROM (or which one to add) and its model. D-pad or left
# stick up/down moves, A, B or START plays (a game without its ROM or model only says what is missing), HOME quits.
# Writes the game's id, or "quit", to OUT; the last game played is highlighted (STATE/last_game).
# Usage: menu.py OUT STATE      env: AG_MODELS (the models directory), AG_ROMS
#   Reads only; never grabs the pad.
import os, select, shutil, struct, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from home import pads, EV_KEY, BTN_MODE
import games
EV_ABS, ABS_Y, ABS_HAT0Y = 3, 1, 17
BTN_SOUTH, BTN_EAST, BTN_START = 304, 305, 315
OUT, STATE = sys.argv[1], sys.argv[2]
M = os.environ.get("AG_MODELS", "")
GGUF = {"e2b": "gemma-4-E2B_q4_0-it.gguf", "e4b": "gemma-4-E4B_q4_0-it.gguf"}
TTS = "pocket-tts-english_2026-09-Q8_0.gguf"
DIM, BOLD, OFF = "\033[2m", "\033[1m", "\033[0m"

def have(f): return bool(M) and os.path.isfile(os.path.join(M, f))

def model_line(g):
    """(text, playable) for the game's model: the bigger one falls back to E2B, as run.sh does"""
    if not g["model"]: return g.get("nomodel", "No model: a bot plays.") + ("" if have(TTS) or not g["tts"] else " No voice (Pocket TTS is not installed)."), True
    if g["model"] == "e4b" and have(GGUF["e4b"]): name = "Gemma 4 E4B"
    elif have(GGUF["e2b"]): name = "Gemma 4 E2B" + (" (E4B is not installed)" if g["model"] == "e4b" else "")
    else: return "The model is missing: run install.sh.", False
    return "Model: %s%s." % (name, "" if have(TTS) else ", no voice (Pocket TTS is not installed)"), True

ROWS = []
for g in games.GAMES:
    path, ok = games.find(g)
    ml, mok = model_line(g)
    rom = ("ROM: %s" % os.path.basename(path) if ok else
           "ROM: %s (not the version it was made for: it may misread the game)" % os.path.basename(path) if path else
           games.need(g) + ".")
    ROWS.append(dict(g=g, rom=rom, model=ml, ok=bool(path) and mok))
try: last = open(os.path.join(STATE, "last_game")).read().strip()
except OSError: last = ""
cur = next((i for i, r in enumerate(ROWS) if r["g"]["id"] == last), 0)
note = ""

def wrap(s, w):
    out, line = [], ""
    for word in s.split():
        if line and len(line) + 1 + len(word) > w: out.append(line); line = word
        else: line = (line + " " + word).strip()
    return out + [line] if line else out

def draw():
    w, h = shutil.get_terminal_size((60, 20)); width = min(w - 2, 60)
    out = [BOLD + "AUTOGAMER" + OFF, "a language model plays retro games", ""]
    for i, r in enumerate(ROWS):
        if i == 0: out.append(DIM + "MAIN" + OFF)
        if r["g"]["section"] == "bonus" and ROWS[i - 1]["g"]["section"] != "bonus": out += ["", DIM + "BONUS" + OFF]
        t = ("> " if i == cur else "  ") + r["g"]["title"]
        out.append((BOLD if i == cur else "") + (t if r["ok"] else DIM + t) + OFF)
    r = ROWS[cur]
    out += [""] + list(r["g"]["about"]) + [""] + wrap(r["rom"], width) + wrap(r["model"], width)
    out += ["", note or "Up/down: game   A or START: play   HOME: quit"]
    plain = lambda s: s.replace(DIM, "").replace(BOLD, "").replace(OFF, "")
    width = max(len(plain(l)) for l in out); pad = " " * max((w - width) // 2, 0)
    top = "\n" * max((h - len(out)) // 2, 0)
    sys.stdout.write("\033[H\033[2J\033[?25l" + top + "\n".join(pad + l for l in out)); sys.stdout.flush()

if __name__ == "__main__":
    fds, seen, stick, done = {}, 0, 0, None
    while done is None:
        if time.time() - seen > 2:                       # InputPlumber may (re)create the node during the launch
            for p in pads():
                if p not in fds.values():
                    try: fds[os.open(p, os.O_RDONLY | os.O_NONBLOCK)] = p
                    except OSError: pass
            seen = time.time()
        draw()
        r, _, _ = select.select(list(fds), [], [], 0.5)
        for fd in r:
            try: data = os.read(fd, 24 * 64)
            except OSError: os.close(fd); fds.pop(fd, None); continue
            for k in range(0, len(data) - 23, 24):
                _, _, typ, code, val = struct.unpack("qqHHi", data[k:k + 24])
                move = 0
                if typ == EV_KEY and val == 1:
                    if code in (BTN_SOUTH, BTN_EAST, BTN_START):
                        if ROWS[cur]["ok"]: done = ROWS[cur]["g"]["id"]
                        else: note = "Not playable yet: see above."
                    elif code == BTN_MODE: done = "quit"
                elif typ == EV_ABS and code == ABS_HAT0Y and val: move = val
                elif typ == EV_ABS and code == ABS_Y:    # DualSense stick 0-255, centre 128: once per push
                    s = -1 if val < 48 else 1 if val > 208 else 0
                    if s and not stick: move = s
                    stick = s
                if move: cur = (cur + move) % len(ROWS); note = ""
                if done: break
            if done: break
    sys.stdout.write("\033[?25h\033[H\033[2J"); sys.stdout.flush()
    open(OUT, "w").write(done + "\n")
    if done != "quit":
        os.makedirs(STATE, exist_ok=True); open(os.path.join(STATE, "last_game"), "w").write(done + "\n")
