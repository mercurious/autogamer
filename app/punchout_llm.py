#!/usr/bin/env python3
# Runs on the handheld: the language model runs Little Mac's fight in Mike Tyson's Punch-Out!! (Nintendo, 1987;
# fceumm) and has to find each opponent's weak spot. A reflex loop does the frame work: it dodges every punch it knows
# at the right frame (a dodge works from 29 to 7 frames before the punch lands, against every punch mapped), throws the
# counters and the jabs the model called, gets Mac up after a knockdown and presses START between rounds and fights.
# The model makes the calls, and each one stands (Mac acts on it every time that turn comes again) until it changes it:
# - when a punch winds up: DODGE it, or counter into the wind-up to the FACE or the BODY, thrown at the frame the lab
#   found it lands (COUNTER). Most counters are blocked, some get Mac hit; a few are the opponent's weak spot: King
#   Hippo's mouth (a face counter into his big punch, then body blows while he holds his trunks), Bald Bull's charge
#   and Piston Honda's shuffle in the World Circuit (one body counter: a knockdown), the star counters of Piston
#   Honda, Great Tiger and Bald Bull (mapped 2026-10-23, counter, follow-up and fight probes on car12's fceumm).
# - when the opponent is open (reeling after a dodge, stunned by a counter, or standing off defence): PUMMEL (rapid
#   jabs to the face until they are blocked), BODY (rapid body blows), WAIT, or while Mac has a star STAR (the
#   uppercut, START; stars are lost when Mac is hit and when the round ends). The first opening of each kind drops into
#   bullet time (RetroArch's slow motion at the level's ratio) until the call comes; a call after the opening has
#   closed is too late.
# Each question carries every choice's record on that turn across all fights with this opponent (tries, dodged,
# landed, stars, hits, knockdowns, blocked, Mac hit; a dodge also counts the hits in the openings after it) and the
# fight so far. The record and the standing calls are kept in AG_PO_RECORD across games and sessions: what the model
# found against King Hippo once it uses the next time. Win and the next opponent comes out; lose and it is a rematch;
# a third loss is game over, then a new game from Glass Joe (the game's own rules).
# RAM (NES CPU addresses; TASVideos' map, timing mapped 2026-10-10 on a headless fceumm): 00 1 in a fight (48 the
# intro, 253 Mac lost, 254 Mac won), 01 opponent (0 Glass Joe .. 13 Tyson), 05 1 opponent down, 2 Mac down, 06 round,
# 1E frame counter, 90 the opponent's move (01 idle, a punch id 15-1F (and Don Flamenco's 06) while it winds up and
# throws, lower ids for reactions: 05 a guard (King Hippo and Don Flamenco punch back from it, as learned on car12),
# 0E/12 hit in the face, 13/14 King Hippo hit in the belly; 80 bit set
# between moves), 300 clock running, 302/304/305 clock m:s s, 323/324 hearts (tens, units), 342 stars, 391 Mac's health
# and 398 the opponent's (0-96), 3C0 losses. A dodge (left, 4 frames) works from 29 to 7 frames before the punch lands,
# whatever its direction, against every punch mapped; a block only softens it. PUNCH: frames from the move's start to
# its impact (the fewest seen; Mac idle). A counter that does not land mostly stops the punch; when it does not, a
# dodge after it is too late.
# Usage: punchout_llm.py SECONDS [log.jsonl]
# env: TL_RUN, TL_CALIB, TL_TTS, TL_THINK0, AG_MODEL_LABEL, AG_PO_RECORD, VS_PORT
import json, os, random, re, socket, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from ra import RA; from pad import Pad; import llm, voice
LLM = "http://127.0.0.1:%s" % os.environ.get("VS_PORT", "8099"); TTS = os.environ.get("TL_TTS", "0") == "1"
MODEL = os.environ.get("AG_MODEL_LABEL", "model"); RUN = os.environ.get("TL_RUN"); CALIB = os.environ.get("TL_CALIB")
THINK0 = float(os.environ.get("TL_THINK0", "4")); BOOK = os.environ.get("AG_PO_RECORD")
NAMES = ["Glass Joe", "Von Kaiser", "Piston Honda", "Don Flamenco", "King Hippo", "Great Tiger", "Bald Bull",
         "Piston Honda", "Soda Popinski", "Bald Bull", "Don Flamenco", "Mr. Sandman", "Super Macho Man", "Mike Tyson"]
