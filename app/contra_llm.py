#!/usr/bin/env python3
# Runs on the handheld: the language model is Player 2 in Contra (Konami, 1988; fceumm), playing beside a human
# Player 1 on the handheld's own controls. A reflex soldier (contra.py) plays P2 frame by frame from RAM: it dodges
# what the game's collision boxes say would hit it, jumps pits, aims and fires. The model makes the calls a partner
# makes, a few seconds apart, each standing until the next: COVER (stay right behind P1 and shoot what threatens
# them), LEAD (go ahead and clear the way), REAR (hang back and watch behind and above); with a weapon on the screen,
# TAKE it (else it is left for P1); and when P2 is out of lives, BORROW one from P1 (the game's own rule: a player who
# is out and presses A takes a life from the other) or SIT OUT. Each question carries the human's state (lives,
# lives lost lately, weapon, where they are) and the model's record with each call this stage: P1's and its own lives
# lost while it stood, and the screens gained. P2 never stands at the left edge while P1 pushes on: the screen
# would not scroll (bank7). The game starts itself: 2 PLAYER (AG_CT_KONAMI=1 first enters the 30-lives code).
# Player 1 can talk to P2 (AG_CT_VOICE=1, talk.py): hold R1, say an order, let go. "cover me", "you first" / "go
# ahead", "hang back", "hold up" / "wait" (then "go"), "grab the spread" / "leave it, it's mine", "don't borrow my
# lives" / "take a life", "your call". An order stands until P1 changes it (the model's calls of that kind wait);
# P2 answers out loud. Anything else goes to the model with its next question, and it answers in a few words.
# AG_CT_STANDIN=1: a reflex soldier plays P1 too (no human: to watch, and to test). AG_CT_RECORD: a JSON file that
# keeps the record across games, per kind of partner (human or stand-in), stage and call; the question gives it as
# rates (lives lost and screens gained a minute), so what one session learns, the next is told.
# Usage: contra_llm.py SECONDS [log.jsonl]   env: TL_CALIB, TL_TTS, TL_THINK0, AG_MODEL_LABEL, VS_PORT,
#   AG_CT_KONAMI, AG_CT_STANDIN, AG_CT_RECORD, AG_CT_VOICE
import json, os, random, re, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from ra import RA; from pad import Pad; import llm, voice
import contra
LLM = "http://127.0.0.1:%s" % os.environ.get("VS_PORT", "8099"); TTS = os.environ.get("TL_TTS", "0") == "1"
MODEL = os.environ.get("AG_MODEL_LABEL", "model"); CALIB = os.environ.get("TL_CALIB")
THINK0 = float(os.environ.get("TL_THINK0", "4")); KONAMI = os.environ.get("AG_CT_KONAMI") == "1"
STANDIN = os.environ.get("AG_CT_STANDIN") == "1"; RECORD = os.environ.get("AG_CT_RECORD")
VOICE = os.environ.get("AG_CT_VOICE") == "1"
PARTNER = "standin" if STANDIN else "human"      # the record across games is kept per kind of partner
ME, HUMAN = 1, 0                                  # player indexes: the model is P2
ROLES = ("cover", "lead", "rear")
OFFSET = {"cover": -20, "lead": 56, "rear": -52}  # where P2 keeps itself from P1, screen px (outdoors, side-on)
EDGE = 0x30                                       # never left of this while P1 pushes on (the scroll stops at 0x21)
TEXT = {"cover": "COVER: stay right behind player 1 and shoot what threatens them",
        "lead": "LEAD: go ahead of player 1 and clear the way",
        "rear": "REAR: hang back and pick off what comes from behind and above",
        "take": "TAKE the %s yourself, then cover",
        "borrow": "BORROW a life from player 1 and rejoin (they keep %d)",
        "sitout": "SIT OUT: player 1 keeps all %d lives"}
SAY = {"cover": "I've got your back.", "lead": "I'll take point.", "rear": "I'll watch our six.",
       "take": "I'll grab the %s.", "leave": "The %s is yours.", "borrow": "Borrowing a life. Sorry!",
       "sitout": "I'll sit this one out."}
