#!/usr/bin/env python3
# Runs on the handheld: the language model plays NES Tennis (Nintendo, 1984; fceumm), singles against the computer.
# The reflex loop runs to where the computer's shot will reach our baseline and swings; the model picks where our
# return goes. The game sets a return's direction by when the swing meets the ball, not by the pad: a forehand met
# late goes right, met early goes left; a backhand the other way round. From where we meet the ball the return lands
# in a strip about 50 px wide (a ball met on the left of the court stays on the left half: no cross-court), and the
# choice is the two ends of that strip inside the singles court, given as court positions with how far each is from
# the computer. Until the model has answered, and when it is too late, the player hits on impulse to the end farther
# from the computer. The court is narrower than it looks from the computer's reach: most points the old player lost
# (forehand or backhand by fixed timing, "away from the computer") were returns out wide. The game runs
# in RetroArch's slow motion at the level's ratio (level.py, run.sh ntennis-model).
# RAM (NES CPU addresses, mapped 2026-10-09/10): 58/59 our / the computer's points in the game (0 love .. 3 forty),
# 3E points played, 6F ball height (94 in the server's hand; 6E a height band, 1 in the hand), 6C-6D its vertical
# speed (signed; it turns positive at a bounce), 70/71 ball ground x / y on the screen (the shadow; y grows toward
# us), 300 object 0 active (1 in a match, and in the attract demo: a doubles match, 320 on), 308/309 our feet y / x,
# 349 the computer's x, 039 the title's cursor (1 doubles; SELECT toggles), 014 = 10 on the level menu, 3A its
# cursor (0-4: levels 1-5; it wraps: the old four lefts from the default landed on level 2).
# Strokes (shot clinic on car12, 2026-10-10: savestates at the computer's hit, a grid of stand-offs and swing
# timings, 120 returns): a forehand works with the ball 3-16 px to our right (12 is safe: under ~8 some go into the
# net), a backhand with it 9-19 px to our left (under ~8: the net). A is pressed when our feet are REACH px below the
# ball's ground y: 3 (late) to 28 (early); contact comes a fixed few frames later. Landing x (screen, ~y 64) from the
# contact x c and REACH p: backhand 0.62c + 28 + 1.9(p - 3), forehand 0.62c + 73 - 1.8(p - 3). Holding a direction
# at contact does not steer; B lobs (often long). The singles sidelines where returns land (~y 64) are at x ~96 and
# ~160 (screen geometry); returns that landed at 70-82 or 178-187 lost the point, 98-155 won or rallied.
# Serve: the toss is automatic (or A); A while it rises serves: at height 112-157 (7-19 frames into the toss) in,
# 167 or more a fault (the ball drops).
# Usage: ntennis_llm.py SECONDS [log.jsonl]   env: TL_RUN, TL_CALIB, TN_WCALIB, TL_TTS, AG_MODEL_LABEL, VS_PORT,
#   NT_CPU (the game's own computer level, 1-5, default 1), NT_MODEL=0 (no model: every return on impulse)
import json, os, re, socket, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from ra import RA; from pad import Pad; import llm, voice
LLM = "http://127.0.0.1:%s" % os.environ.get("VS_PORT", "8099"); TTS = os.environ.get("TL_TTS", "0") == "1"
MODEL = os.environ.get("AG_MODEL_LABEL", "model"); RUN = os.environ.get("TL_RUN"); USE_MODEL = os.environ.get("NT_MODEL", "1") != "0"
CALIB = os.environ.get("TL_CALIB"); WCALIB = os.environ.get("TN_WCALIB"); CPU = int(os.environ.get("NT_CPU", "1"))
STAND = {"forehand": -12, "backhand": 13}     # our x - the ball's x at contact
EARLY, LATE = 26, 3                           # A at this many px of the ball's ground y before our feet
SERVE_H = 120                                 # A when the toss rises past this height (6F; 112-157 served, 167 faulted)
COURT = (96, 160)                             # the singles sidelines (screen x) at the far baseline and where returns land
LAND = (101, 155)                             # where a return is aimed: inside them (a return to 70 or 180 is out)
MID = 128                                     # where we wait for the computer's shot (its shots met us at x 31-230)
CALL = ["love", "15", "30", "40"]
# Without the last sentence E4B picked the farther spot 9 times in 16 (chance), with it 16 in 16 (2.0 s, was 3.0)
SYSTEM = ("You are playing NES Tennis (1984) against the game's computer player. You run to the ball by yourself; "
          "your only choice is where each return goes. The computer must run to reach it: a return far from where the "
          "computer stands wins the point, one near it comes back. Each shot you get the score, where the computer stands "
          "(court position 0-100, left to right) and two lettered spots your return can reach, each with its distance "
          "from the computer. Pick the spot that is farther from the computer. Reply exactly as: PICK <letter>")

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