CIRCUIT = ["Minor Circuit"] * 3 + ["Major Circuit"] * 4 + ["World Circuit"] * 6 + ["Dream Fight"]
PUNCH = {0: {0x15: 36, 0x16: 58}, 1: {0x16: 33, 0x17: 39},
         2: {0x15: 43, 0x16: 50, 0x17: 43, 0x18: 13, 0x1A: 13, 0x1B: 57}, 3: {0x05: 40, 0x06: 42, 0x18: 51},
         4: {0x05: 36, 0x15: 40, 0x16: 40, 0x17: 43, 0x18: 43, 0x19: 84}, 5: {0x16: 41, 0x17: 31, 0x18: 31},
         6: {0x15: 33, 0x16: 38, 0x17: 24, 0x19: 138},
         7: {0x15: 30, 0x16: 19, 0x17: 30, 0x18: 9, 0x19: 81, 0x1A: 11, 0x1C: 47, 0x1D: 76},
         8: {0x15: 27, 0x16: 19, 0x18: 24, 0x1A: 105}, 9: {0x15: 27, 0x16: 29, 0x17: 21, 0x1A: 135},
         10: {0x06: 38, 0x15: 27, 0x16: 33}, 11: {0x15: 25, 0x16: 23, 0x18: 23, 0x1A: 11, 0x1B: 11, 0x1C: 25, 0x1F: 28},
         12: {0x15: 23, 0x17: 20, 0x18: 20, 0x19: 28, 0x1B: 52}, 13: {0x16: 38, 0x17: 22}}
# COUNTER: frames from a wind-up's start to throw a counter that lands (a star first), face and body (None: nothing
# landed in the lab); counters into a punch not here go at DEFAULT_K. The charges (Bald Bull 6/19 and 9/1A, Piston
# Honda 7/19) go down to one body counter there; King Hippo's 17/18 open his mouth.
COUNTER = {0: {0x15: (0, None), 0x16: (None, 4)}, 1: {0x16: (None, 6)},
           2: {0x15: (0, None), 0x16: (0, 14), 0x1B: (14, None)}, 4: {0x17: (12, None), 0x18: (12, None)},
           5: {0x16: (0, None), 0x17: (None, 0)}, 6: {0x15: (2, None), 0x16: (0, None), 0x19: (None, 120)},
           7: {0x19: (60, 54), 0x1C: (16, 18), 0x1D: (None, 40)}, 9: {0x1A: (None, 120)},
           10: {0x06: (50, None), 0x15: (0, None), 0x16: (None, 4)}}
DEFAULT_K = 4
EARLY, LATE = 29, 8          # the dodge window: frames before the impact (7, and a frame for the poll)
FIRST = 12                   # dodge this many frames before the impact (or at once when later than that)
SPREAD = {(0, 0x15): 9}      # how much later than its fastest a punch can land (Glass Joe's jab: 36-44; others 0-2)
BLOCKED = 45                 # jabs stop when this many frames pass without damage (it shows 20-30 after the jab)
LONGEST = 400                # and after this many in any case (King Hippo's belly: 32 damage in 250 frames)
OPEN, PROBE = 30, 240        # standing this many frames: an offence turn; then none for this many
REEL = 100                   # an opening lasts at least this long (Glass Joe: a pummel 100 frames on landed)
JAB = 10                     # a jab every this many frames, held 4
ASK_GAP = 20                 # seconds before the model is asked again about a turn it has a standing call for
WINDUP = ("dodge", "cface", "cbody"); OFFENCE = ("pummel", "body", "wait"); STAR = ("star",)
SAY = {"body": "To the body!", "pummel": "Pummel him!", "wait": "Wait.", "star": "Star punch!", "dodge": "Dodge it.",
       "cface": "Counter to the face!", "cbody": "Counter to the body!"}