KIND = {0x01: "enemy bullets", 0x05: "soldiers", 0x06: "snipers", 0x07: "turrets", 0x04: "turrets", 0x08: "wall cannons",
        0x02: "weapon boxes", 0x03: "weapon capsules", 0x0c: "divers", 0x0e: "Basquez"}
SYSTEM = ("You are Player 2 in Contra (NES, 1988), fighting beside a human Player 1. Your soldier moves, dodges, "
          "jumps and shoots by itself; you make a partner's calls, and each call stands until your next one: COVER "
          "(stay right behind player 1), LEAD (go ahead and clear the way), REAR (hang back and watch behind and "
          "above). When a weapon is on the screen you may TAKE it; otherwise you leave it for player 1. Player 1 is a "
          "person: keep them alive and moving forward, and do not take the best weapon from them. If you run out of "
          "lives you may BORROW one of theirs or SIT OUT. Player 1 can talk to you; their orders stand until they change "
          "them, so follow them. Each turn you get the stage, both players, the enemies, your record with each call "
          "this stage, and lettered choices. Reply exactly as: PICK <letter>")

# what P1 says: the first pattern that matches is the order (the narrow ones first)
ITEM = r"(it|that|this|one|power ?-?ups?|weapons?|guns?|items?|falcon|spread|laser|machine ?gun|m|fire|flame|rapid|barrier|shield|s|l|f|r|b)"
ORDERS = [
    ("noborrow", r"\b(don'?t|do not|no|never|stop|quit)\b.{0,20}\b(borrow\w*|tak\w+|steal\w*|us\w+)\b.{0,14}\bli(fe|ves)\b|\bno borrow"),
    ("borrow", r"\b(borrow|take|have|grab|use)\b.{0,14}\bli(fe|ves)\b|\byou can borrow\b|\bborrow\b"),
    ("leave", r"\b(leave|skip|ignore)\b.{0,8}\b(it|that|the|this)\b|\b(that'?s|it'?s|that is|it is)\s+mine\b|"
              r"\b(don'?t|do not)\b.{0,8}\b(take|grab|get|touch)\b|\bi'?(ll| will)\s+(get|take|grab)\b|^\W*mine\b"),
    ("take", r"\b(grab|get|take|pick up|go for|snag|collect)\b\s+(the |that |this |a |some |your )?" + ITEM + r"\b|"
             r"\b(you take it|it'?s (all )?yours|you have it|all yours|you get it)\b"),
    ("yourcall", r"\b(your call|you decide|up to you|do your thing|your choice|play (it )?your way|you'?re free)\b"),
    ("lead", r"\b(you first|go ahead|go first|after you|you lead|lead (the way|on)|take (the )?point|clear the way|"
             r"push (on|ahead|forward)|go on ahead|get ahead|in front)\b"),
    ("rear", r"\b(hang back|fall back|stay back|get back|watch (our|my|the) (six|back|rear)|rear|behind us|cover (our|the) back)\b"),
    ("cover", r"\b(cover|back me up|stay with me|stick with me|stay close|follow me|on me|with me|behind me|"
              r"come (here|back|with|to me)|protect me|help me|guard me|catch up)\b"),
    ("hold", r"\b(hold|wait|stop|stay|freeze|halt|don'?t move|hang on|easy)\b"),
    ("go", r"\b(go|move|let'?s go|come on|onward|forward|run|now)\b"),
]
ITEM_NAMES = [("spread", r"spread|\bs\b"), ("laser", r"laser|\bl\b"), ("machine gun", r"machine|\bm\b"),
              ("fire gun", r"fire|flame|\bf\b"), ("rapid fire", r"rapid|\br\b"), ("barrier", r"barrier|shield|\bb\b")]
REPLY = {"cover": "Got your back.", "lead": "Moving up. Follow me.", "rear": "Hanging back. I'll watch our six.",
         "hold": "Holding here.", "go": "Moving!", "take": "Going for the %s.", "take_later": "I'll grab the next one.",
         "leave": "It's all yours.", "noborrow": "Got it. I won't touch your lives.", "borrow": "Thanks, partner. Borrowing one.",
         "borrow_later": "Thanks. I'll take one if I run out.", "yourcall": "Okay, I'll make the calls."}

