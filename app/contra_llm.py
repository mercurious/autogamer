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
# AG_CT_STANDIN=1: a reflex soldier plays P1 too (no human: to watch, and to test). AG_CT_RECORD: a JSON file that
# keeps the record across games, per kind of partner (human or stand-in), stage and call; the question gives it as
# rates (lives lost and screens gained a minute), so what one session learns, the next is told.
# Usage: contra_llm.py SECONDS [log.jsonl]   env: TL_CALIB, TL_TTS, TL_THINK0, AG_MODEL_LABEL, VS_PORT,
#   AG_CT_KONAMI, AG_CT_STANDIN, AG_CT_RECORD
import json, os, random, re, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from ra import RA; from pad import Pad; import llm, voice
import contra
LLM = "http://127.0.0.1:%s" % os.environ.get("VS_PORT", "8099"); TTS = os.environ.get("TL_TTS", "0") == "1"
MODEL = os.environ.get("AG_MODEL_LABEL", "model"); CALIB = os.environ.get("TL_CALIB")
THINK0 = float(os.environ.get("TL_THINK0", "4")); KONAMI = os.environ.get("AG_CT_KONAMI") == "1"
STANDIN = os.environ.get("AG_CT_STANDIN") == "1"; RECORD = os.environ.get("AG_CT_RECORD")
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
          "lives you may BORROW one of theirs or SIT OUT. Each turn you get the stage, both players, the enemies, "
          "your record with each call this stage, and lettered choices. Reply exactly as: PICK <letter>")

def save(path, xs):
    if not path or len(xs) < 3: return
    try:
        with open(path + ".tmp", "w") as f: f.write("%.2f\n" % (sum(xs) / len(xs)))
        os.replace(path + ".tmp", path)
    except OSError: pass

def ask(text):
    return llm.chat(LLM, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}], 6, 0.3, 120, cache=True)[0]

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

def facts(st, rec, order, now, item, lost, t_now, past=""):
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
    return "\n".join(lines + ["%s) %s" % ("ABCDE"[i], c) for i, c in enumerate(order)])

def options(st, item):
    """the lettered choices now: (keys, texts)"""
    if st.over(ME):
        keys = ["borrow", "sitout"] if st.lives(HUMAN) >= 1 and not st.over(HUMAN) else ["sitout"]
        txt = {"borrow": TEXT["borrow"] % max(st.lives(HUMAN) - 1, 0), "sitout": TEXT["sitout"] % st.lives(HUMAN)}
    else:
        keys = list(ROLES) + (["take"] if item is not None else [])
        txt = dict(TEXT); txt["take"] = TEXT["take"] % (item_name(st, item) if item is not None else "weapon")
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

    def bump(key, **kw):
        """add to the record across games: this partner, this stage, this call"""
        if stage is None or key not in ROLES: return
        r = hist.setdefault(PARTNER, {}).setdefault(str(stage), {}).setdefault(key, dict(secs=0.0, p1=0, p2=0, screens=0))
        for k, v in kw.items(): r[k] += v

    def busy(): return worker is not None and worker.is_alive()

    def ask_now(st, item):
        global worker, last_ask
        keys, texts = options(st, item)
        box = dict(keys=keys, item=item, stage=st.level(), t=time.time()); pending.append(box); last_ask = time.time()
        text = facts(st, rec, texts, role, item, lost, time.time(), hist_text(hist, st.level()))
        def think(text=text, box=box):
            t1 = time.time()
            try: box["ans"] = ask(text)
            except Exception as ex: box["ans"] = "ERROR %s" % ex
            box["dt"] = time.time() - t1; thinks.append(box["dt"]); save(CALIB, thinks[1:][-50:])
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
                                 note=(me if i == ME else stand).note if (i == ME or stand) else ""))

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
                    me.pickup = pick == "take"
                    new = "cover" if pick == "take" else pick
                    if pick == "take":
                        if item is not None and item in st.slots() and item not in item_said:
                            spoken = SAY["take"] % item_name(st, item); item_said.add(item)
                    elif item is not None and item in st.slots() and item not in item_said:
                        spoken = SAY["leave"] % item_name(st, item); item_said.add(item)
                    if new != role:
                        close_role(st); role = new; spoken = spoken or SAY[new]
                    if role in ROLES: rec.setdefault(role, dict(n=0, secs=0.0, p1=0, p2=0, screens=0))["n"] += 1
                if spoken: say(spoken, show="%s: %s" % (MODEL, spoken))
                log(dict(call=pick, parsed=bool(mm), think_s=round(b["dt"], 2), answer=b["ans"], stage=stage, scr=st.z[0x64]))

            item_said = {k for k in item_said if k in st.slots() and st.etype(k) in (0x00, 0x03)}   # gone: forgotten
            # ask again whenever the model is free (at most every 2 s), at once when a weapon shows up
            item = me.item(st)
            if item is None:
                cap = [k for k in st.slots() if st.etype(k) == 0x03]; item = cap[0] if cap else None
            if not busy() and st.playing() and not st.z[0x25] and (time.time() - last_ask > 2 or item is not None and item not in item_said and not pending):
                ask_now(st, item)

            # the soldiers: P2 keeps its place from P1 by the standing call; never at the left edge while P1 pushes on
            if st.alive(HUMAN) and not st.indoor() and not st.vertical():
                g = st.x(HUMAN) + OFFSET.get(role or "cover", -20)
                me.goal = max(min(g, 0xd8), EDGE)
            elif not st.alive(HUMAN): me.goal = 0xc0            # alone: push on (the 2-player scroll point is 0xb0)
            # the waterfall: a climb above 0x50 scrolls the screen and pushes P1 down; not while P1 is low on it
            me.ceiling = 0x50 if st.vertical() and st.alive(HUMAN) and st.y(HUMAN) > 0x90 else 0
            if item is None: me.pickup = False                    # a TAKE holds for the weapon it was about
            press(ME, me.step(st), st.frame())
            if stand: press(HUMAN, stand.step(st), st.frame())
            if time.time() - mem.get("status", 0) > 0.5:          # what each soldier is doing, for a look from outside
                mem["status"] = time.time()
                try:
                    with open("/dev/shm/autogamer/contra.tmp", "w") as f:
                        for i, sd in ((ME, me), (HUMAN, stand)):
                            if sd: f.write("P%d x %d y %d goal %d btn %s note %s target %s leap %s climb %s\n" % (
                                i + 1, st.x(i), st.y(i), sd.goal, held[i], sd.note, sd.target, sd.leap, sd.climb_x))
                        f.write("role %s pickup %s item %s\n" % (role, me.pickup, item))
                    os.replace("/dev/shm/autogamer/contra.tmp", "/dev/shm/autogamer/contra.txt")
                except OSError: pass
            prev = st
            time.sleep(0.002)
    finally:
        for p in pads: p.release_all()
        save_hist(hist)
        if LOG: LOG.close()
    print("%d calls in %.0f s, mean think %.1f s" % (n, time.time() - t0, sum(thinks) / max(len(thinks), 1)))
