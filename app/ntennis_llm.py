#!/usr/bin/env python3
# Runs on the handheld: the language model plays NES Tennis (Nintendo, 1984; fceumm), singles against the computer.
# The reflex loop runs to the ball and swings; when the computer hits (or serves), the model picks the stroke for our
# return: a forehand (sends the ball to the right of the computer's court) or a backhand (to the centre-left). Until
# it has answered, the loop runs to the ball for a forehand; if the model is too late it swings on impulse, hitting
# away from where the computer stands (forehand when it is left of centre), and when the shot leaves less time than
# the model usually takes, the player lines up for that stroke from the start (it read as
# overthinking when it waited for the model; as Tetris's low-first). The model's stroke still takes over when it comes in time. The game runs in RetroArch's slow motion at the level's ratio (level.py, run.sh ntennis-model).
# RAM (NES CPU addresses, mapped 2026-10-09): 58/59 our / the computer's points in the game (0 love .. 3
# forty), 3E points played, 6E-6F ball height (1/16 px), 70/71 ball ground x / y on the screen (the shadow; y grows
# toward us), 300 object 0 active (1 in a match, 0 on the title and level menus), 308/309 our feet y / x, 348/349
# the computer's, 014 = 10 on the level menu. Serve: the toss is automatic and only A within ~0.1 s of its start
# serves. Return: A when the ball's ground y is within 6 px of our feet, standing ~8 px left of it (forehand) or
# ~12 px right of it (backhand). Holding a direction at contact does not steer; B lobs (often long).
# Usage: ntennis_llm.py SECONDS [log.jsonl]   env: TL_RUN, TL_CALIB, TN_WCALIB, TL_TTS, AG_MODEL_LABEL, VS_PORT,
#   NT_CPU (the game's own computer level, 1-5, default 1)
import json, os, random, re, socket, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from ra import RA; from pad import Pad; import llm, voice
LLM = "http://127.0.0.1:%s" % os.environ.get("VS_PORT", "8099"); TTS = os.environ.get("TL_TTS", "0") == "1"
MODEL = os.environ.get("AG_MODEL_LABEL", "model"); RUN = os.environ.get("TL_RUN")
CALIB = os.environ.get("TL_CALIB"); WCALIB = os.environ.get("TN_WCALIB"); CPU = int(os.environ.get("NT_CPU", "1"))
OFF = {"forehand": -8, "backhand": 12}; LANDS = {"forehand": 100, "backhand": 57}   # where each sends the ball, 0-100
REACH = 6                                     # swing when the ball's ground y is this close to our feet
HAND = 22.1                                   # ball height in the server's hand (21.8-21.9)
THINK0 = float(os.environ.get("TL_THINK0", "4"))
try: W0 = float(open(os.environ.get("TN_WCALIB", "")).read())
except (OSError, ValueError): W0 = 1.74          # game seconds from the computer's hit to ours (measured)
COURT = (71, 183)                             # the computer's baseline, screen x left to right
CALL = ["love", "15", "30", "40"]
SYSTEM = ("You are playing NES Tennis (1984) against the game's computer player. You run to the ball by yourself; "
          "your only choice is the stroke for each return: a forehand sends the ball to the right of the computer's "
          "court, a backhand to the centre. A ball sent away from where the computer stands makes it run and wins "
          "points; one sent at it comes back. Each shot you get the score, where the computer stands (court position "
          "0-100, left to right), your record so far (returns, then points won and lost after each stroke), and two "
          "lettered strokes with where each sends the ball and how far that is from the computer. Reply exactly as: PICK <letter>")

def level():
    try:
        lv = [l.split() for l in open(os.path.join(RUN, "levels")) if l.strip()]
        name, r, _ = lv[int(open(os.path.join(RUN, "level")).read())]; return name, max(float(r), 1)
    except (TypeError, OSError, ValueError, IndexError): return None, 1

def save(path, xs):
    if not path or len(xs) < 3: return
    try:
        with open(path + ".tmp", "w") as f: f.write("%.2f\n" % (sum(xs) / len(xs)))
        os.replace(path + ".tmp", path)
    except OSError: pass

def rd(a, n):
    """n bytes at a, from a reply that names a (late replies to earlier requests are dropped)"""
    ra.s.setblocking(False)
    try:
        while True: ra.s.recv(65536)
    except (BlockingIOError, socket.error): pass
    ra.s.settimeout(0.2)
    p = (ra.cmd("READ_CORE_MEMORY %x %d" % (a, n)) or "").split()
    return bytes(int(x, 16) for x in p[2:]) if len(p) == n + 2 and p[1] == "%x" % a else None

