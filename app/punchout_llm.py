#!/usr/bin/env python3
# Runs on the handheld: the language model runs Little Mac's offence in Mike Tyson's Punch-Out!! (Nintendo, 1987;
# fceumm). A reflex loop defends: it dodges every punch it knows at the right frame (a dodge works from 29 to 7 frames
# before the punch lands, against every punch mapped). The model decides when it is clear to attack: when the opponent
# is open (reeling after a dodge, or standing off defence) the game drops into bullet time (RetroArch's slow motion at
# the level's ratio) and the model calls PUMMEL (rapid jabs to the face until they are blocked), BODY (rapid body
# blows) or WAIT, with its record in that situation: tries, hits, blocks. Against Glass Joe the face takes 5-6 hits
# after a dodge and 3 while he stands, the body none while he stands; others guard differently. A call that comes
# after the opening has closed is too late. While the model is still busy, its last call holds. Win and the next
# opponent comes out; lose and it is a rematch; a third loss is game over, then a new game from Glass Joe (the game's
# own rules). The reflex loop also throws the jabs (a star uppercut first when Mac has one), gets Mac up after a
# knockdown and presses START on the screens between rounds and fights.
# RAM (NES CPU addresses; TASVideos' map, timing mapped 2026-10-10 on a headless fceumm): 00 1 in a fight (48 the
# intro, 253 Mac lost, 254 Mac won), 01 opponent (0 Glass Joe .. 13 Tyson), 05 1 opponent down, 2 Mac down, 06 round,
# 1E frame counter, 90 the opponent's move (01 idle, a punch id while it winds up and throws; 80 bit set between
# moves), 300 clock running, 302/304/305 clock m:s s, 323/324 hearts (tens, units), 342 stars, 391 Mac's health and
# 398 the opponent's (0-96), 3C0 losses. A dodge (left, 4 frames) works from 29 to 7 frames before the punch lands,
# whatever its direction, against every punch mapped; a block only softens it. PUNCH: frames from the move's start to
# its impact (the fewest seen; Mac idle).
# Usage: punchout_llm.py SECONDS [log.jsonl]   env: TL_RUN, TL_CALIB, TL_TTS, TL_THINK0, AG_MODEL_LABEL, VS_PORT
import json, os, random, re, socket, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from ra import RA; from pad import Pad; import llm, voice
LLM = "http://127.0.0.1:%s" % os.environ.get("VS_PORT", "8099"); TTS = os.environ.get("TL_TTS", "0") == "1"
MODEL = os.environ.get("AG_MODEL_LABEL", "model"); RUN = os.environ.get("TL_RUN"); CALIB = os.environ.get("TL_CALIB")
THINK0 = float(os.environ.get("TL_THINK0", "4"))
NAMES = ["Glass Joe", "Von Kaiser", "Piston Honda", "Don Flamenco", "King Hippo", "Great Tiger", "Bald Bull",
         "Piston Honda", "Soda Popinski", "Bald Bull", "Don Flamenco", "Mr. Sandman", "Super Macho Man", "Mike Tyson"]
CIRCUIT = ["Minor Circuit"] * 3 + ["Major Circuit"] * 4 + ["World Circuit"] * 6 + ["Dream Fight"]
PUNCH = {0: {0x15: 36, 0x16: 58}, 1: {0x16: 33, 0x17: 39},
         2: {0x15: 43, 0x16: 50, 0x17: 43, 0x18: 13, 0x1A: 13, 0x1B: 57}, 3: {0x06: 42},
         4: {0x15: 40, 0x16: 40, 0x17: 47, 0x18: 47, 0x19: 84}, 5: {0x16: 41, 0x17: 31, 0x18: 31},
         6: {0x15: 33, 0x16: 38, 0x17: 24},
         7: {0x15: 30, 0x16: 19, 0x17: 30, 0x18: 9, 0x19: 81, 0x1A: 11, 0x1C: 47, 0x1D: 76},
         8: {0x15: 27, 0x16: 19, 0x18: 24, 0x1A: 105}, 9: {0x15: 27, 0x16: 29, 0x17: 21},
         10: {0x06: 38, 0x15: 27, 0x16: 33}, 11: {0x15: 25, 0x16: 23, 0x18: 23, 0x1A: 11, 0x1B: 11, 0x1C: 25, 0x1F: 28},
         12: {0x15: 23, 0x17: 20, 0x18: 20, 0x19: 28, 0x1B: 52}, 13: {0x16: 38, 0x17: 22}}