TEXT = {"body": "body blows", "pummel": "pummel his face (rapid jabs)", "wait": "wait",
        "star": "star uppercut (spends a star), then jabs", "dodge": "dodge it",
        "cface": "counter to his face, into the wind-up", "cbody": "counter to his body, into the wind-up"}
SITU = {"reel": "%s is reeling from your dodge.", "hurt": "%s is stunned by your counter.",
        "stand": "%s is standing, not punching."}
SYSTEM = ("You are Little Mac in Mike Tyson's Punch-Out!! (NES, 1987). Mac dodges by himself; you decide how he fights. "
          "Every opponent has a weak spot and your job is to find it. Some opponents block every punch after a dodge: "
          "against them, dodging is safe but wins nothing, and the way in is a counter into one of their wind-ups, and "
          "the right blows after it. Two kinds of turn. When he winds up a punch: DODGE it, or counter into the wind-up "
          "to his FACE or his BODY. When he is open (reeling after a dodge, stunned by a counter, or standing): PUMMEL "
          "his face with rapid jabs, BODY blows, WAIT, or STAR (a big uppercut, while Mac has stars; he loses one each "
          "time he is hit, and all of them when the round ends). Your call stands: Mac does it every time that turn "
          "comes again, until you change it. Each choice shows your record with it on that turn, across all your "
          "fights with him. A call that knocked him down is his weak spot: keep it. Keep what lands. When nothing you do "
          "lands, experiment: try a choice you have never tried, on a different punch each time, until you find what "
          "hurts him. Blocked punches cost hearts; at zero Mac cannot punch. Knock him down to win. Reply exactly as: "
          "PICK <letter>")
LABEL = (("safe", "dodged"), ("landed", "landed"), ("star", "earned a star"), ("hits", "hits"), ("down", "knocked him down"),
         ("blocked", "blocked"), ("hit", "Mac hit"), ("late", "too late"))

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

def load_book():
    """the record across games: {"rec": {turn: {choice: counts}}, "calls": {turn: choice}, "learned": {opp: {move:
    frames}}, "opp": {opp: {fights, won, secs, landed, taken}}}; a turn is "OPP KIND", KIND pXX (a punch), reel, hurt
    or stand"""
    try: b = json.load(open(BOOK))
    except (TypeError, OSError, ValueError): b = {}
    for k in ("rec", "calls", "learned", "opp"): b.setdefault(k, {})
    return b

def save_book(b):
    if not BOOK: return
    try:
        with open(BOOK + ".tmp", "w") as f: json.dump(b, f)
        os.replace(BOOK + ".tmp", BOOK)
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

def hearts(h): return h[0x23] * 10 + h[0x24]

def pnum(opp, move):
    """a punch's number for the model: the mapped ones in id order, then those learned"""
    ms = sorted(m for m in PUNCH0.get(opp, {})); ms += [m for m in PUNCH.get(opp, {}) if m not in ms]
    return ms.index(move) + 1 if move in ms else len(ms) + 1

def counter_k(opp, move, c):
    ks = COUNTER.get(opp, {}).get(move, (None, None)); k = ks[0 if c == "cface" else 1]
    return DEFAULT_K if k is None else k

def rtext(r, c):
    """one choice's record on a turn"""
    if not r or not r.get("n"): return "never tried"
    bits = ["%d tr%s" % (r["n"], "y" if r["n"] == 1 else "ies")]
    if c == "wait": return bits[0]
    if c in ("pummel", "body", "star") and not r.get("hits"): bits.append("0 hits")
    bits += ["%d %s" % (r[k], label) for k, label in LABEL if r.get(k)]
    if c in WINDUP: bits.append("then %d hits in the openings after" % r.get("after", 0))
    return ", ".join(bits)