def pos(x): return max(0, min(100, round((x - COURT[0]) * 100 / (COURT[1] - COURT[0]))))

def score_text(us, them):
    if us >= 3 and them >= 3: return "deuce" if us == them else "advantage %s" % ("you" if us > them else "the computer")
    return "%s-%s in this game (you first)" % (CALL[min(us, 3)], CALL[min(them, 3)])

def facts(us, them, cx, mx, rec, order):
    p = pos(cx)
    lines = ["Score: %s." % score_text(us, them),
             "Computer %d (%s). You %d." % (p, "left of centre" if p < 44 else "right of centre" if p > 56 else "centre", pos(mx)),
             "Record: " + ", ".join("%s %d %d %d" % (a, rec[a]["n"], rec[a]["won"], rec[a]["lost"]) for a in OFF) + "."]
    for i, a in enumerate(order):
        lines.append("%s) %s: to %d, %d from the computer" % ("AB"[i], a, LANDS[a], abs(LANDS[a] - p)))
    return "\n".join(lines)

def ask(text):
    return llm.chat(LLM, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}], 6, 0.3, 120, cache=True)[0]

def say(line, show=None, spoken=True):
    if TTS and spoken: voice.say(line, show=show, ra=ra)
    elif show: ra.cmd("SHOW_MSG " + show, reply=False)