EARLY, LATE = 29, 8          # the dodge window: frames before the impact (7, and a frame for the poll)
FIRST = 12                   # dodge this many frames before the impact (or at once when later than that)
SPREAD = 10                  # a punch can land up to this many frames after its fastest (Glass Joe: 36-44)
BLOCKED = 45                 # counters stop when this many frames pass without damage (it shows 20-30 after the jab)
OPEN, PROBE = 30, 240        # standing this many frames: an offence turn; then none for this many
REEL = 100                   # an opening after a dodge lasts at least this long (Glass Joe: a pummel 100 frames on landed)
JAB = 10                     # a jab every this many frames, held 4
OFFENCE = ("pummel", "body", "wait")
SAY = {"body": "To the body!", "pummel": "Pummel him!", "wait": "Wait."}
TEXT = {"body": "body blows", "pummel": "pummel his face (rapid jabs)", "wait": "wait"}
SYSTEM = ("You are Little Mac in Mike Tyson's Punch-Out!! (NES, 1987). Mac dodges punches by himself; you run the "
          "offence. When your opponent is open (reeling after a dodge, or standing) the game slows down and you call: "
          "PUMMEL throws rapid jabs at his face until he blocks, BODY rapid body blows, WAIT holds back. Blocked punches "
          "cost hearts; at zero Mac cannot punch. Knock him down to win. A call that arrives after the opening has closed "
          "is wasted. Each turn you get the score, the situation, your record in it, and three lettered choices. Reply "
          "exactly as: PICK <letter>")

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

def ask(text):
    return llm.chat(LLM, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}], 6, 0.3, 120, cache=True)[0]

def say(line, show=None, spoken=True):
    if TTS and spoken: voice.say(line, show=show, ra=ra)
    elif show: ra.cmd("SHOW_MSG " + show, reply=False)

def record_text(rec, choices):
    parts = []
    for c in choices:
        r = rec.get(c)
        if not r: parts.append("%s never tried" % c); continue
        bits = ["%d tries" % r["n"]] + ["%d %s" % (r[k], k) for k in ("safe", "landed", "star", "hits", "blocked", "hit", "late") if r.get(k)]
        parts.append("%s %s" % (c, ", ".join(bits)))
    return "; ".join(parts)

def score(opp, z, h):
    who = NAMES[opp]
    return "%s, %s. Round %d, %d:%d%d. Mac health %d of 96, hearts %d, stars %d. %s health %d of 96." % (
        who, CIRCUIT[opp], max(z[0x06], 1), h[2], h[4], h[5], h[0x91], h[0x23] * 10 + h[0x24], h[0x42], who, h[0x98])

def ofacts(opp, kind, z, h, arrive, rec, order):
    """an offence turn: how he is open, when the call arrives"""
    who = NAMES[opp]
    lines = [score(opp, z, h),
             ("%s is reeling from your dodge." if kind == "reel" else "%s is standing, not punching.") % who,
             "Your call arrives about %.2f s from now." % (arrive / 60.0),
             "Your record when he is %s: %s." % ("reeling" if kind == "reel" else "standing", record_text(rec, OFFENCE))]
    return "\n".join(lines + ["%s) %s" % ("ABC"[i], TEXT[c]) for i, c in enumerate(order)])

class Speed:
    """bullet time: RetroArch's slow motion (a toggle) on while a punch winds up. The frame counter's rate shows which
    way it really is; a toggle that went astray is put right after a while."""
    def __init__(self): self.slow = False; self.want = False; self.marks = []; self.t_bad = None
    def set(self, want, ratio):
        self.want = want and ratio > 1
        if self.want != self.slow: ra.cmd("SLOWMOTION", reply=False); self.slow = self.want; self.marks = []; self.t_bad = None
    def check(self, frames, ratio):
        now = time.time(); self.marks.append((now, frames)); self.marks = [m for m in self.marks if now - m[0] < 0.6]
        if ratio <= 1.5 or now - self.marks[0][0] < 0.4: return
        fps = (self.marks[-1][1] - self.marks[0][1]) / (self.marks[-1][0] - self.marks[0][0])
        if fps < 0.5: return                           # paused, or the counter stands (no fight): no telling
        slow = fps < 60 / (1 + ratio) * 2
        if slow == self.slow: self.t_bad = None; return
        if self.t_bad is None: self.t_bad = now
        elif now - self.t_bad > 0.5:                   # RetroArch is the other way: toggle until it agrees
            ra.cmd("SLOWMOTION", reply=False); self.marks = []; self.t_bad = None

