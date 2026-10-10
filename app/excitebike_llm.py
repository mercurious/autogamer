#!/usr/bin/env python3
# Runs on the handheld: the language model rides the turbo in Excitebike (Nintendo, 1984; fceumm), Selection A, the
# time trial against the qualifying time (3RD on the screen). A reflex loop rides: on the ground it keeps a light
# wheelie (the nose at 8, which clears the hurdles), in the air it tilts the bike for the landing (nose up onto a
# ramp's upslope). The model runs the engine: TURBO (B) is faster and heats it, CRUISE (A) is slower and cools it to
# 17; at 32 the engine overheats and the bike stops for about 4 s. Each answer holds until the next one arrives, so the
# model's own think time is the stake: a turbo it is too slow to call off overheats the engine. It is asked again as
# soon as it answers; each question says how long its next answer is likely to take, in race time, and what each
# choice would do to the temperature by then. The game runs in RetroArch's slow motion at the level's ratio (level.py,
# run.sh excitebike-model). Qualify and the game goes on to the next race; miss and it is game over, then the title.
# RAM (NES CPU addresses, mapped 2026-10-09 on a headless fceumm): 41 mode (0 title, 1 track select, 2 or 5 race, 3
# game over, 8 and 10 design), 42 title cursor (0 Selection A) or track (0-4), 43 race in the series, 52 results
# screen, 58 obstacle under the bike, 68/69/6A race time min/s/hundredths, 70 lane, AC bike angle (6 level, 2-11;
# left raises the nose), B0 2 in the air, F3 speed, 3B5-3B6 temperature (32.0 overheats), 580/590 course records
# (min, s, hundredths; 3RD = record + 8 s: 580+3*track for the first race after the track select, else
# 590+3*(track+race)). Hurdles are lane tiles, not in 58: the wheelie clears them in every lane.
# Usage: excitebike_llm.py SECONDS [log.jsonl]   env: TL_RUN, TL_CALIB, TL_TTS, TL_THINK0, AG_MODEL_LABEL, VS_PORT,
#   EB_TRACK (the track the series starts on, 1-5, default 1)
import json, os, random, re, socket, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from ra import RA; from pad import Pad; import llm, voice
LLM = "http://127.0.0.1:%s" % os.environ.get("VS_PORT", "8099"); TTS = os.environ.get("TL_TTS", "0") == "1"
MODEL = os.environ.get("AG_MODEL_LABEL", "model"); RUN = os.environ.get("TL_RUN"); CALIB = os.environ.get("TL_CALIB")
TRACK = min(max(int(os.environ.get("EB_TRACK", "1")), 1), 5) - 1
THINK0 = float(os.environ.get("TL_THINK0", "4"))
HOT, HEAT, COOL, WARM, REST = 32, 3.5, 2.6, 1.6, 17   # overheat; per race second: turbo, cruise above / below REST
WHEELIE = 8                                           # nose angle held on the ground (clears hurdles; 7 does not)
SYSTEM = ("You are racing in Excitebike (NES, 1984), a motocross time trial. A reflex rider steers, jumps and lands; you "
          "run the engine. Turbo is faster but heats the engine; cruising is slower and cools it. If the temperature "
          "reaches 32 the engine overheats and the bike stops for about 4 seconds, which costs more than turbo gains. "
          "Your answer takes effect when it arrives and holds until the next one. Each turn you get the temperature, the "
          "race time and the qualifying time, how long an answer takes in race seconds, the temperature when this one "
          "arrives, and two lettered choices with the temperature each leads to by the answer after. "
          "Reply exactly as: PICK <letter>")

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

def secs(m, s, cs): return m * 60 + s + cs / 100.0

def clock(t): return "%d:%05.2f" % (t // 60, t % 60)

def target(z):
    """the qualifying time (3RD) of the race now on: the course record + 8 s, or None"""
    first = z[0x43] == 0 and z[0x41] == 2
    a = 0x580 + 3 * z[0x42] if first else 0x590 + 3 * (z[0x42] + z[0x43])
    rec = rd(a, 3)
    return secs(*rec) + 8 if rec and rec[1] < 60 and rec[2] < 100 else None

def ahead(temp, plan, d):
    """the temperature after d race seconds of turbo or cruise"""
    if plan == "turbo": return temp + HEAT * d
    return max(REST, temp - COOL * d) if temp > REST else min(REST, temp + WARM * d)

def facts(temp, plan, t, goal, d, heats, order):
    """the question, and the temperature when its answer arrives (the plan now on holds until then)"""
    land = ahead(temp, plan, d)
    lines = ["Temperature %.0f of 32, engine on %s. Overheats so far: %d." % (temp, plan, heats),
             "Race time %s%s." % (clock(t), ", qualifying time %s" % clock(goal) if goal else ""),
             "An answer takes about %.1f race seconds: when this one arrives the temperature will be about %.0f%s." % (
                 d, min(land, HOT), " (it overheats first)" if land >= HOT else "")]
    for i, p in enumerate(order):
        x = ahead(min(land, HOT), p, d)
        lines.append("%s) %s: about %.0f by the answer after%s" % ("AB"[i], p, min(x, HOT), ", overheats" if x >= HOT else ""))
    return "\n".join(lines), land

def ask(text):
    return llm.chat(LLM, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}], 6, 0.3, 120, cache=True)[0]