def options(rec, order):
    return ["%s) %s: %s" % ("ABCD"[i], TEXT[c], rtext(rec.get(c), c)) for i, c in enumerate(order)]

def plainly(rec):
    """what the record says plainly: a choice that knocked him down, a choice tried often that never led to a hit"""
    out = ["%s knocked him down %s." % (TEXT[c][0].upper() + TEXT[c][1:], "once" if r["down"] == 1 else "%d times" % r["down"])
           for c, r in sorted(rec.items()) if r.get("down")]
    for c, r in sorted(rec.items()):
        if c == "wait" or r.get("n", 0) < 8 or r.get("hit"): continue
        if c == "dodge" and not r.get("after"): out.append("Dodging it has never led to a hit (%d dodges)." % r["n"])
        elif c != "dodge" and not r.get("hits") and not r.get("landed") and not r.get("star"):
            out.append("%s has never landed here (%d tries)." % (TEXT[c][0].upper() + TEXT[c][1:], r["n"]))
    return out

def score(opp, z, h):
    who = NAMES[opp]
    return "%s, %s. Round %d, %d:%d%d. Mac health %d of 96, hearts %d, stars %d. %s health %d of 96." % (
        who, CIRCUIT[opp], max(z[0x06], 1), h[2], h[4], h[5], h[0x91], h[0x23] * 10 + h[0x24], h[0x42], who, h[0x98])

def against(book, opp, fight):
    """the fight so far, with the fights before it"""
    o = book["opp"].get(str(opp), {}); secs = o.get("secs", 0) + time.time() - fight["t0"]
    landed = o.get("landed", 0) + fight["hits"]; taken = o.get("taken", 0) + fight["hit"]
    s = "Against %s so far (this fight and %d before, %d won): %.0f min, you landed %d punches, he landed %d." % (
        NAMES[opp], o.get("fights", 0), o.get("won", 0), secs / 60, landed, taken)
    return s + (" Nothing you call has hurt him yet." if not landed and secs > 60 else "")

def pfacts(book, opp, fight, key, move, land, z, h, order, now):
    """a punch winds up: dodge it or counter into it"""
    return "\n".join([score(opp, z, h), against(book, opp, fight),
                      "%s winds up punch %d (it lands %.2f s after it starts)." % (NAMES[opp], pnum(opp, move), land / 60.0),
                      "Your call here now: %s. Your answer is Mac's call for this punch from now on." % TEXT[now]]
                     + plainly(book["rec"].get(key, {})) + options(book["rec"].get(key, {}), order))

def ofacts(book, opp, fight, kind, key, z, h, arrive, order, now=None, later=False):
    """an offence turn: how he is open, when the call arrives (later: a turn gone by without a call, for next time)"""
    lines = [score(opp, z, h), against(book, opp, fight), SITU[kind] % NAMES[opp]]
    if later: lines[-1] = "Next time: " + lines[-1][0].lower() + lines[-1][1:] + " Your answer is Mac's call then."
    elif now: lines.append("Your call here now: %s. Mac is doing it now; your answer is his call from now on." % TEXT[now])
    else: lines.append("Your call arrives about %.2f s from now." % (arrive / 60.0))
    if h[0x42]: lines.append("You have %d star%s: lost when you are hit, and at the end of this round (%d:%d%d of 3:00 gone)." % (
        h[0x42], "" if h[0x42] == 1 else "s", h[2], h[4], h[5]))
    return "\n".join(lines + plainly(book["rec"].get(key, {})) + options(book["rec"].get(key, {}), order))

