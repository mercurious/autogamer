#!/usr/bin/env python3
# Runs on the handheld: the language model aims every return in Activision Tennis (Atari 2600, stella); play.py's
# reflex loop (decide()) still runs to the ball and the swing is automatic. When blue hits (or serves), the model gets
# the score, where blue stands and its own record so far (points won and lost after each aim), and picks left, middle
# or right, each with where it sends the ball and how far that is from blue; the reflex loop then meets the ball with
# that hit offset (+2 left, +5 middle, +12 right; +7 sent the ball right as much as +12, 2026-10-09). If the model has
# not answered, pink stands well off the ball (hit offset -16 or +30, on the side with room; -2 still got hit, the
# racket flips sides) and blue wins the point: no decision, no shot, as a Tetris piece the model is too late for falls where it is. An answer that comes
# late in the window may still get the racket there.
# The game never pauses: it runs in RetroArch's slow motion at the level's ratio (level.py, run.sh tennis-model), so
# the level is how much of blue's shot the model's thinking takes. Points are spoken from the facts (TL_TTS=1).
# Each answer updates this session's mean think time (TL_CALIB) and each shot the mean game time from blue's hit to
# ours (TN_WCALIB); the next launch sets the levels from them.
# Usage: tennis_llm.py SECONDS [log.jsonl]     env: TL_RUN, TL_CALIB, TN_WCALIB, TL_TTS, AG_MODEL_LABEL, VS_PORT
import json, os, random, re, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from ra import RA; from pad import Pad; import llm, voice
import play
LLM = "http://127.0.0.1:%s" % os.environ.get("VS_PORT", "8099"); TTS = os.environ.get("TL_TTS", "0") == "1"
MODEL = os.environ.get("AG_MODEL_LABEL", "model"); RUN = os.environ.get("TL_RUN")
CALIB = os.environ.get("TL_CALIB"); WCALIB = os.environ.get("TN_WCALIB")
AIMS = {"left": play.AIM_L, "middle": -5, "right": play.AIM_R}; LATE_AIM = "middle"   # DX = -(hit offset)
NOSHOT = lambda bx: 16 if bx < 100 else -30   # DX while the model has not answered: hits need offset 0..14 (court x 9-161)
LANDS = {"left": 20, "middle": 50, "right": 80}     # where each aim roughly sends the ball, court position 0-100
LEAD_F = 12.8              # play.py's LEAD 10 polls at 47 Hz, in game frames
CALL = ["love", "15", "30", "40"]; WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven"]
SYSTEM = ("You are the pink player in the 1981 Atari 2600 game Tennis, against the game's computer (blue). Your "
          "racket swings by itself; your only choice is where each return goes: to the left of the screen, down the "
          "middle, or to the right. A return aimed away from where blue stands makes him run for it and wins "
          "points; one aimed at him comes straight back. Each shot you get the score, where blue and you stand "
          "(court position 0-100, left to right), your record so far (returns, then points won and lost after each aim), "
          "and three lettered aims with where each sends the ball and how far that is from blue. "
          "Reply exactly as: PICK <letter>")
# The fixed text is all in SYSTEM and the request is cached (llm.chat cache=True): each shot reads only ~70 tokens of
# facts and the reply is the letter alone (the 330-token prompt was ~85 % of the think time, 2026-10-09).

def level():
    """(name, ratio) of the level now playing, or (None, 1) without levels."""
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

def score_text(r):
    p, b, gp, gb = r[0x45], r[0x46], r[0x47], r[0x48]
    games = "games %d all" % gp if gp == gb else "%s leads %d games to %d" % (("you", gp, gb) if gp > gb else ("blue", gb, gp))
    if p >= 3 and b >= 3: pts = "deuce" if p == b else "advantage %s" % ("you" if p > b else "blue")
    else: pts = "%s-%s in this game (you first)" % (CALL[min(p, 3)], CALL[min(b, 3)])
    return "%s; %s" % (games.capitalize(), pts)

def where(x):
    """a player's x as the model reads it: left / centre / right of the court and 0-100"""
    pos = max(0, min(100, round((x + 4 - 9) * 100 / 152)))     # sprite left edge -> body, court x 9-161
    return ("left of centre" if x < play.MID - 6 else "right of centre" if x > play.MID + 6 else "in the centre"), pos

