#!/usr/bin/env python3
# Runs on the handheld: the language model plays NES Tetris. For each new piece the model (on VS_PORT, text only) gets the
# column heights from RAM and the K best legal placements by the Lee heuristic, in shuffled order, each with what it
# does (lines, holes, height, bumpiness), and replies with a letter; the pick's facts go on screen (SHOW_MSG) and the
# closed loop from tetris.py moves the piece. With TL_PAUSE=1 (no TL_RUN) the game pauses while it thinks.
# While it thinks, MangoHud shows its progress (llm.py: reading the prompt, writing, tok/s). With TL_TTS=1 the pick is
# spoken (voice.py) from the facts of the chosen placement.
# With TL_RUN (run.sh's run folder, with levels and level) the game is not paused: it runs in RetroArch's slow motion
# at the level's ratio (level.py turns it on and changes levels) while the model thinks as the piece falls. Each pick
# updates this session's mean think time in TL_CALIB, from which the next launch sets the ratios.
# Usage: tetris_llm.py SECONDS [log.jsonl]     env: TL_K (default 6), TL_PAUSE=0 (think while the piece falls), TL_TTS=1,
#   TL_RUN, TL_CALIB (file for the mean think time)
# Losing is spoken too (TL_TTS=1): a piece that lands before the model has decided ("too late", timed by watching the
# game while it thinks), the stack passing DANGER rows once a game, and at game over the model's own two sentences
# on why it lost, from that game's facts (any number not in the facts -> a template line instead).
import json, os, random, re, sys, threading, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from ra import RA; from pad import Pad; import hud, llm, voice
import tetris as tt
LLM = "http://127.0.0.1:%s" % os.environ.get("VS_PORT", "8099"); K = int(os.environ.get("TL_K", "6"))
PAUSE = os.environ.get("TL_PAUSE", "1") != "0"; TTS = os.environ.get("TL_TTS", "0") == "1"
MODEL = os.environ.get("AG_MODEL_LABEL", "model")
RUN = os.environ.get("TL_RUN"); CALIB = os.environ.get("TL_CALIB")
GAMELEVEL = int(os.environ.get("TL_GAMELEVEL", "0"))   # NES level to start each game at (0-9, run.sh picks it)
if RUN: PAUSE = False

def level():
    """(name, ratio) of the level now playing, or (None, 0) without levels."""
    try:
        lv = [l.split() for l in open(os.path.join(RUN, "levels")) if l.strip()]
        name, r, _ = lv[int(open(os.path.join(RUN, "level")).read())]; return name, float(r)
    except (TypeError, OSError, ValueError, IndexError): return None, 0
WORDS = ["no", "one", "two", "three", "four"]
NAMES = ["T"] * 4 + ["J"] * 4 + ["Z"] * 2 + ["O"] + ["S"] * 2 + ["L"] * 4 + ["I"] * 2
# The fixed text is all in the system prompt and the request is cached (llm.chat cache=True), so each pick reads only
# the column heights, the piece and the placements (~110 tokens), and the reply is the letter alone: reading the old
# 330-token prompt was ~85 % of E4B's 13 s (2026-10-09).
SYSTEM = ("You are playing Tetris. Pick the best placement for the current piece. Good placements clear lines, "
          "leave no holes (empty cells covered from above), keep the stack low and the surface flat. "
          "Each turn you get the column heights (left to right, 0-20), the piece, and lettered placements, each as: "
          "column, flat or turned: lines it clears, holes it leaves, stack height, bumpiness. Reply exactly as: PICK <letter>")

def features(board, o, x, y0):
    y = y0
    while tt.fits(board, o, x, y + 1): y += 1
    nb = [row[:] for row in board]
    for dx, dy in tt.SHAPES[o]:
        if y + dy >= 0: nb[y + dy][x + dx] = True
    full = sum(1 for r in nb if all(r)); rows = [r for r in nb if not all(r)]; b = [[False] * 10] * full + rows
    hts, holes = [], 0
    for c in range(10):
        top = next((r for r in range(20) if b[r][c]), 20); hts.append(20 - top); holes += sum(1 for r in range(top, 20) if not b[r][c])
    bump = sum(abs(hts[i] - hts[i + 1]) for i in range(9))
    score = tt.W_H * sum(hts) + tt.W_L * full + tt.W_HO * holes + tt.W_B * bump
    return dict(o=o, x=x, lines=full, holes=holes, height=max(hts), bump=bump, score=score)