if __name__ == "__main__":
    T = float(sys.argv[1]); LOG = open(sys.argv[2], "a") if len(sys.argv) > 2 else None
    ra, pad = RA(timeout=0.2), Pad()
    if "PAUSED" in (ra.cmd("GET_STATUS") or ""): ra.cmd("PAUSE_TOGGLE", reply=False)
    log = lambda d: LOG and (LOG.write(json.dumps(dict(t=round(time.time() - t0, 1), **d)) + "\n"), LOG.flush())
    LEVEL, SLOW = level(); speed = Speed()
    t0 = time.time(); worker = None; relevel = False; menu_t = 0; held = []; thinks = []
    records = {}       # (opponent, move) or (opponent, "reel" / "stand") -> {choice: {"n", "safe", "hits", ...}}
    nums = {}          # (opponent, move) -> its number for the model (1, 2, ... in order of first sight)
    frames = 0; fc = None; prev_m = None; fight = None; n = 0; polls = 0; idle = None; move = None; last_hp = 0
    stop_t = time.time(); probe = 0
    turn = None        # the model's turn now on: {"kind" ("punch", "reel", "stand"), "f0", "box", "choice", ...}
    attack = None      # Mac's jabs: {"choice", "next", "at", "btn", "last" (damage seen), "ohp", "hits", "star"}
    calls = {"open": None}     # the last answer: it holds while the model is busy
    pending = []       # questions whose answers have not come yet

    def think_s():
        return sum(thinks[1:][-20:]) / len(thinks[1:][-20:]) if len(thinks) > 1 else THINK0

    def ask_turn(tn, text, order):
        global worker
        box = dict(order=order, turn=tn); tn["box"] = box; pending.append(box)
        def think(text=text, box=box):
            t1 = time.time()
            try: box["ans"] = ask(text)
            except Exception as ex: box["ans"] = "ERROR %s" % ex
            box["dt"] = time.time() - t1; thinks.append(box["dt"]); save(CALIB, thinks[1:][-50:])
        worker = threading.Thread(target=think, daemon=True); worker.start()

    def busy(): return worker is not None and worker.is_alive()

    def open_turn(kind, z, h):
        """an offence turn: bullet time and a question, or the last offence call when the model is busy"""
        global turn
        turn = dict(kind=kind, f0=frames, key=(z[0x01], kind), choice=None, done=False)
        records.setdefault(turn["key"], {})
        if busy(): turn["choice"] = calls["open"]; return
        speed.set(True, SLOW); order = random.sample(OFFENCE, 3)
        ask_turn(turn, ofacts(min(z[0x01], 13), kind, z, h, think_s() * 60 / SLOW, records[turn["key"]], order), order)

    def start_attack(c, h, star=False):
        global attack
        attack = dict(choice=c, next=frames, at=-99, btn=[], last=frames, ohp=h[0x98], hits=0, star=star, hand=0)

    def end_attack():
        """the jabs stopped: their record in the offence turn they answered"""
        global attack
        if attack and turn and turn["kind"] != "punch" and turn.get("choice") == attack["choice"] and not turn["done"]:
            r = records[turn["key"]].setdefault(attack["choice"], dict(n=0)); r["n"] += 1
            r["hits"] = r.get("hits", 0) + attack["hits"]
            if attack["hits"] == 0: r["blocked"] = r.get("blocked", 0) + 1
            turn["done"] = True
            log(dict(attack=attack["choice"], kind=turn["kind"], opp=turn["key"][0], hits=attack["hits"], level=LEVEL, slow=SLOW))
            if attack["hits"] >= 2: ra.cmd("SHOW_MSG %s: %d hits!" % (MODEL, attack["hits"]), reply=False)
        attack = None

    try:
        while time.time() - t0 < T:
            if RUN and os.path.exists(os.path.join(RUN, "restart")):
                time.sleep(0.2); relevel = True; continue
            if relevel: LEVEL, SLOW = level(); relevel = False; speed = Speed()
            z = rd(0x00, 0x100); h = rd(0x300, 0xE0)
            if not z or not h: continue
            polls += 1
            if fc is not None: frames += (z[0x1E] - fc) % 256
            fc = z[0x1E]; speed.check(frames, SLOW)
            opp = min(z[0x01], 13); m = z[0x90]; hp = h[0x91]; btn = []
            for b in [b for b in pending if "ans" in b]:                  # answers that came in
                pending.remove(b); tn = b["turn"]; kinds = OFFENCE
                mm = re.search(r"PICK\s*\(?([ABC])\)?", b["ans"])
                pick = b["order"]["ABC".index(mm.group(1))] if mm else kinds[0]
                calls["open"] = pick; n += 1
                if fight: fight["calls"] += 1
                at = frames - tn["f0"]
                in_time = tn is turn and not tn["done"]
                if in_time:                                    # the jabs start now (or Mac waits)
                    tn["choice"] = pick; speed.set(False, SLOW)
                    if pick == "wait": tn["done"] = True; r = records[tn["key"]].setdefault("wait", dict(n=0)); r["n"] += 1
                    else: start_attack(pick, h)
                else:
                    r = records[tn["key"]].setdefault(pick, dict(n=0)); r["n"] += 1; r["late"] = r.get("late", 0) + 1
                    if fight: fight["late"] += 1
                say(SAY[pick], show="%s: %s%s" % (MODEL, pick.upper(), "" if in_time else " - too late"), spoken=SLOW >= 2 and in_time)
                log(dict(call=pick, kind=tn["kind"], parsed=bool(mm), at=at, in_time=in_time,
                         think_s=round(b["dt"], 2), opp=tn["key"][0], answer=b["ans"], level=LEVEL, slow=SLOW))

            def result(won):
                fight["result"] = "won" if won else "lost"
                line = ("Mac beats %s!" % NAMES[fight["opp"]] if won else
                        "%s beats Mac. %s" % (NAMES[fight["opp"]], "Game over." if fight["losses"] >= 2 else "Rematch."))
                say(line, show="%s: %s" % (MODEL, line))
                log(dict(fight_end=fight["result"], opp=fight["opp"], calls=fight["calls"], dodged=fight["dodged"],
                         hit=fight["hit"], hits=fight["hits"], late=fight["late"], polls_s=round(polls / max(time.time() - t0, 1), 1),
                         level=LEVEL, slow=SLOW))
            if z[0x00] != 1:                               # between fights: the result, then START through the screens
                speed.set(False, SLOW); turn = None; attack = None
                if fight and z[0x00] in (253, 254) and "result" not in fight: result(z[0x00] == 254)
                if held: pad.hold([]); held = []
                if time.time() - menu_t > 1.0: pad.tap("start", 0.1); menu_t = time.time()
                time.sleep(0.05); continue
            if fight and "result" not in fight and (fight["opp"] != opp or h[0xC0] != fight["losses"]):
                result(fight["opp"] != opp and h[0xC0] == fight["losses"])     # the 253/254 screen went by unread
            if fight is None or "result" in fight:
                fight = dict(opp=opp, calls=0, dodged=0, hit=0, hits=0, late=0, losses=h[0xC0])
                said = "%s, %s." % (NAMES[opp], CIRCUIT[opp])
                say(said, show="%s: fight: %s" % (MODEL, said)); log(dict(fight=NAMES[opp], opp=opp, losses=h[0xC0], level=LEVEL, slow=SLOW))
            if attack and h[0x98] < attack["ohp"]: attack["hits"] += 1; fight["hits"] += 1; attack["last"] = frames
            if attack: attack["ohp"] = h[0x98]
            if z[0x05] == 2:                                # Mac is down: mash to get up
                speed.set(False, SLOW); end_attack(); turn = None
                btn = [["a"], ["a"], [], [], ["b"], ["b"], [], []][frames % 8]
            elif z[0x05] == 1 or h[0x00] != 1:              # the opponent is down, or the clock has stopped: wait
                speed.set(False, SLOW); end_attack(); turn = None
                if z[0x05] == 0 and time.time() - stop_t > 4 and time.time() - menu_t > 1.5:   # between rounds: on
                    pad.tap("start", 0.1); menu_t = time.time()
            else:
                if m != prev_m and not m & 0x80 and m in PUNCH.get(opp, {}):     # a punch winds up: the reflex dodge
                    end_attack(); speed.set(False, SLOW)
                    turn = dict(kind="punch", key=(opp, m), f0=frames, land=PUNCH[opp][m], hp=hp, ohp=h[0x98], stars=h[0x42],
                                choice="dodge", done=False)
                if turn and turn["kind"] == "punch" and not turn["done"]:
                    k = frames - turn["f0"]; c = turn["choice"]; land = turn["land"]
                    if c == "dodge" and "dodge_at" not in turn and land - FIRST <= k <= land - LATE: turn["dodge_at"] = k
                    if c in ("face", "body") and "punch_at" not in turn: turn["punch_at"] = k
                    if "dodge_at" in turn and k < turn["dodge_at"] + 4: btn = ["left"]
                    if "punch_at" in turn and k < turn["punch_at"] + 3: btn = ["up", "b"] if c == "face" else ["b"]
                    end = max(land + SPREAD, turn.get("punch_at", -99) + 35)   # a jab's damage shows 20-30 frames on
                    if hp < turn["hp"] or k > end:                         # it landed, or it is over
                        res = ("hit" if hp < turn["hp"] else "star" if h[0x42] > turn["stars"] else
                               "landed" if h[0x98] < turn["ohp"] else "safe")
                        turn["done"] = True
                        if c:
                            r = records.setdefault(turn["key"], {}).setdefault(c, dict(n=0)); r["n"] += 1; r[res] = r.get(res, 0) + 1
                        if res == "hit": fight["hit"] += 1
                        if res == "safe": fight["dodged"] += 1
                        log(dict(punch="%02x" % turn["key"][1], opp=opp, choice=c, result=res, hp=hp, ohp=h[0x98], level=LEVEL, slow=SLOW))
                        if res == "safe": open_turn("reel", z, h)                   # he is open: the model's turn
                elif turn and turn["kind"] != "punch" and not turn["done"]:
                    k = frames - turn["f0"]
                    if turn["choice"] in ("pummel", "body") and attack is None and "started" not in turn:
                        turn["started"] = True; start_attack(turn["choice"], h)
                    if attack is None and k > (REEL if turn["kind"] == "reel" else OPEN * 3):   # nothing came of it
                        turn["done"] = True; speed.set(False, SLOW)
                if attack:                                  # Mac's jabs: until they stop landing
                    if frames - attack["last"] > BLOCKED or frames - attack.get("first", frames) > 240: end_attack()
                    else:
                        attack.setdefault("first", frames)
                        if frames >= attack["next"]:
                            star = attack["star"] and h[0x42] > 0; attack["star"] = False
                            hand = ["b"] if attack["hand"] % 2 == 0 else ["a"]; attack["hand"] += 1
                            attack["btn"] = ["start"] if star else (["up"] + hand if attack["choice"] == "pummel" else hand)
                            attack["at"] = frames; attack["next"] = frames + JAB
                        if frames < attack["at"] + 4: btn = attack["btn"]
                if m not in PUNCH.get(opp, {}) and attack is None and (turn is None or turn["done"]):
                    if idle is None: idle = frames                  # not punching (from the bell on): an offence turn
                    elif frames - idle > OPEN and frames >= probe: open_turn("stand", z, h); probe = frames + PROBE
                else: idle = None
                if hp < last_hp and (turn is None or turn["kind"] != "punch" or turn["done"]) and move and move[0] not in PUNCH.setdefault(opp, {}):
                    PUNCH[opp][move[0]] = max(frames - move[1], FIRST)       # a punch not mapped: learn when it lands
                    log(dict(learned="%02x" % move[0], opp=opp, land=PUNCH[opp][move[0]], level=LEVEL, slow=SLOW))
            if m != prev_m and not m & 0x80 and m != 1: move = (m, frames)
            if h[0x00] == 1 and z[0x05] == 0: stop_t = time.time()
            prev_m = m; last_hp = hp
            if btn != held: pad.hold(btn); held = btn
            time.sleep(0.003)
    finally:
        pad.release_all()
        if speed.slow: ra.cmd("SLOWMOTION", reply=False)
        if os.environ.get("KEEP_RUNNING") != "1" and "PAUSED" not in (ra.cmd("GET_STATUS") or ""): ra.cmd("PAUSE_TOGGLE", reply=False)
        if LOG: LOG.close()
    print("%d calls in %.0f s, mean think %.1f s" % (n, time.time() - t0, sum(thinks) / max(len(thinks), 1)))