def facts(r, rec, order):
    e = play.END[r[0x50] & 1]; oy = r[e["y"] ^ 1]
    side, pos = where(r[e["opp"]]); mine, mpos = where(r[e["x"]])
    lines = ["Score: %s." % score_text(r),
             "Blue %d (%s, %s). You %d." % (pos, side, "near the net" if abs(oy - play.NET) < 30 else "baseline", mpos),
             "Record: " + ", ".join("%s %d %d %d" % (a, rec[a]["n"], rec[a]["won"], rec[a]["lost"]) for a in AIMS) + "."]
    for i, a in enumerate(order):
        lines.append("%s) %s: to %d, %d from blue" % ("ABC"[i], a, LANDS[a], abs(LANDS[a] - pos)))
    return "\n".join(lines)

def ask(text):
    return llm.chat(LLM, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}], 6, 0.3, 120, cache=True)[0]

def say(line, show=None, slow_ok=True):
    if TTS and slow_ok: voice.say(line, show=show, ra=ra)
    elif show: ra.cmd("SHOW_MSG " + show, reply=False)

if __name__ == "__main__":
    T = float(sys.argv[1]); LOG = open(sys.argv[2], "a") if len(sys.argv) > 2 else None
    ra, pad = RA(timeout=0.2), Pad()
    if "PAUSED" in (ra.cmd("GET_STATUS") or ""): ra.cmd("PAUSE_TOGGLE", reply=False)
    log = lambda d: LOG and (LOG.write(json.dumps(dict(t=round(time.time() - t0, 1), **d)) + "\n"), LOG.flush())
    LEVEL, SLOW = level()
    rec = {a: dict(n=0, won=0, lost=0) for a in AIMS}; thinks, windows = [], []
    t0 = time.time(); DX = AIMS[LATE_AIM]; hist = []; last_dir = 0; prev = None; set_over = None; start_until = 0
    shot = None        # blue's shot now coming: {"t", "f", "box", "aim", ...}
    last = None        # our last return: {"aim", "late"}
    n = late = 0; worker = None; relevel = False
    try:
        while time.time() - t0 < T:
            if RUN and os.path.exists(os.path.join(RUN, "restart")):        # level change (level.py)
                time.sleep(0.2); hist = []; relevel = True; continue
            if relevel: LEVEL, SLOW = level(); relevel = False
            r = ra.ram(0x80, 128)
            if not r: continue
            f, d, bx = r[0x04], r[0x37], r[0x10]
            e = play.END[r[0x50] & 1]; toward = 1 if e["home"] > play.NET else -1   # top end: depth grows toward us
            # ball depth per game frame, from the frame counter (in slow motion most polls see the same frame)
            if not hist or hist[-1][0] != f:
                if hist and (abs(d - hist[-1][1]) > 10 or d == 255): hist = []
                hist.append((f, d)); hist = hist[-4:]
            fr = (hist[-1][0] - hist[0][0]) & 255 if len(hist) > 1 else 0
            vd = (hist[-1][1] - hist[0][1]) / fr if fr else 0.0
            dirn = (vd > 0.3) - (vd < -0.3) if d != 255 and bx > 5 else 0
            if dirn and dirn != last_dir:
                if dirn == toward:              # blue hit (or served): the model picks where our return goes
                    busy = worker is not None and worker.is_alive()   # still on an earlier shot: no new question
                    shot = dict(t=time.time(), f=f, box={}, aim=None, busy=busy, opp=r[e["opp"]], order=random.sample(list(AIMS), 3))
                    if last and "went" not in last: last["went"] = bx - last["bx"]   # where our last return reached blue
                    if not busy:
                        text = facts(r, rec, shot["order"]); box = shot["box"]
                        def think(text=text, box=box):
                            t1 = time.time()
                            try: box["ans"] = ask(text)
                            except Exception as ex: box["ans"] = "ERROR %s" % ex
                            box["dt"] = time.time() - t1; thinks.append(box["dt"]); save(CALIB, thinks[1:][-50:])   # not the first: it fills the prompt cache
                        worker = threading.Thread(target=think, daemon=True); worker.start()
                elif last_dir == toward and shot:   # we hit it back: was the aim in time?
                    box = shot["box"]; in_time = "dt" in box and shot["aim"] is not None
                    aim = shot["aim"] if in_time else LATE_AIM
                    w = ((f - shot["f"]) & 255) / 60.0; windows.append(w); windows[:] = windows[-50:]; save(WCALIB, windows)
                    rec[aim]["n"] += 1; n += 1; late += not in_time
                    prev_went = last and last.get("went"); prev_aim = last and last["aim"]
                    last = dict(aim=aim, late=not in_time, bx=bx)
                    if not in_time:                 # it got there anyway (a wild return off the racket's edge)
                        say("Lucky.", show="%s: no answer in time, the ball hit the racket anyway" % MODEL, slow_ok=SLOW >= 4)
                    log(dict(shot=n, aim=aim, late=not in_time, prev_aim=prev_aim, prev_went=prev_went, busy=shot["busy"], window_s=round(w, 2), opp_x=shot["opp"],
                             think_s=round(box["dt"], 1) if "dt" in box else None, answer=box.get("ans"), level=LEVEL, slow=SLOW))
                    shot = None
                last_dir = dirn
            if shot and shot["aim"] is None and "dt" in shot["box"]:       # the answer is in: use it for this return
                box = shot["box"]; ans = box["ans"]
                m = re.search(r"PICK\s*\(?([ABC])\)?", ans); shot["aim"] = shot["order"]["ABC".index(m.group(1))] if m else LATE_AIM
                say("%s." % shot["aim"].capitalize(), show="%s: %s, blue at %d" % (MODEL, shot["aim"], where(shot["opp"])[1]), slow_ok=SLOW >= 4)
            DX = AIMS[shot["aim"]] if shot and shot["aim"] else NOSHOT(bx) if shot else AIMS[LATE_AIM]
            btns, DX = play.decide(r, DX, vd * LEAD_F / play.LEAD, str(DX))
            if (f // 24) % 2 == 0: btns.append("b")       # fire on and off by game frames: serves
            score = (r[0x45], r[0x46], r[0x47], r[0x48])
            if prev is not None and score != prev and score[2] + score[3] >= prev[2] + prev[3]:   # a point ended
                if score[2] != prev[2] or score[3] != prev[3]: won = score[2] > prev[2]
                elif score[0] > prev[0] or score[1] > prev[1]: won = score[0] > prev[0]
                else: won = score[1] < prev[1]          # an advantage falls back to deuce: the other player won it
                game = score[2] != prev[2] or score[3] != prev[3]
                missed = shot is not None and shot["aim"] is None and not won     # blue's shot came, no answer yet
                if last and not missed: rec[last["aim"]]["won" if won else "lost"] += 1
                if missed: late += 1
                W = "Pink" if won else "Blue"
                line = ("Game, %s! " % W if game else "Point %s. " % W)
                if game: line += ("%s games all." % WORDS[min(score[2], 7)].capitalize() if score[2] == score[3] else
                                  "%s leads %s to %s." % (("Pink", WORDS[min(score[2], 7)], WORDS[min(score[3], 7)]) if score[2] > score[3]
                                                          else ("Blue", WORDS[min(score[3], 7)], WORDS[min(score[2], 7)])))
                if missed: line += " %s." % ("I was still thinking about the last one" if shot["busy"] else "I had not decided yet")
                elif last: line += " I was too late to aim." if last["late"] else " My last shot went %s." % ("down the middle" if last["aim"] == "middle" else last["aim"])
                say(line, show="%s: %s" % (MODEL, line))
                log(dict(point="pink" if won else "blue", missed=missed, last_aim=last and last["aim"], last_late=last and last["late"], score=list(score), level=LEVEL, slow=SLOW))
                last = None; shot = None; last_dir = 0
            prev = score
            gp, gb = score[2], score[3]
            if max(gp, gb) >= 6 and abs(gp - gb) >= 2:           # set over: the game waits for a reset
                set_over = set_over or time.time()
                if time.time() - set_over > 10: start_until = time.time() + 0.1 * SLOW; set_over = None
            if time.time() < start_until: btns = ["start"]
            pad.hold(btns)
            time.sleep(0.012)
    finally:
        pad.release_all()
        if os.environ.get("KEEP_RUNNING") != "1" and "PAUSED" not in (ra.cmd("GET_STATUS") or ""): ra.cmd("PAUSE_TOGGLE", reply=False)
        if LOG: LOG.close()
    print("%d returns in %.0f s, %d late, mean think %.1f s, mean window %.2f s; %s" % (
        n, time.time() - t0, late, sum(thinks) / max(len(thinks), 1), sum(windows) / max(len(windows), 1), json.dumps(rec)))