def render(board):
    hts = [next((20 - r for r in range(20) if board[r][c]), 0) for c in range(10)]
    top = max(hts + [1]); rows = ["".join("#" if board[r][c] else "." for c in range(10)) for r in range(20 - top - 1, 20)]
    return "\n".join(rows), hts

def save_mean(thinks):
    if not CALIB or len(thinks) < 3: return
    try:
        with open(CALIB + ".tmp", "w") as f: f.write("%.1f\n" % (sum(thinks) / len(thinks)))
        os.replace(CALIB + ".tmp", CALIB)
    except OSError: pass

DANGER = 12
GRAV = [48, 43, 38, 33, 28, 23, 18, 13, 8, 6, 5, 5, 5, 4, 4, 4, 3, 3, 3] + [2] * 11   # NES frames a row, by level
THINK0 = float(os.environ.get("TL_THINK0", "7"))

def drive(tx, to, drop):
    """one step of the closed loop toward column tx, orientation to (drop: hold down once there); returns the RAM read"""
    global held, last_fc
    z = ra.ram(0x40, 0x10)
    if not z or z[8] != 1: return z
    if RUN:       # one change of the buttons per game frame (frame counter B1), or the game misses most of them
        fc = ra.ram(0xB1, 1)
        if fc == last_fc: return z
        last_fc = fc
    x, ori = z[0], z[2]; want = set()
    if ori != to and "a" not in held: want.add("a")
    if x < tx and "right" not in held: want.add("right")
    if x > tx and "left" not in held: want.add("left")
    if drop and ori == to and x == tx: want.add("down")
    held = want; pad.hold(sorted(want))
    return z
REFLECT = ("You are the AI that was playing Tetris and just lost. In at most two short sentences, in the first person, "
           "say why you lost, using only the facts given. Do not invent numbers.")

def reflect(g, ra, label, slow):
    """Game over: the model says why it lost, from the facts of this game."""
    st = ra.ram(0x50, 6) or bytes(6); lv = ra.ram(0x64, 1) or bytes(1)
    lines_n = tt.bcd(st[1]) * 100 + tt.bcd(st[0]); think = sum(g["thinks"]) / max(len(g["thinks"]), 1)
    facts = ["Difficulty %s: %s." % (label, "the game ran at full speed" if slow <= 1 else "the game ran %.1f times slower than normal" % slow),
             "You placed %d pieces and cleared %d lines; the game reached level %d." % (g["pieces"], lines_n, lv[0]),
             "%d pieces landed on their own before you had decided where to put them." % g["late"],
             "You took %.0f seconds on average to decide." % think]
    if g["landed"]: facts.append("Pieces you were too late for landed after %.0f seconds on average." % (sum(g["landed"]) / len(g["landed"])))
    facts.append("The stack reached the top of the well.")
    fx = " ".join(facts)
    try: out = llm.chat(LLM, [{"role": "system", "content": REFLECT}, {"role": "user", "content": fx}], 60, 0.5, 120)[0]
    except Exception: out = ""
    out = " ".join(out.split()).strip('"')
    if not out or not set(re.findall(r"\d+", out)) <= set(re.findall(r"\d+", fx)):
        out = ("I lost. %d pieces landed before I could decide; I need about %.0f seconds a piece." % (g["late"], think) if g["late"]
               else "I lost. The stack reached the top after %d pieces." % g["pieces"])
    return out, fx

def ask(text):
    return llm.chat(LLM, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}], 6, 0.2, 120, cache=True)[0]