def order_of(words):
    """the order in what P1 said, or None: (key, the weapon they named or None)"""
    w = words.lower().replace("’", "'")
    for key, pat in ORDERS:
        if re.search(pat, w):
            named = next((n for n, p in ITEM_NAMES if re.search(p, w)), None) if key == "take" else None
            return key, named
    return None, None

def save(path, xs):
    if not path or len(xs) < 3: return
    try:
        with open(path + ".tmp", "w") as f: f.write("%.2f\n" % (sum(xs) / len(xs)))
        os.replace(path + ".tmp", path)
    except OSError: pass

def ask(text, reply=False):
    if reply: text += "\nReply as: PICK <letter>, then a new line: SAY <a few words back to player 1>"
    return llm.chat(LLM, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}], 32 if reply else 6,
                    0.3, 120, cache=True)[0]

def say(line, show=None):
    if TTS: voice.say(line, show=show, ra=ra)
    elif show: ra.cmd("SHOW_MSG " + show, reply=False)

def weapon(st, i):
    return contra.WEAPONS.get(st.weapon(i), "rifle") + (" with rapid fire" if st.rapid(i) else "")

def item_name(st, k):
    """what a weapon item or capsule carries (its attribute bits)"""
    return contra.ITEMS.get(st.eattr(k) & 0x07, "a weapon")

def load_hist():
    try: return json.load(open(RECORD))
    except (TypeError, OSError, ValueError): return {}

def save_hist(hist):
    if not RECORD: return
    try:
        with open(RECORD + ".tmp", "w") as f: json.dump(hist, f)
        os.replace(RECORD + ".tmp", RECORD)
    except OSError: pass

def hist_text(hist, stage):
    """the record across past games with this kind of partner on this stage, per call, as rates"""
    h = hist.get(PARTNER, {}).get(str(stage), {}); parts = []
    for r in ROLES:
        x = h.get(r)
        if not x or x["secs"] < 30: continue
        m = x["secs"] / 60
        parts.append("%s %.0f min: player 1 lost %.1f lives a minute, you %.1f, %.1f screens a minute" % (
            r.upper(), m, x["p1"] / m, x["p2"] / m, x["screens"] / m))
    return "; ".join(parts)

def facts(st, rec, order, now, item, lost, t_now, past="", orders=""):
    """the question: the stage, both players, the enemies, the record, the choices"""
    lv = st.level(); h, m = HUMAN, ME
    where = st.x(h) - st.x(m)
    rel = ("%d px ahead of you" % where if where > 8 else "%d px behind you" % -where if where < -8 else "beside you")
    if st.vertical(): rel = "%d px above you" % (st.y(m) - st.y(h)) if st.y(h) < st.y(m) - 8 else (
        "%d px below you" % (st.y(h) - st.y(m)) if st.y(h) > st.y(m) + 8 else "level with you")
    recent = sum(1 for t in lost if t_now - t < 60)
    lines = ["Contra, 2 players. Stage %d of 8: %s%s, screen %d." % (lv + 1, contra.LEVELS[lv],
             " (a base: rooms seen from behind)" if st.indoor() else " (the screen climbs: whoever falls behind dies)"
             if st.vertical() else "", st.z[0x64])]
    if st.over(h): lines.append("Player 1 (the human) is out of lives.")
    else: lines.append("Player 1 (the human): %d lives left, %s, %s, lost %d li%s in the last minute." % (
        st.lives(h), weapon(st, h), rel, recent, "fe" if recent == 1 else "ves"))
    lines.append("You (player 2): %s." % ("out of lives" if st.over(m) else "%d lives left, %s" % (st.lives(m), weapon(st, m))))
    kinds = {}
    for k in st.slots():
        n = KIND.get(st.etype(k), "other enemies" if st.etype(k) >= 0x10 else None)
        if n and n not in ("weapon capsules",): kinds[n] = kinds.get(n, 0) + 1
    lines.append("On the screen: %s." % (", ".join("%d %s" % (v, n) for n, v in kinds.items()) or "no enemies"))
    if item is not None: lines.append("A weapon is on the screen: %s." % item_name(st, item))
    parts = []
    for r in ROLES:
        x = rec.get(r)
        parts.append("%s never called" % r.upper() if not x else "%s %d calls, %.0f s, player 1 lost %d, you lost %d, "
                     "%d screens gained" % (r.upper(), x["n"], x["secs"], x["p1"], x["p2"], x["screens"]))
    lines.append("Your record this stage: %s." % "; ".join(parts))
    if past: lines.append("Past games with %s on this stage: %s." % ("this partner" if PARTNER == "human" else "a bot partner", past))
    if now: lines.append("Your standing call: %s." % now.upper())
    if orders: lines.append(orders)
    return "\n".join(lines + ["%s) %s" % ("ABCDE"[i], c) for i, c in enumerate(order)])