if __name__ == "__main__":
    T = float(sys.argv[1]); LOG = open(sys.argv[2], "a") if len(sys.argv) > 2 else None
    ra, pad = RA(timeout=0.2), Pad()
    if "PAUSED" in (ra.cmd("GET_STATUS") or ""): ra.cmd("PAUSE_TOGGLE", reply=False)
    log = lambda d: LOG and (LOG.write(json.dumps(dict(t=round(time.time() - t0, 1), **d)) + "\n"), LOG.flush())
    LEVEL, SLOW = level()
    rec = {a: dict(n=0, won=0, lost=0) for a in OFF}; thinks, windows = [], []; told = False
    t0 = time.time(); worker = None; relevel = False; menu_t = 0; held = []
    gy0 = None; dirn = 0; h0 = 0; served = False
    shot = None        # the computer's shot now coming: {"t", "box", "stroke", "busy", "swung"}
    last = None        # our last return: {"stroke", "late"}
    prev = None; n = late = 0
    try:
        while time.time() - t0 < T:
            if RUN and os.path.exists(os.path.join(RUN, "restart")):
                time.sleep(0.2); relevel = True; continue
            if relevel: LEVEL, SLOW = level(); relevel = False
            P = rd(0x300, 0x4A); A = rd(0x58, 0x1A)
            if not P or not A: continue
            TAP = 0.1 * SLOW
            if P[0] != 1:                                  # title or level menu: singles, the computer's level, start
                if held: pad.hold([]); held = []
                if time.time() - menu_t > 1.5 * SLOW:
                    if (rd(0x14, 1) or b"\0")[0] == 10:
                        for b in ["left"] * 4 + ["right"] * (CPU - 1): pad.tap(b, TAP); time.sleep(TAP)
                    pad.tap("start", TAP); menu_t = time.time()
                time.sleep(0.05); continue
            us, them = A[0], A[1]; h = (A[0x6E - 0x58] * 256 + A[0x6F - 0x58]) / 16.0
            gx, gy = A[0x70 - 0x58], A[0x71 - 0x58]; my, mx = P[8], P[9]; cx = P[0x49]
            if gy0 is None or gy != gy0:                    # depth direction from the last change (slow motion repeats)
                d = 0 if gy0 is None else (gy > gy0) - (gy < gy0)
                if gy0 is not None and abs(gy - gy0) > 16: d = 0; dirn = 0      # the ball put back in the server's hand
                if d and d != dirn:
                    if d == 1 and abs(gy - my) > 40:        # the computer hit (or served): the model picks our stroke
                        busy = worker is not None and worker.is_alive()
                        # impulse (the stroke if the model is too late): away from where the computer stands; when the
                        # shot leaves less time than the model usually takes, the player lines up for it from the start
                        expect = sum(thinks[1:]) / len(thinks[1:]) if len(thinks) > 1 else THINK0
                        wmean = sum(windows) / len(windows) if windows else W0
                        shot = dict(t=time.time(), box={}, stroke=None, busy=busy, swung=False, cx=cx, order=random.sample(list(OFF), 2),
                                    impulse="forehand" if pos(cx) < 50 else "backhand", hurry=busy or expect > wmean * SLOW)
                        if last and "went" not in last: last["went"] = gx
                        if not busy:
                            text = facts(us, them, cx, mx, rec, shot["order"]); box = shot["box"]
                            def think(text=text, box=box):
                                t1 = time.time()
                                try: box["ans"] = ask(text)
                                except Exception as ex: box["ans"] = "ERROR %s" % ex
                                box["dt"] = time.time() - t1; thinks.append(box["dt"]); save(CALIB, thinks[1:][-50:])
                            worker = threading.Thread(target=think, daemon=True); worker.start()
                    dirn = d
                gy0 = gy
            if shot and shot["stroke"] is None and "dt" in shot["box"]:          # the answer is in
                m = re.search(r"PICK\s*\(?([AB])\)?", shot["box"]["ans"])
                shot["stroke"] = shot["order"]["AB".index(m.group(1))] if m else "forehand"
                say("%s." % shot["stroke"].capitalize(), show="%s: %s, computer at %d" % (MODEL, shot["stroke"], pos(shot["cx"])), spoken=SLOW >= 2)
            btn = []
            toss = abs(gy - my) < 24 and dirn == 0 and HAND < h < 60 and h > h0 > 0   # our toss is rising (in hand: 21.8-21.9)
            if toss and not served:
                btn = ["a"]; served = True; shot = None     # serve at once: later presses do nothing
            if h <= HAND: served = False
            h0 = h
            if shot and not shot["swung"] and dirn == 1:     # run to the ball; swing with the model's stroke, or on impulse
                plan = shot["stroke"] or (shot["impulse"] if shot["hurry"] else "forehand")
                tx = gx + OFF[plan]
                if mx < tx - 2: btn.append("right")
                elif mx > tx + 2: btn.append("left")
                if 0 <= my - gy <= REACH:
                    stroke = shot["stroke"] or shot["impulse"]; rushed = shot["stroke"] is None
                    btn = ["a"]; shot["swung"] = True
                    w = time.time() - shot["t"]; windows.append(w / SLOW); save(WCALIB, windows[-50:])
                    rec[stroke]["n"] += 1; n += 1; late += rushed; last = dict(stroke=stroke, late=rushed)
                    if rushed:
                        if not told:
                            told = True; say("No time to think it through. I hit it away from the computer.", spoken=True)
                        say("", show="%s: no time, %s away from the computer" % (MODEL, stroke), spoken=False)
                    log(dict(shot=n, stroke=stroke, late=rushed, hurry=shot["hurry"], busy=shot["busy"], window_s=round(w / SLOW, 2), cx=shot["cx"],
                             think_s=round(shot["box"]["dt"], 1) if "dt" in shot["box"] else None, answer=shot["box"].get("ans"), level=LEVEL, slow=SLOW))
            if btn != held:
                if "a" in btn: pad.hold(btn); time.sleep(TAP); btn = [b for b in btn if b != "a"]
                pad.hold(btn); held = btn
            pts = (us, them)
            if prev is not None and pts != prev:             # a point ended
                if them > prev[1]: won = False
                elif us > prev[0]: won = True
                elif us == them == 0: won = prev[0] > prev[1]    # a game ended (back to love): the leader won it
                else: won = them < prev[1]                   # an advantage lost (back to deuce)
                game = us == them == 0
                if last: rec[last["stroke"]]["won" if won else "lost"] += 1
                line = ("Game to %s." if game else "Point to %s.") % ("me" if won else "the computer")
                if last: line += " My last shot was a %s%s." % (last["stroke"], ", on impulse" if last["late"] else "")
                say(line, show="%s: %s" % (MODEL, line))
                log(dict(point="us" if won else "computer", game=game, last=last and last["stroke"], impulse=bool(last and last["late"]),
                         score=[us, them], level=LEVEL, slow=SLOW))
                last = None; shot = None; dirn = 0; gy0 = None
                if game: told = False
            prev = pts
            time.sleep(0.008)
    finally:
        pad.release_all()
        if os.environ.get("KEEP_RUNNING") != "1" and "PAUSED" not in (ra.cmd("GET_STATUS") or ""): ra.cmd("PAUSE_TOGGLE", reply=False)
        if LOG: LOG.close()
    print("%d returns in %.0f s, %d late, mean think %.1f s, mean window %.2f s; %s" % (
        n, time.time() - t0, late, sum(thinks) / max(len(thinks), 1), sum(windows) / max(len(windows), 1), json.dumps(rec)))