PUNCH0 = {o: dict(p) for o, p in PUNCH.items()}     # the mapped punches (numbered first)

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
    book = load_book(); calls = book["calls"]; book_t = time.time()
    for o, ms in book["learned"].items():
        for mv, land in ms.items(): PUNCH.setdefault(int(o), {}).setdefault(int(mv), land)
    t0 = time.time(); worker = None; relevel = False; menu_t = 0; held = []; thinks = []
    frames = 0; fc = None; prev_m = None; fight = None; n = 0; polls = 0; idle = None; move = None; last_hp = 0
    last_ohp = 0; stop_t = time.time(); probe = 0; attack_end = -99; blow = None
    turn = None        # the turn now on: {"kind" ("punch", "reel", "hurt", "stand"), "key", "f0", "choice", ...}
    attack = None      # Mac's jabs: {"choice", "next", "at", "btn", "last" (damage seen), "ohp", "hits", "star"}
    asked = {}         # turn -> when the model was last asked about it
    todo = {}          # offence turns to ask about first, for next time: gone by without a call while the model was
                       # busy, or their call just came to nothing
    pending = []       # questions whose answers have not come yet

    def think_s():
        return sum(thinks[1:][-20:]) / len(thinks[1:][-20:]) if len(thinks) > 1 else THINK0

    def bump(key, choice, **kw):
        """add to a choice's record on a turn (kept across games)"""
        r = book["rec"].setdefault(key, {}).setdefault(choice, dict(n=0))
        for k, v in kw.items(): r[k] = r.get(k, 0) + v
        return r

    def busy(): return worker is not None and worker.is_alive()

    def ask_turn(tn, text, order):
        global worker
        box = dict(order=order, turn=tn); tn["box"] = box; pending.append(box); asked[tn["key"]] = time.time()
        def think(text=text, box=box):
            t1 = time.time()
            try: box["ans"] = ask(text)
            except Exception as ex: box["ans"] = "ERROR %s" % ex
            box["dt"] = time.time() - t1; thinks.append(box["dt"]); save(CALIB, thinks[1:][-50:])
        worker = threading.Thread(target=think, daemon=True); worker.start()

    def may_ask(key):
        return not busy() and (key not in calls or time.time() - asked.get(key, 0) > ASK_GAP)

    def open_turn(kind, z, h, after=None):
        """an offence turn. With a standing call for this opponent and situation Mac acts on it at once, and the model
        is asked (at full speed) whether to keep it; the first time, the game slows down and waits for the call."""
        global turn
        if not hearts(h): turn = None; return          # tired: Mac cannot punch until his dodges win hearts back
        opp = min(z[0x01], 13); key = "%d %s" % (opp, kind); now = calls.get(key)
        if now == "star" and not h[0x42]: now = "pummel"
        turn = dict(kind=kind, f0=frames, key=key, choice=now, standing=now, done=now == "wait", after=after)
        if now == "wait": bump(key, "wait", n=1)
        if not may_ask(key):
            if not now: todo[key] = kind
            return
        todo.pop(key, None)
        choices = OFFENCE + (STAR if h[0x42] else ()); order = random.sample(choices, len(choices))
        if not now: speed.set(True, SLOW)
        ask_turn(turn, ofacts(book, opp, fight, kind, key, z, h, think_s() * 60 / (1 if now else SLOW), order, now), order)

    def start_attack(c, h, star=False):
        global attack
        attack = dict(choice=c, next=frames, at=-99, btn=[], last=frames, ohp=h[0x98], hits=0, star=star, hand=0)

    def end_attack():
        """the jabs stopped: their record in the offence turn they answered, and in the dodge or counter before it"""
        global attack, attack_end
        if attack and turn and turn["kind"] != "punch" and turn.get("choice") == attack["choice"] and not turn["done"]:
            bump(turn["key"], attack["choice"], n=1, hits=attack["hits"], blocked=0 if attack["hits"] else 1)
            if turn["after"]: bump(*turn["after"], after=attack["hits"])
            turn["done"] = True
            log(dict(attack=attack["choice"], kind=turn["kind"], opp=int(turn["key"].split()[0]), hits=attack["hits"], level=LEVEL, slow=SLOW))
            if attack["hits"] >= 2: ra.cmd("SHOW_MSG %s: %d hits!" % (MODEL, attack["hits"]), reply=False)
            if not attack["hits"] and time.time() - asked.get(turn["key"], 0) > ASK_GAP: todo[turn["key"]] = turn["kind"]
        if attack: attack_end = frames
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
                pending.remove(b); tn = b["turn"]; kinds = WINDUP if tn["kind"] == "punch" else OFFENCE
                mm = re.search(r"PICK\s*\(?([ABCD])\)?", b["ans"])
                if mm and "ABCD".index(mm.group(1)) >= len(b["order"]): mm = None
                pick = b["order"]["ABCD".index(mm.group(1))] if mm else tn.get("standing") or kinds[0]
                calls[tn["key"]] = pick; n += 1                 # it stands for the next turns like this one
                if fight: fight["calls"] += 1
                at = frames - tn["f0"]
                if tn["kind"] == "punch":                       # a counter not thrown yet, or a dodge: it applies now
                    live = tn is turn and not tn["done"] and "punch_at" not in tn and "dodge_at" not in tn
                    if live and not tn.get("tired"): tn["choice"] = pick; tn["ck"] = counter_k(opp, tn["move"], pick)
                    if pick != tn["standing"]:
                        say(SAY[pick], show="%s: punch %d: %s" % (MODEL, pnum(int(tn["key"].split()[0]), tn["move"]), TEXT[pick]), spoken=False)
                    log(dict(call=pick, kind="punch", move="%02x" % tn["move"], parsed=bool(mm), at=at, now=live,
                             think_s=round(b["dt"], 2), opp=int(tn["key"].split()[0]), answer=b["ans"], level=LEVEL, slow=SLOW))
                    continue
                in_time = tn is turn and not tn["done"] and (attack is None or attack["choice"] != pick)
                update = (bool(tn.get("standing")) or tn.get("later", False)) and not in_time
                if update: pass                                 # Mac acted on the standing call; this one is for next time
                elif in_time:                                  # the jabs start now (or Mac waits)
                    if attack: end_attack(); tn["done"] = False   # the standing call's jabs, recorded; now the new one
                    tn["choice"] = pick; speed.set(False, SLOW)
                    if pick == "wait": tn["done"] = True; bump(tn["key"], "wait", n=1)
                    else: start_attack(pick, h, star=pick == "star"); tn["started"] = True
                else:
                    bump(tn["key"], pick, n=1, late=1)
                    if fight: fight["late"] += 1
                say(SAY[pick], show="%s: %s%s" % (MODEL, pick.upper(), "" if in_time or update else " - too late"),
                    spoken=SLOW >= 2 and in_time)
                log(dict(call=pick, kind=tn["kind"], parsed=bool(mm), at=at, in_time=in_time, update=update,
                         think_s=round(b["dt"], 2), opp=int(tn["key"].split()[0]), answer=b["ans"], level=LEVEL, slow=SLOW))

            def result(won):
                fight["result"] = "won" if won else "lost"
                line = ("Mac beats %s!" % NAMES[fight["opp"]] if won else
                        "%s beats Mac. %s" % (NAMES[fight["opp"]], "Game over." if fight["losses"] >= 2 else "Rematch."))
                say(line, show="%s: %s" % (MODEL, line))
                o = book["opp"].setdefault(str(fight["opp"]), dict(fights=0, won=0, secs=0, landed=0, taken=0))
                for k, v in (("fights", 1), ("won", int(won)), ("secs", round(time.time() - fight["t0"])),
                             ("landed", fight["hits"]), ("taken", fight["hit"])): o[k] = o.get(k, 0) + v
                save_book(book)
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
                fight = dict(opp=opp, calls=0, dodged=0, hit=0, hits=0, late=0, losses=h[0xC0], t0=time.time())
                last_hp = hp; last_ohp = h[0x98]; todo.clear()
                said = "%s, %s." % (NAMES[opp], CIRCUIT[opp])
                say(said, show="%s: fight: %s" % (MODEL, said)); log(dict(fight=NAMES[opp], opp=opp, losses=h[0xC0], level=LEVEL, slow=SLOW))
            if h[0x98] < last_ohp: fight["hits"] += 1                        # every punch that lands, either way
            if hp < last_hp: fight["hit"] += 1
            if attack and h[0x98] < attack["ohp"]:
                attack["hits"] += 1; attack["last"] = frames; blow = (turn["key"], attack["choice"], frames) if turn else None
            if attack: attack["ohp"] = h[0x98]
            if z[0x05] == 1 and blow and frames - blow[2] < 60:            # he went down: the blow that did it
                bump(blow[0], blow[1], down=1); log(dict(down=blow[1], key=blow[0], level=LEVEL, slow=SLOW)); blow = None
            if z[0x05] == 2:                                # Mac is down: mash to get up
                speed.set(False, SLOW); end_attack(); turn = None
                btn = [["a"], ["a"], [], [], ["b"], ["b"], [], []][frames % 8]
            elif z[0x05] == 1 or h[0x00] != 1:              # the opponent is down, or the clock has stopped: wait
                speed.set(False, SLOW); end_attack(); turn = None
                if z[0x05] == 0 and time.time() - stop_t > 4 and time.time() - menu_t > 1.5:   # between rounds: on
                    pad.tap("start", 0.1); menu_t = time.time()
            else:
                if m != prev_m and not m & 0x80 and m in PUNCH.get(opp, {}):     # a punch winds up: the call on it
                    end_attack(); speed.set(False, SLOW)
                    key = "%d p%02x" % (opp, m); c = calls.get(key, "dodge"); tired = not hearts(h)
                    turn = dict(kind="punch", key=key, move=m, f0=frames, land=PUNCH[opp][m], hp=hp, ohp=h[0x98], stars=h[0x42],
                                choice="dodge" if tired else c, standing=c, tired=tired, ck=counter_k(opp, m, c), done=False)
                    if may_ask(key) and not todo:
                        order = random.sample(WINDUP, len(WINDUP))
                        ask_turn(turn, pfacts(book, opp, fight, key, m, PUNCH[opp][m], z, h, order, c), order)
                for key in [k for k in todo if k.split()[0] == str(opp)]:      # a turn missed: for next time
                    if busy(): break
                    kind = todo.pop(key); order = random.sample(OFFENCE, len(OFFENCE))
                    ask_turn(dict(kind=kind, key=key, f0=frames, done=True, later=True, after=None),
                             ofacts(book, opp, fight, kind, key, z, h, 0, order, later=True), order)
                if turn and turn["kind"] == "punch" and not turn["done"]:
                    k = frames - turn["f0"]; c = turn["choice"]; land = turn["land"]
                    if c == "dodge" and "dodge_at" not in turn and land - FIRST <= k <= land - LATE: turn["dodge_at"] = k
                    if c in ("cface", "cbody") and "punch_at" not in turn and k >= turn["ck"]: turn["punch_at"] = k
                    if "dodge_at" in turn and k < turn["dodge_at"] + 4: btn = ["left"]
                    if "punch_at" in turn and k < turn["punch_at"] + 3: btn = ["up", "b"] if c == "cface" else ["b"]
                    end = max(land + SPREAD.get((opp, turn["move"]), 3), turn.get("punch_at", -99) + 35)   # a jab's damage shows 20-30 frames on
                    landed = "punch_at" in turn and (h[0x98] < turn["ohp"] or h[0x42] > turn["stars"])
                    if hp < turn["hp"] or k > end or landed:               # it landed (his or Mac's), or it is over
                        res = ("hit" if hp < turn["hp"] else "star" if h[0x42] > turn["stars"] else
                               "landed" if h[0x98] < turn["ohp"] else "safe" if c == "dodge" else "blocked")
                        turn["done"] = True
                        bump(turn["key"], c, n=1, **{res: 1})
                        if res == "star" and h[0x98] < turn["ohp"]: bump(turn["key"], c, landed=1)
                        if res == "safe": fight["dodged"] += 1
                        if res in ("star", "landed"): blow = (turn["key"], c, frames)
                        log(dict(punch="%02x" % turn["move"], opp=opp, choice=c, result=res, at=turn.get("punch_at", turn.get("dodge_at")),
                                 hp=hp, ohp=h[0x98], level=LEVEL, slow=SLOW))
                        if res == "safe": open_turn("reel", z, h, after=(turn["key"], c))      # he is open: the model's turn
                        elif res in ("star", "landed"): open_turn("hurt", z, h, after=(turn["key"], c))
                elif turn and turn["kind"] != "punch" and not turn["done"]:
                    k = frames - turn["f0"]
                    if turn["choice"] in ("pummel", "body", "star") and attack is None and "started" not in turn:
                        turn["started"] = True; start_attack(turn["choice"], h, star=turn["choice"] == "star")
                    if attack is None and k > (REEL if turn["kind"] != "stand" else OPEN * 3):   # nothing came of it
                        turn["done"] = True; speed.set(False, SLOW)
                if attack:                                  # Mac's jabs: until they stop landing
                    if frames - attack["last"] > BLOCKED or frames - attack.get("first", frames) > LONGEST: end_attack()
                    else:
                        attack.setdefault("first", frames)
                        if frames >= attack["next"]:
                            star = attack["star"] and h[0x42] > 0; attack["star"] = False
                            hand = ["b"] if attack["hand"] % 2 == 0 else ["a"]; attack["hand"] += 1
                            attack["btn"] = ["start"] if star else (["up"] + hand if attack["choice"] in ("pummel", "star") else hand)
                            attack["at"] = frames; attack["next"] = frames + JAB
                        if frames < attack["at"] + 4: btn = attack["btn"]
                if m not in PUNCH.get(opp, {}) and attack is None and (turn is None or turn["done"]):
                    if idle is None: idle = frames                  # not punching (from the bell on): an offence turn
                    elif frames - idle > OPEN and frames >= probe: open_turn("stand", z, h); probe = frames + PROBE
                else: idle = None
                if hp < last_hp and (turn is None or turn["kind"] != "punch" or turn["done"]) and move and move[0] not in PUNCH.setdefault(opp, {}):
                    PUNCH[opp][move[0]] = max(frames - move[1], FIRST)       # a punch not mapped: learn when it lands
                    book["learned"].setdefault(str(opp), {})[str(move[0])] = PUNCH[opp][move[0]]
                    log(dict(learned="%02x" % move[0], opp=opp, land=PUNCH[opp][move[0]], level=LEVEL, slow=SLOW))
            if m != prev_m and not m & 0x80 and m != 1: move = (m, frames)
            if h[0x00] == 1 and z[0x05] == 0: stop_t = time.time()
            prev_m = m; last_hp = hp; last_ohp = h[0x98]
            if time.time() - book_t > 20: save_book(book); book_t = time.time()
            if btn != held: pad.hold(btn); held = btn
            time.sleep(0.003)
    finally:
        pad.release_all(); save_book(book)
        if speed.slow: ra.cmd("SLOWMOTION", reply=False)
        if os.environ.get("KEEP_RUNNING") != "1" and "PAUSED" not in (ra.cmd("GET_STATUS") or ""): ra.cmd("PAUSE_TOGGLE", reply=False)
        if LOG: LOG.close()
    print("%d calls in %.0f s, mean think %.1f s" % (n, time.time() - t0, sum(thinks) / max(len(thinks), 1)))