def chat_facts(st, order, now, orders=""):
    """a short question for answering what P1 said: who is where, the orders, what they said, the choices (the
    full question's record and enemies make the answer come ~10 s late)"""
    lv = st.level(); h, m = HUMAN, ME
    lines = ["Contra, 2 players. Stage %d of 8: %s." % (lv + 1, contra.LEVELS[lv]),
             "Player 1 (the human): %s." % ("out of lives" if st.over(h) else "%d lives left, %s" % (st.lives(h), weapon(st, h))),
             "You (player 2): %s." % ("out of lives" if st.over(m) else "%d lives left, %s" % (st.lives(m), weapon(st, m)))]
    if now: lines.append("Your standing call: %s." % now.upper())
    if orders: lines.append(orders)
    return "\n".join(lines + ["%s) %s" % ("ABCDE"[i], c) for i, c in enumerate(order)])

def options(st, item, borrow_ok=True, keep=None):
    """the lettered choices now: (keys, texts). keep: the standing call, offered as a choice when answering P1"""
    if st.over(ME):
        keys = ["borrow", "sitout"] if st.lives(HUMAN) >= 1 and not st.over(HUMAN) and borrow_ok else ["sitout"]
        txt = {"borrow": TEXT["borrow"] % max(st.lives(HUMAN) - 1, 0), "sitout": TEXT["sitout"] % st.lives(HUMAN)}
    else:
        keys = list(ROLES) + (["take"] if item is not None else []) + (["keep"] if keep else [])
        txt = dict(TEXT); txt["take"] = TEXT["take"] % (item_name(st, item) if item is not None else "weapon")
        if keep: txt["keep"] = "KEEP your standing call (%s)" % keep.upper()
    random.shuffle(keys)
    return keys, [txt[k] for k in keys]

def title(st, pad, mem):
    """the title (game routine 1, bank7): (the 30-lives code, checked every frame of it), START skips the logo's
    scroll, SELECT moves the cursor (22) to 2 PLAYER, START begins. mem: what has been done (a dict)"""
    z = st.z; now = time.time()
    if now - mem.get("t", 0) < (0.1 if mem.get("down") or KONAMI and z[0x3f] < 10 and not z[0x24] else 0.35): return
    mem["t"] = now
    if mem.get("down"): pad.set(mem["down"], False); mem["down"] = None; return
    if z[0x18] != 1: return
    if KONAMI and not z[0x24] and z[0x3f] == 0xff and mem.get("retry", 0) < 3:   # a press went astray: type it again
        ra.cmd("WRITE_CORE_MEMORY 3f 00", reply=False); mem["retry"] = mem.get("retry", 0) + 1; mem["code"] = None
        print("title: code missed, again", flush=True); return
    if KONAMI and not z[0x24] and z[0x3f] < 10:            # 3F: how many of the code's presses the game has seen
        if mem.get("code") == z[0x3f] and now - mem.get("code_t", 0) < 1: return    # wait for the last to count
        mem["down"] = ["up", "up", "down", "down", "left", "right", "left", "right", "b", "a"][z[0x3f]]
        pad.set(mem["down"], True); mem["code"] = z[0x3f]; mem["code_t"] = now
        return
    if not mem.get("said"): print("title: code %s (3F=%02x), cursor %d" % ("on" if z[0x24] else "off", z[0x3f], z[0x22]), flush=True); mem["said"] = 1
    if z[0xfd]: mem["down"] = "start"                      # still scrolling in: START shows the menu
    elif z[0x22] != 1: mem["down"] = "select"              # the cursor to 2 PLAYER
    else: mem["down"] = "start"                            # go
    pad.set(mem["down"], True)