def lands(stroke, c, p):
    """screen x where a return met at x c lands, A pressed p px early"""
    return 0.62 * c + 28 + 1.9 * (p - 3) if stroke == "backhand" else 0.62 * c + 73 - 1.8 * (p - 3)

def reach_for(stroke, c, x):
    """the swing distance that sends a return met at c to x (clamped to what the swing can do)"""
    p = (x - 0.62 * c - 28) / 1.9 + 3 if stroke == "backhand" else (0.62 * c + 73 - x) / 1.8 + 3
    return max(LATE, min(EARLY, round(p)))

def spots(c):
    """the two ends of where a return met at c can land, left first"""
    lo, hi = lands("backhand", c, LATE), lands("backhand", c, EARLY)
    return {"left": max(LAND[0], min(LAND[1], lo)), "right": max(LAND[0], min(LAND[1], hi))}

def score_text(us, them):
    if us >= 3 and them >= 3: return "deuce" if us == them else "advantage %s" % ("you" if us > them else "the computer")
    return "%s-%s in this game (you first)" % (CALL[min(us, 3)], CALL[min(them, 3)])

def facts(us, them, cx, sp, order):
    p = pos(cx); lines = ["Score: %s." % score_text(us, them), "Computer at %d." % p]
    for i, a in enumerate(order): lines.append("%s) to %d: %d from the computer" % ("AB"[i], pos(sp[a]), abs(pos(sp[a]) - p)))
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
    rec = {a: dict(n=0, won=0, lost=0) for a in ("left", "right")}; thinks, windows = [], []; told = False
    t0 = time.time(); worker = None; relevel = False; menu_t = 0; held = []
    gy0 = None; dirn = 0; h0 = 0; served = False; vz0 = 0
    shot = None        # the computer's shot now coming: {"t", "y0", "path", "c" (where it meets us), "box", "aim", "swung", ...}
    last = None        # our last return: {"aim", "late", "target", "bounce"}
    prev = None; n = late = won = lost = 0
    try:
        while time.time() - t0 < T:
            if RUN and os.path.exists(os.path.join(RUN, "restart")):
                time.sleep(0.2); relevel = True; continue
            if relevel: LEVEL, SLOW = level(); relevel = False
            M = rd(0x58, 0x2F2)                            # 058-349 in one read (a frame): two reads skipped past the swing
            if not M: continue
            R = lambda a: M[a - 0x58]
            TAP = 0.1 * SLOW
            if R(0x300) != 1 or R(0x320) == 1:                 # title, level menu, or the attract demo (doubles: 320 on)
                if held: pad.hold([]); held = []
                if time.time() - menu_t > 1.5 * SLOW:
                    if R(0x300) == 1: pass                  # the demo: START leaves it for the title
                    elif (rd(0x14, 1) or b"\0")[0] == 10:  # the level menu: its cursor (3A, 0-4) wraps, so read it
                        for _ in range(8):
                            cur = (rd(0x3A, 1) or b"\0")[0]
                            if cur == CPU - 1: break
                            pad.tap("right", TAP); time.sleep(TAP)
                    elif (rd(0x39, 1) or b"\0")[0] == 1:   # the title on doubles (39; SELECT toggles): singles
                        pad.tap("select", TAP); time.sleep(TAP)
                    pad.tap("start", TAP); menu_t = time.time()
                time.sleep(0.05); continue
            us, them = R(0x58), R(0x59); h = R(0x6F); vz = (R(0x6C) * 256 + R(0x6D)) - (65536 if R(0x6C) > 127 else 0)
            if last and "bounce" not in last and vz0 < 0 <= vz: last["bounce"] = (gx, gy)   # where our return came down
            vz0 = vz
            gx, gy = R(0x70), R(0x71); my, mx = R(0x308), R(0x309); cx = R(0x349)
            if gy0 is None or gy != gy0:                    # depth direction from the last change (slow motion repeats)
                d = 0 if gy0 is None else (gy > gy0) - (gy < gy0)
                if gy0 is not None and abs(gy - gy0) > 16: d = 0; dirn = 0      # the ball put back in the server's hand
                if d and d != dirn:
                    if d == 1 and abs(gy - my) > 40:        # the computer hit (or served): the model picks our return
                        busy = worker is not None and worker.is_alive()
                        shot = dict(t=time.time(), y0=gy, c=None, path=[(gx, gy)], vy=0, box={}, aim=None, busy=busy, swung=False, cx=cx, asked=False)
                        if last and "went" not in last: last["went"] = gx
                    dirn = d
                gy0 = gy
            if shot and not shot["swung"] and dirn == 1:
                path = shot["path"]
                if gy != path[-1][1]:
                    shot["vy"] = gy - path[-1][1]; path.append((gx, gy))   # px per read: the swing anticipates the next one
                    # where the ball will meet our feet (ground travel is straight): from the hit on, once it has come 4 px
                    if gy - path[0][1] >= 4:
                        shot["c"] = max(30, min(230, round(gx + (gx - path[0][0]) * (my - gy) / (gy - path[0][1]))))
            if shot and not shot["asked"]:                  # asked at once (the spots from where we stand, refined later)
                sp = spots(mx); shot["asked"] = True; shot["sp"] = dict(sp)
                shot["order"] = sorted(sp, key=lambda a: (a != "left") ^ (n % 2))
                if USE_MODEL and not shot["busy"]:
                    text = facts(us, them, cx, sp, shot["order"]); box = shot["box"]
                    def think(text=text, box=box):
                        t1 = time.time()
                        try: box["ans"] = ask(text)
                        except Exception as ex: box["ans"] = "ERROR %s" % ex
                        box["dt"] = time.time() - t1; thinks.append(box["dt"]); save(CALIB, thinks[1:][-50:])
                    worker = threading.Thread(target=think, daemon=True); worker.start()
            if shot and not shot["swung"] and dirn == 1 and shot["c"] is not None:
                c = shot["c"]; sp = spots(c)
                shot["impulse"] = max(sp, key=lambda a: abs(sp[a] - cx))   # the impulse: the end farther from the computer
            if shot and shot["aim"] is None and "dt" in shot["box"] and "order" in shot:   # the answer is in
                m = re.search(r"PICK\s*\(?([AB])\)?", shot["box"]["ans"])
                if m:
                    shot["aim"] = shot["order"]["AB".index(m.group(1))]
                    say("%s." % shot["aim"].capitalize(), show="%s: %s, to %d, computer at %d" % (
                        MODEL, shot["aim"], pos(shot["sp"][shot["aim"]]), pos(cx)), spoken=SLOW >= 2)
                else: shot["box"]["dt"] = None; shot["aim"] = False      # no pick: the impulse
            btn = []
            toss = abs(gy - my) < 24 and dirn == 0 and h > h0 and h >= SERVE_H
            if toss and not served:
                btn = ["a"]; served = True; shot = None     # serve near the toss's fastest height
            if h <= 96: served = False
            h0 = h
            if shot and not shot["swung"] and dirn == 1 and "impulse" in shot:     # run to the meeting point; swing to the model's spot, or on impulse
                c = shot["c"]                                # the stroke on our side of the ball, kept once it is close
                if my - gy > 40 or not shot.get("stroke"): shot["stroke"] = "forehand" if mx <= c else "backhand"
                stroke = shot["stroke"]; tx = c + STAND[stroke]
                if mx < tx - 2: btn.append("right")
                elif mx > tx + 2: btn.append("left")
                aim = shot["aim"] or shot["impulse"]; target = sp[aim]
                p = reach_for(stroke, c, target)
                if -6 <= my - gy - shot["vy"] / 2 <= p:
                    rushed = not shot["aim"]
                    btn = ["a"]; shot["swung"] = True
                    w = time.time() - shot["t"]; windows.append(w / SLOW); save(WCALIB, windows[-50:])
                    rec[aim]["n"] += 1; n += 1; late += rushed; last = dict(aim=aim, late=rushed, target=round(target))
                    if rushed and USE_MODEL:
                        if not told:
                            told = True; say("No time to think it through. I hit it away from the computer.", spoken=True)
                        say("", show="%s: no time, %s, away from the computer" % (MODEL, aim), spoken=False)
                    log(dict(shot=n, aim=aim, stroke=stroke, late=rushed, busy=shot["busy"], window_s=round(w / SLOW, 2), cx=cx, c=c,
                             gx=gx, dx=gx - mx, reach=p, target=round(target), think_s=round(shot["box"]["dt"], 1) if shot["box"].get("dt") else None,
                             answer=shot["box"].get("ans"), level=LEVEL, slow=SLOW))
            if (not shot or shot["swung"]) and dirn == -1 and abs(mx - MID) > 4:   # our shot on its way: back to the middle
                btn.append("right" if mx < MID else "left")
            if btn != held:
                if "a" in btn: pad.hold(btn); time.sleep(TAP); btn = [b for b in btn if b != "a"]
                pad.hold(btn); held = btn
            pts = (us, them)
            if prev is not None and pts != prev:             # a point ended
                if them > prev[1]: w = False
                elif us > prev[0]: w = True
                elif us == them == 0: w = prev[0] > prev[1]      # a game ended (back to love): the leader won it
                else: w = them < prev[1]                     # an advantage lost (back to deuce)
                game = us == them == 0; won += w; lost += not w
                if last: rec[last["aim"]]["won" if w else "lost"] += 1
                line = ("Game to %s." if game else "Point to %s.") % ("me" if w else "the computer")
                if last and USE_MODEL: line += " My last shot went %s%s." % (last["aim"], ", on impulse" if last["late"] else "")
                say(line, show="%s: %s" % (MODEL, line))
                log(dict(point="us" if w else "computer", game=game, last=last and last["aim"], impulse=bool(last and last["late"]),
                         target=last and last.get("target"), bounce=last and last.get("bounce"),
                         score=[us, them], won=won, lost=lost, level=LEVEL, slow=SLOW, cpu=CPU))
                last = None; shot = None; dirn = 0; gy0 = None
                if game: told = False
            prev = pts
            time.sleep(0.008)
    finally:
        pad.release_all()
        if os.environ.get("KEEP_RUNNING") != "1" and "PAUSED" not in (ra.cmd("GET_STATUS") or ""): ra.cmd("PAUSE_TOGGLE", reply=False)
        if LOG: LOG.close()
    print("%d returns in %.0f s, %d late, points %d-%d, mean think %.1f s, mean window %.2f s; %s" % (
        n, time.time() - t0, late, won, lost, sum(thinks) / max(len(thinks), 1), sum(windows) / max(len(windows), 1), json.dumps(rec)))