def say(line, show=None, spoken=True):
    if TTS and spoken: voice.say(line, show=show, ra=ra)
    elif show: ra.cmd("SHOW_MSG " + show, reply=False)

def reflex(z, throttle):
    """the rider: buttons for this moment (throttle "a" or "b")"""
    btn = [throttle]; ang = z[0xAC]
    if z[0xB0] == 2:                                  # in the air: nose up onto an upslope, else a little nose up
        want = 10 if z[0x58] in (0x09, 0x0A, 0x0C) else 8
        if ang < want: btn.append("left")
        elif ang > want: btn.append("right")
    elif ang < WHEELIE: btn.append("left")            # on the ground: the light wheelie
    return btn

if __name__ == "__main__":
    T = float(sys.argv[1]); LOG = open(sys.argv[2], "a") if len(sys.argv) > 2 else None
    ra, pad = RA(timeout=0.2), Pad()
    if "PAUSED" in (ra.cmd("GET_STATUS") or ""): ra.cmd("PAUSE_TOGGLE", reply=False)
    log = lambda d: LOG and (LOG.write(json.dumps(dict(t=round(time.time() - t0, 1), **d)) + "\n"), LOG.flush())
    LEVEL, SLOW = level()
    t0 = time.time(); worker = None; relevel = False; menu_t = 0; held = []; thinks = []
    ours = False       # a race we started (the title's demo race is not ours)
    race = None        # this race: {"goal", "heats", "crashes", "picks", "turbo_s"}
    plan = "cruise"; box = None; prev = None; mode_t = time.time(); last_mode = None; n = 0
    last = None        # the answer now holding: {"pick", "risky" (turbo though it said overheats), "at"}
    series = 0         # races in this series (back to 0 at the title)
    try:
        while time.time() - t0 < T:
            if RUN and os.path.exists(os.path.join(RUN, "restart")):
                time.sleep(0.2); relevel = True; continue
            if relevel: LEVEL, SLOW = level(); relevel = False
            z = rd(0x00, 0x100); h = rd(0x3B5, 2)
            if not z or not h: continue
            TAP = 0.1 * SLOW; mode = z[0x41]
            if mode != last_mode: last_mode = mode; mode_t = time.time()
            if mode not in (2, 5) or not ours:            # menus: Selection A, then the track; game over waits
                if held: pad.hold([]); held = []
                if mode == 0: ours = False; series = 0
                if mode in (8, 10) and time.time() - mode_t > 2 * SLOW:      # the design screen: reset to the title
                    ra.cmd("RESET", reply=False); ra.cmd("RESET", reply=False); mode_t = time.time()
                elif mode in (0, 1) and time.time() - menu_t > 1.0 * SLOW:
                    want = 0 if mode == 0 else TRACK
                    b = "start" if z[0x42] == want else "down" if mode == 0 else "right" if z[0x42] < want else "left"
                    pad.tap(b, TAP); menu_t = time.time()
                    if mode == 1 and b == "start": ours = True
                time.sleep(0.05); continue
            temp = h[1] + h[0] / 256.0; t = secs(z[0x68], z[0x69], z[0x6A])
            if z[0x52]:                                   # the results screen: the race is over
                if held: pad.hold([]); held = []
                if race and "time" not in race:
                    race["time"] = t; goal = race["goal"]
                    if goal: line = ("Finished in %.1f seconds. Qualified, with %.1f to spare." % (t, goal - t) if t <= goal else
                                     "Finished in %.1f seconds, %.1f over the qualifying time. Game over." % (t, t - goal))
                    else: line = "Finished in %.1f seconds." % t
                    if race["heats"]: line += " %d overheat%s." % (race["heats"], "" if race["heats"] == 1 else "s")
                    say(line, show="%s: %s" % (MODEL, line))
                    log(dict(finish=round(t, 2), goal=goal, qualified=goal is not None and t <= goal, overheats=race["heats"],
                             crashes=race["crashes"], picks=race["picks"], turbo_s=round(race["turbo_s"], 1), level=LEVEL, slow=SLOW,
                             race=series))
                    race = None
                time.sleep(0.05); continue
            if race is None:                              # a new race: its qualifying time, the model starts cautious
                race = dict(goal=target(z), heats=0, crashes=0, picks=0, turbo_s=0.0); plan = "cruise"; prev = None; last = None; box = None
                series += 1; said = "Race %d." % series
                if race["goal"]: said += " Qualifying time %.0f seconds." % race["goal"]
                say(said, show="%s: %s" % (MODEL, said))
                log(dict(race=series, ram=[z[0x41], z[0x42], z[0x43]], goal=race["goal"], level=LEVEL, slow=SLOW))
            running = t > 0
            if running and temp < HOT and (worker is None or not worker.is_alive()):
                if box is not None and "ans" in box:       # the answer is in: it holds until the next one
                    m = re.search(r"PICK\s*\(?([AB])\)?", box["ans"])
                    new = box["order"]["AB".index(m.group(1))] if m else "cruise"
                    race["picks"] += 1; n += 1
                    if new != plan:
                        show = "%s: %s, temperature %.0f" % (MODEL, new, temp)
                        say("Turbo." if new == "turbo" else "Easing off.", show=show, spoken=SLOW >= 2)
                    plan = new; last = dict(pick=new, risky=new == "turbo" and ahead(box["land"], "turbo", box["d"]) >= HOT, at=time.time())
                    log(dict(pick=new, parsed=bool(m), think_s=round(box["dt"], 1), temp_asked=round(box["temp"], 1), temp_land=round(min(box["land"], HOT), 1),
                             temp_now=round(temp, 1), next_s=round(box["d"], 1), answer=box["ans"], level=LEVEL, slow=SLOW))
                expect = sum(thinks[1:][-20:]) / len(thinks[1:][-20:]) if len(thinks) > 1 else THINK0
                d = expect / SLOW; order = random.sample(["turbo", "cruise"], 2)
                text, land = facts(temp, plan, t, race["goal"], d, race["heats"], order)
                box = dict(order=order, temp=temp, d=d, land=land)
                def think(text=text, box=box):
                    t1 = time.time()
                    try: box["ans"] = ask(text)
                    except Exception as ex: box["ans"] = "ERROR %s" % ex
                    box["dt"] = time.time() - t1; thinks.append(box["dt"]); save(CALIB, thinks[1:][-50:])
                worker = threading.Thread(target=think, daemon=True); worker.start()
            if prev is not None:
                if temp >= HOT and prev_temp < HOT:       # overheated: the engine stops
                    race["heats"] += 1; held_s = (time.time() - last["at"]) / SLOW if last else 0
                    if last and last["risky"]: line = "Overheated! I took the turbo past the limit."
                    else: line = "Overheated! The turbo stayed on while I was still thinking."
                    say(line, show="%s: %s" % (MODEL, line))
                    log(dict(overheat=race["heats"], plan=plan, risky=bool(last and last["risky"]), turbo_held_s=round(held_s, 1),
                             temp=round(temp, 1), level=LEVEL, slow=SLOW))
                if prev[0xF3] > 8 and z[0xF3] == 0 and z[0xB0] != 2 and temp < HOT:
                    race["crashes"] += 1; ra.cmd("SHOW_MSG %s: the rider fell" % MODEL, reply=False)
                    log(dict(crash=race["crashes"], speed=prev[0xF3], angle=prev[0xAC], obstacle=prev[0x58], level=LEVEL, slow=SLOW))
                if plan == "turbo" and running: race["turbo_s"] += (time.time() - loop_t) / SLOW
            btn = reflex(z, "b" if plan == "turbo" and temp < HOT else "a")
            if btn != held: pad.hold(btn); held = btn
            prev = z; prev_temp = temp; loop_t = time.time()
            time.sleep(0.004)
    finally:
        pad.release_all()
        if os.environ.get("KEEP_RUNNING") != "1" and "PAUSED" not in (ra.cmd("GET_STATUS") or ""): ra.cmd("PAUSE_TOGGLE", reply=False)
        if LOG: LOG.close()
    print("%d engine calls in %.0f s, mean think %.1f s" % (n, time.time() - t0, sum(thinks) / max(len(thinks), 1)))