if __name__ == "__main__":
    T = float(sys.argv[1]); LOG = open(sys.argv[2], "a") if len(sys.argv) > 2 else None
    ra = RA(timeout=0.2); pads = [Pad(user=0), Pad(user=1)]
    if "PAUSED" in (ra.cmd("GET_STATUS") or ""): ra.cmd("PAUSE_TOGGLE", reply=False)
    log = lambda d: LOG and (LOG.write(json.dumps(dict(t=round(time.time() - t0, 1), **d)) + "\n"), LOG.flush())
    t0 = time.time(); worker = None; thinks = []; pending = []; n = 0
    me = contra.Soldier(ME); me.pickup = False; stand = contra.Soldier(HUMAN) if STANDIN else None
    if stand: stand.goal = 0xc0                 # past the 2-player scroll point (0xb0)
    held = [[], []]; jump_hold = [0, 0]; last_frame = [None, None]; mem = {}; prev = None
    role = None; role_t = time.time(); role_scr = 0; stage = None; rec = {}; lost = []
    item_said = set(); last_ask = 0; borrowed = 0; hist = load_hist(); hist_t = time.time()
    # P1's orders (talk.py): role (cover/lead/rear/hold) and item (take/leave) stand until P1 changes them
    order = dict(role=None, said="", said_t=0, item=None, item_t=0, item_seen=False, borrow_ok=True)
    told = []; heard = []; hold_w = None; before_hold = None
    if VOICE:
        import talk
        talk.Talk(lambda: heard.append(("listen",)), lambda w, secs, why="": heard.append(("text", w, secs, why))).start()

    def orders_text(st):
        """the orders standing, and what P1 just said, for the question"""
        out = []
        if order["role"]: out.append('Player 1\'s standing order: %s (they said "%s" %d s ago).' % (
            order["role"].upper(), order["said"], time.time() - order["said_t"]))
        if order["item"] == "take": out.append("Player 1 told you to take the next weapon.")
        if order["item"] == "leave": out.append("Player 1 wants the weapon for themselves.")
        if not order["borrow_ok"]: out.append("Player 1 told you not to borrow their lives.")
        if told: out.append('Player 1 just said to you: "%s"' % " / ".join(told))
        return "\n".join(out)

    def obey(st, key, named, words):
        """carry out an order P1 said: the spoken answer (None: not an order, the model answers it)"""
        global role, hold_w, before_hold
        now = time.time()
        if key is None: told.append(words[:120]); return None
        if key in ("cover", "lead", "rear", "hold", "go"):
            text = REPLY[key]
            if key == "go": key = before_hold if role == "hold" and before_hold else "lead"
            if key == "hold":
                if role != "hold": before_hold = role
                hold_w = st.z[0x64] * 256 + st.z[0x65] + st.x(ME)
            if key != role: close_role(st); role = key
            order.update(role=key, said=words[:60], said_t=now)
            return text
        if key == "take":
            order.update(item="take", item_t=now, item_seen=False); me.pickup = True
            k = me.item(st)
            if k is None: k = next((k for k in st.slots() if st.etype(k) == 0x03), None)
            return REPLY["take"] % item_name(st, k) if k is not None else REPLY["take_later"]
        if key == "leave": order.update(item="leave", item_t=now, item_seen=False); me.pickup = False; return REPLY["leave"]
        if key == "noborrow": order["borrow_ok"] = False; return REPLY["noborrow"]
        if key == "borrow":
            order["borrow_ok"] = True
            if st.over(ME) and st.lives(HUMAN) >= 1 and not st.over(HUMAN): pads[ME].tap("a", 0.05); return REPLY["borrow"]
            return REPLY["borrow_later"]
        if key == "yourcall":
            if role == "hold": close_role(st); role = before_hold or "cover"
            order.update(role=None, item=None); return REPLY["yourcall"]

    def bump(key, **kw):
        """add to the record across games: this partner, this stage, this call"""
        if stage is None or key not in ROLES: return
        r = hist.setdefault(PARTNER, {}).setdefault(str(stage), {}).setdefault(key, dict(secs=0.0, p1=0, p2=0, screens=0))
        for k, v in kw.items(): r[k] += v

    def busy(): return worker is not None and worker.is_alive()

    def ask_now(st, item):
        global worker, last_ask
        keys, texts = options(st, item, order["borrow_ok"], keep=role if told and role else None)
        box = dict(keys=keys, item=item, stage=st.level(), t=time.time(), told=list(told)); pending.append(box)
        last_ask = time.time()
        if told: text = chat_facts(st, texts, role, orders_text(st))
        else: text = facts(st, rec, texts, role, item, lost, time.time(), hist_text(hist, st.level()), orders_text(st))
        told.clear()
        def think(text=text, box=box):
            t1 = time.time()
            try: box["ans"] = ask(text, reply=bool(box["told"]))
            except Exception as ex: box["ans"] = "ERROR %s" % ex
            box["dt"] = time.time() - t1
            if not box["told"]: thinks.append(box["dt"]); save(CALIB, thinks[1:][-50:])
        worker = threading.Thread(target=think, daemon=True); worker.start()

    def close_role(st):
        """the standing call ends: its time and the screens gained go to its record"""
        global role_t, role_scr
        if role in ROLES:
            r = rec.setdefault(role, dict(n=0, secs=0.0, p1=0, p2=0, screens=0))
            r["secs"] += time.time() - role_t; r["screens"] += max(st.z[0x64] - role_scr, 0)
            bump(role, secs=time.time() - role_t, screens=max(st.z[0x64] - role_scr, 0))
        role_t = time.time(); role_scr = st.z[0x64]

    def press(i, btn, frame):
        """the soldier's buttons, one change a frame (the network remote reads one message a frame); A held 3 frames"""
        if "a" in btn: jump_hold[i] = 3
        if frame == last_frame[i]: return
        last_frame[i] = frame
        if jump_hold[i] > 0: jump_hold[i] -= 1; btn = sorted((set(btn) | {"a"}) - {"down"})   # not a drop-through
        pads[i].nudge(btn); held[i] = sorted(pads[i].held)

    try:
        while time.time() - t0 < T:
            if time.time() - t0 < 20 and time.time() - mem.get("unpause", 0) > 2:   # run.sh's pause may land late
                mem["unpause"] = time.time()
                if "PAUSED" in (ra.cmd("GET_STATUS") or ""): ra.cmd("PAUSE_TOGGLE", reply=False)
            st = contra.read(ra)
            if not st: continue
            if st.z[0x18] < 3:                                       # title and demo: start a 2-player game
                if st.z[0x18] == 2 and time.time() - mem.get("demo", 0) > 1:      # START ends the demo: the title
                    pads[0].tap("start", 0.05); mem["demo"] = time.time()
                elif st.z[0x18] != 2: title(st, pads[0], mem)
                prev = st; time.sleep(0.01); continue
            if mem.get("down"):                                      # the title's last press (START) outlives the
                pads[0].set(mem["down"], False); mem["down"] = None  # title: held, P1's own START never registers
            if st.z[0x18] != 5: prev = st; time.sleep(0.02); continue
            if not st.two():                                         # a 1-player game: not ours to join
                if time.time() - mem.get("solo", 0) > 30:
                    mem["solo"] = time.time()
                    ra.cmd("SHOW_MSG A 1-player game: the model joins 2-player games only (HOME, then start again).", reply=False)
                prev = st; time.sleep(0.05); continue

            if time.time() - hist_t > 30 and st.playing():            # the record across games, now and then
                close_role(st); save_hist(hist); hist_t = time.time()
            if stage != st.level():                                    # a new stage: a new record
                if stage is not None: close_role(st)
                if stage is not None: say("Stage clear!", show="%s: stage %d clear" % (MODEL, stage + 1))
                stage = st.level(); rec = {}; item_said = set(); role_scr = st.z[0x64]
                if role == "hold": role = before_hold or "cover"; order["role"] = role if order["role"] else None
                log(dict(stage=stage, name=contra.LEVELS[stage], lives=[st.lives(0), st.lives(1)]))
            if st.z[0x2c] in (6, 7) and STANDIN and time.time() - mem.get("cont", 0) > 1:   # game over screens
                pads[0].tap("start", 0.05); mem["cont"] = time.time()

            # lives lost: whose, under which call
            if prev and prev.playing():
                for i in (0, 1):
                    if prev.pstate(i) == 1 and st.pstate(i) == 2:
                        if i == HUMAN: lost.append(time.time())
                        if role in ROLES: rec.setdefault(role, dict(n=0, secs=0.0, p1=0, p2=0, screens=0))["p%d" % (i + 1)] += 1
                        bump(role, **{"p%d" % (i + 1): 1})
                        near = [(hex(prev.etype(k)), prev.ex(k) - prev.x(i), prev.ey(k) - prev.y(i)) for k in prev.slots()
                                if abs(prev.ex(k) - prev.x(i)) < 40 and abs(prev.ey(k) - prev.y(i)) < 48]
                        log(dict(lost="P%d" % (i + 1), stage=stage, scr=st.z[0x64], role=role, lives=st.lives(i),
                                 x=prev.x(i), y=prev.y(i), pose=prev.pose(i), near=near,
                                 note=(me if i == ME else stand).note if (i == ME or stand) else "",
                                 took=(me if i == ME else stand).took if (i == ME or stand) else None))

            # what P1 said (R1): an order now, anything else for the model's next question
            while heard:
                ev = heard.pop(0)
                if ev[0] == "listen": ra.cmd("SHOW_MSG %s is listening... (let go of R1)" % MODEL, reply=False); continue
                _, words, secs, why = ev
                if not words:
                    if why: ra.cmd("SHOW_MSG " + why, reply=False)
                    log(dict(heard="", why=why)); continue
                key, named = order_of(words); answer = obey(st, key, named, words)
                log(dict(heard=words, asr_s=round(secs, 2), order=key, named=named, stage=stage, scr=st.z[0x64], role=role))
                if answer: say(answer, show='You: "%s"  %s: %s' % (words[:50], MODEL, answer))
                else: ra.cmd('SHOW_MSG You: "%s"' % words[:70], reply=False)

            # answers that came in: the new standing call
            for b in [b for b in pending if "ans" in b]:
                pending.remove(b); mm = re.search(r"PICK\s*\(?([A-E])\)?", b["ans"])
                idx = "ABCDE".index(mm.group(1)) if mm else -1
                pick = b["keys"][idx] if 0 <= idx < len(b["keys"]) else b["keys"][0]
                n += 1; item = b["item"]; spoken = None
                if pick == "borrow":
                    if st.over(ME) and st.lives(HUMAN) >= 1: pads[ME].tap("a", 0.05); borrowed += 1; spoken = SAY["borrow"]
                elif pick == "sitout": spoken = SAY["sitout"] if mem.get("sat") != stage else None; mem["sat"] = stage
                else:
                    me.pickup = pick == "take" if not order["item"] else order["item"] == "take"
                    new = role if pick == "keep" else "cover" if pick == "take" else pick
                    if b["told"] and pick in ROLES and order["said_t"] <= b["t"]:   # its reading of what P1 said: an
                                                                       # order (unless P1 gave one since)
                        order.update(role=pick, said=" / ".join(b["told"])[:60], said_t=time.time())
                    elif order["role"]: new = role                     # P1's order stands
                    if pick == "take":
                        if item is not None and item in st.slots() and item not in item_said:
                            spoken = SAY["take"] % item_name(st, item); item_said.add(item)
                    elif item is not None and item in st.slots() and item not in item_said:
                        spoken = SAY["leave"] % item_name(st, item); item_said.add(item)
                    if new != role:
                        close_role(st); role = new; spoken = spoken or SAY[new]
                    if role in ROLES and pick != "keep": rec.setdefault(role, dict(n=0, secs=0.0, p1=0, p2=0, screens=0))["n"] += 1
                back = [l for l in b["ans"].splitlines()[1:] if l.strip()] if b["told"] else []
                if back: spoken = re.sub(r"^\W*SAY\W*", "", back[0]).strip().strip('"')[:90] or spoken   # its answer
                if spoken: say(spoken, show="%s: %s" % (MODEL, spoken))
                log(dict(call=pick, parsed=bool(mm), think_s=round(b["dt"], 2), answer=b["ans"], stage=stage, scr=st.z[0x64],
                         **(dict(told=b["told"], overruled=pick in ROLES and pick != role) if b["told"] or order["role"] else {})))

            item_said = {k for k in item_said if k in st.slots() and st.etype(k) in (0x00, 0x03)}   # gone: forgotten
            # ask again whenever the model is free (at most every 2 s), at once when a weapon shows up
            item = me.item(st)
            if item is None:
                cap = [k for k in st.slots() if st.etype(k) == 0x03]; item = cap[0] if cap else None
            if order["item"]:                                   # a take/leave order is about one weapon
                if item is not None: order["item_seen"] = True
                if item is None and (order["item_seen"] or time.time() - order["item_t"] > 15) or time.time() - order["item_t"] > 40:
                    order["item"] = None
            if not busy() and st.playing() and not st.z[0x25] and (time.time() - last_ask > 2 or told or
                                                                   item is not None and item not in item_said and not pending):
                ask_now(st, item)

            # the soldiers: P2 keeps its place from P1 by the standing call; never at the left edge while P1 pushes on
            if role == "hold" and hold_w is not None and not st.indoor() and not st.vertical():
                me.goal = max(min(hold_w - (st.z[0x64] * 256 + st.z[0x65]), 0xd8), EDGE)
            elif st.alive(HUMAN) and not st.indoor() and not st.vertical():
                g = st.x(HUMAN) + OFFSET.get(role or "cover", -20)
                if st.x(HUMAN) < 0x40: g = min(g, contra.SCROLL_X - 8)   # P1 hangs back: no scroll to drag them
                me.goal = max(min(g, 0xd8), EDGE)                         # into the corner (and stop P2 there)
            elif st.over(HUMAN): me.goal = 0xc0                 # alone: push on (the 2-player scroll point is 0xb0)
            elif not st.alive(HUMAN) and not st.indoor() and not st.vertical():
                me.goal = min(me.goal, contra.SCROLL_X - 8)      # P1 drops back in: no scroll under them
            # the waterfall: a climb above 0x50 scrolls the screen and pushes P1 down; not while P1 is low on it
            me.ceiling = 0x50 if st.vertical() and st.alive(HUMAN) and st.y(HUMAN) > 0x90 else 0
            if item is None and order["item"] != "take": me.pickup = False   # a TAKE holds for the weapon it was about
            for i, sd in ((ME, me), (HUMAN, stand)):
                if not sd: continue
                press(i, sd.step(st), st.frame())
                if sd.jump_t == sd.n:                             # a take-off: why, where, toward what
                    sd.took = dict(jump="P%d" % (i + 1), note=sd.note, x=st.x(i), y=st.y(i), goal=sd.goal, d=sd.jump_d,
                                   scr=st.z[0x64], px=st.z[0x65], other=st.x(1 - i), role=role)
                    log(sd.took)
                if sd.stall: log(dict(sd.stall, who="P%d" % (i + 1), role=role)); sd.stall = None
            if time.time() - mem.get("status", 0) > 0.5:          # what each soldier is doing, for a look from outside
                mem["status"] = time.time()
                try:
                    with open("/dev/shm/autogamer/contra.tmp", "w") as f:
                        for i, sd in ((ME, me), (HUMAN, stand)):
                            if sd: f.write("P%d x %d y %d goal %d btn %s note %s target %s leap %s climb %s\n" % (
                                i + 1, st.x(i), st.y(i), sd.goal, held[i], sd.note, sd.target, sd.leap, sd.climb_x))
                        f.write("role %s pickup %s item %s order %s\n" % (role, me.pickup, item, order))
                    os.replace("/dev/shm/autogamer/contra.tmp", "/dev/shm/autogamer/contra.txt")
                except OSError: pass
            prev = st
            time.sleep(0.002)
    finally:
        for p in pads: p.release_all()
        save_hist(hist)
        if LOG: LOG.close()
    print("%d calls in %.0f s, mean think %.1f s" % (n, time.time() - t0, sum(thinks) / max(len(thinks), 1)))