if __name__ == "__main__":
    T = float(sys.argv[1]); LOG = open(sys.argv[2], "a") if len(sys.argv) > 2 else None
    ra, pad = RA(timeout=0.3), Pad()
    if "PAUSED" in (ra.cmd("GET_STATUS") or ""): ra.cmd("PAUSE_TOGGLE", reply=False)
    LEVEL, SLOW = level()
    nav = False
    t0 = time.time(); target = None; last_state = None; held = set(); menu_t = 0; stuck_t = None; n = 0; thinks = []; late = 0; last_fc = None
    new_game = lambda: dict(playing=False, pieces=0, late=0, thinks=[], landed=[], danger=False, hurry=False); g = new_game()
    try:
        while time.time() - t0 < T:
            if RUN and os.path.exists(os.path.join(RUN, "restart")): time.sleep(0.2); continue   # level change (level.py)
            z = ra.ram(0x40, 0x10); hi = ra.ram(0xBF, 2)
            if not z or not hi: continue
            mode, state = hi[1], z[8]
            stuck = mode != 4 or state in (0, 10)     # menus, game over, high-score name entry
            if not stuck: stuck_t = None
            elif stuck_t is None: stuck_t = time.time()
            if stuck and (mode != 4 or time.time() - stuck_t > 1.5):   # Start (level 0, A-type); in play it would pause
                target = None
                if g["playing"]:        # game over: the model says why, while the game-over screen waits
                    pad.release_all(); held = set()
                    said, fx = reflect(g, ra, LEVEL or "", SLOW)
                    if TTS: voice.say(said, show="%s: %s" % (MODEL, said[:110]), ra=ra)
                    else: ra.cmd("SHOW_MSG %s: %s" % (MODEL, said[:110]), reply=False)
                    if LOG: LOG.write(json.dumps({"t": round(time.time() - t0, 1), "gameover": True, "level": LEVEL, "slow": SLOW, "facts": fx, "said": said}) + "\n"); LOG.flush()
                    g = new_game(); time.sleep(4)
                TAP = 0.1 * max(SLOW, 1)        # the game reads the pad once a frame: in slow motion, SLOW / 60 s
                if mode == 3 and GAMELEVEL and not nav:   # level menu (0-4 above 5-9): to 0, then to GAMELEVEL
                    for b in ["up"] + ["left"] * 4 + (["down"] if GAMELEVEL >= 5 else []) + ["right"] * (GAMELEVEL % 5):
                        pad.tap(b, TAP); time.sleep(TAP)
                    nav = True; menu_t = 0
                if mode != 3: nav = False
                if time.time() - menu_t > 1.0 + 2 * TAP: pad.tap("start", TAP); menu_t = time.time()
                time.sleep(0.05); continue
            x, y, ori = z[0], z[1], z[2]
            if state != 1 or ori > 18: pad.hold([]); held = set(); last_state = state; continue
            g["playing"] = True
            if target is None or last_state != 1 or ori not in tt.GROUP[target[1]]:
                if PAUSE: ra.cmd("PAUSE_TOGGLE", reply=False)
                LEVEL, SLOW = level()
                f = ra.ram(0x400, 200); board = [[f[r * 10 + c] != 0xEF for c in range(10)] for r in range(20)]
                cands = [features(board, o, cx, y) for o in tt.GROUP[ori] for cx in range(10) if tt.fits(board, o, cx, y)]
                cands.sort(key=lambda c: -c["score"]); top = cands[:K]; best = top[0]; random.shuffle(top)
                pic, hts = render(board)
                lines = ["Heights %s. Piece %s." % (" ".join(map(str, hts)), NAMES[ori])]
                for i, c in enumerate(top):
                    lines.append("%s) column %d, %s: %d lines, %d holes, height %d, bumpiness %d" % (
                        "ABCDEFGH"[i], c["x"], ["flat", "turned"][c["o"] != ori] if len(tt.GROUP[ori]) > 1 else "only way",
                        c["lines"], c["holes"], c["height"], c["bump"]))
                # Hurry: when the piece will land sooner than the model usually takes (its rows above the stack, the
                # game's gravity, the slow motion), move it at once to the placement that keeps the stack lowest; the
                # model's pick still takes over if it comes in time. A high stack otherwise lets pieces land untouched
                # in the middle and the next ones land sooner still (watching it play: always lost from 50 %).
                yl = y
                while tt.fits(board, ori, x, yl + 1): yl += 1
                lv = (ra.ram(0x64, 1) or bytes(1))[0]
                fall = (yl - y) * GRAV[min(lv, 29)] / 60.0 * max(SLOW, 1)
                expect = sum(thinks[1:]) / len(thinks[1:]) if len(thinks) > 1 else THINK0
                low = min(cands, key=lambda c: (c["height"], c["holes"], -c["lines"]))
                hurry = not PAUSE and fall < expect
                if hurry and not g["hurry"]:
                    g["hurry"] = True
                    if TTS: voice.say("No time to think it through. I move each piece low first.")
                if hurry: ra.cmd("SHOW_MSG %s, %s: no time, low first (column %d)" % (MODEL, NAMES[ori], low["x"]), reply=False)
                t1 = time.time(); box = {}
                def think(text="\n".join(lines)):
                    try: box["ans"] = ask(text)
                    except Exception as e: box["ans"] = "ERROR %s" % e
                th = threading.Thread(target=think, daemon=True); th.start(); landed = None
                while th.is_alive():      # the game runs on while it thinks: watch for the piece landing (still this one?)
                    th.join(0.012 if hurry else 0.05)
                    if not PAUSE and landed is None:
                        z2 = drive(low["x"], low["o"], False) if hurry else ra.ram(0x40, 0x10)
                        if z2 and (z2[8] != 1 or z2[1] < y or z2[2] not in tt.GROUP[ori]): landed = time.time() - t1
                ans = box.get("ans", ""); dt = time.time() - t1; thinks.append(dt); g["thinks"].append(dt); save_mean(thinks[1:])   # the first pick fills the prompt cache: slow
                if landed is not None:
                    late += 1; g["late"] += 1; g["landed"].append(landed); target = None; last_state = None
                    said = ("Too late; it went low." if hurry else "Too late. It landed after %.0f seconds; I needed %.0f." % (landed, dt))
                    if TTS: voice.say(said, show="%s, %s: %s" % (MODEL, NAMES[ori], said), ra=ra)
                    else: ra.cmd("SHOW_MSG %s, %s: %s" % (MODEL, NAMES[ori], said), reply=False)
                    if LOG: LOG.write(json.dumps({"t": round(time.time() - t0, 1), "late": True, "piece": NAMES[ori], "think_s": round(dt, 1), "landed_s": round(landed, 1), "level": LEVEL, "slow": SLOW,
                                                  "hurry": hurry, "fall_s": round(fall, 1), "low_x": low["x"]}) + "\n"); LOG.flush()
                    continue
                m = re.search(r"PICK\s*\(?([A-H])\)?", ans); pick = top["ABCDEFGH".index(m.group(1))] if m and "ABCDEFGH".index(m.group(1)) < len(top) else best
                target = (pick["x"], pick["o"]); n += 1; g["pieces"] += 1
                ra.cmd("SHOW_MSG %s, %s: column %d, %d lines, %d holes" % (MODEL, NAMES[ori], pick["x"], pick["lines"], pick["holes"]), reply=False)
                if TTS:
                    turned = "turned" if pick["o"] != ori and len(tt.GROUP[ori]) > 1 else "flat"
                    said = "%s piece, column %d, %s." % (NAMES[ori], pick["x"], turned)
                    if pick["lines"]: said += " Clears %s line%s!" % (WORDS[pick["lines"]], "" if pick["lines"] == 1 else "s")
                    elif pick["holes"]: said += " That leaves %s hole%s." % (WORDS[min(pick["holes"], 4)] if pick["holes"] <= 4 else pick["holes"], "" if pick["holes"] == 1 else "s")
                    if max(hts) >= DANGER and not g["danger"]:
                        g["danger"] = True; said += " The stack is at %d of 20 rows." % max(hts)
                        if g["late"]: said += " Pieces are landing before I decide."
                    voice.say(said)
                if PAUSE: ra.cmd("PAUSE_TOGGLE", reply=False)
                if LOG:
                    st = ra.ram(0x50, 6) or bytes(6)
                    LOG.write(json.dumps({"t": round(time.time() - t0, 1), "n": n, "piece": NAMES[ori], "think_s": round(dt, 1), "level": LEVEL, "slow": SLOW, "answer": ans,
                                          "hurry": hurry, "fall_s": round(fall, 1),
                                          "parsed": bool(m), "picked_best": pick is best, "pick_score": round(pick["score"], 2),
                                          "best_score": round(best["score"], 2), "holes_after": pick["holes"],
                                          "lines": tt.bcd(st[1]) * 100 + tt.bcd(st[0]), "stack": max(hts)}) + "\n"); LOG.flush()
                last_state = state; continue
            last_state = state; drive(target[0], target[1], True)
            time.sleep(0.012)
    finally:
        pad.release_all()
        if os.environ.get("KEEP_RUNNING") != "1" and "PAUSED" not in (ra.cmd("GET_STATUS") or ""): ra.cmd("PAUSE_TOGGLE", reply=False)
        if LOG: LOG.close()
    print("%d pieces in %.0f s%s" % (n, time.time() - t0, ", %d late, mean think %.1f s" % (
        late, sum(thinks) / max(len(thinks), 1)) if RUN else ""))
