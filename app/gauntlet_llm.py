#!/usr/bin/env python3
# Runs on the handheld: the language model captains Players 2, 3 and 4 in Gauntlet IV (Tengen, 1993; genesis_plus_gx),
# beside a human Player 1. Three reflex heroes (gauntlet.py) walk, aim, fire and get out of each other's way frame by
# frame; the model makes the calls a captain makes, a few seconds apart, one standing until the next: which generator
# to destroy first, who takes a key to which door, when to stop fighting and leave. Its first job is to keep the
# group together and moving: four heroes share one screen, and a group that only survives still loses, because a
# generator left standing goes on making monsters.
# Each question carries everyone's health and keys, the monsters, the near generators, the keys, the doors and the
# exit, and when the group has stopped, what blocks each hero. Until an answer comes, or when one has gone stale, a
# plain rule picks the call: the game does not wait.
# Player 1 picks a hero before the game (AG_GT_HUMAN 0-3, run.sh); the other three join when Player 1 has, and come
# back with START when they fall while the game still gives credits. Player 1 can talk to them (AG_GT_VOICE=1,
# talk.py): hold R1, say an order, let go. "kill the generator", "get the key", "open the door", "to the exit", "stay
# with me", "hold" (then "go"), "your call". An order stands until it is done or Player 1 changes it, and the model's
# calls wait. Anything else goes to the model with its next question, and it answers in a few words.
# AG_GT_STANDIN=1: Player 1 is a fourth hero on the same calls, and this script presses through the menus (no human:
# to watch, and to test).
# Usage: gauntlet_llm.py SECONDS [log.jsonl]   env: TL_CALIB, TL_TTS, AG_MODEL_LABEL, VS_PORT, AG_GT_STANDIN,
#   AG_GT_HUMAN, AG_GT_VOICE
import json, os, random, re, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from ra import RA; from pad import Pad; import llm, voice
import gauntlet as g
LLM = "http://127.0.0.1:%s" % os.environ.get("VS_PORT", "8099"); TTS = os.environ.get("TL_TTS", "0") == "1"
MODEL = os.environ.get("AG_MODEL_LABEL", "model"); CALIB = os.environ.get("TL_CALIB")
STANDIN = os.environ.get("AG_GT_STANDIN") == "1"; VOICE = os.environ.get("AG_GT_VOICE") == "1"
HUMAN = int(os.environ.get("AG_GT_HUMAN", "0") or 0)
LETTERS = "ABCDEF"
FROZEN = 3.0        # seconds with nobody moving before the model is asked at once
def system(human):
    mine = [n for k, n in enumerate(g.PLAYERS) if k != human]
    return ("You are the captain of %s, %s and %s in Gauntlet IV, a maze game, beside a human Player 1, the %s. Your heroes "
            "walk, aim and shoot by themselves; you make one call for all three, and it stands until your next one. All "
            "four share one screen, which follows the group, and nobody can walk through anybody. Health drains all the "
            "time, so keep moving. Monsters come from generators: a generator left standing makes monsters for ever, so "
            "destroy one that is making monsters near you, but when none is, head for the way out: time spent wandering is "
            "health lost. Doors need a key, held by one hero and spent on touching. The level ends only when all four are "
            "on the exit. Each turn you get the situation and lettered choices. Reply exactly as: PICK <letter>" % (
                mine[0], mine[1], mine[2], g.PLAYERS[human]))

ORDERS = [
    ("yourcall", r"\b(your call|you decide|up to you|do your thing|your choice)\b"),
    ("kill", r"\b(generators?|spawners?|kill (it|that)|destroy|take (it|that) out|shoot (it|that))\b"),
    ("door", r"\b(doors?|open (it|that|up)|unlock)\b"),
    ("key", r"\bkeys?\b"),
    ("exit", r"\b(exit|way out|get out|leave|next level)\b"),
    ("follow", r"\b(follow|stay with|with me|come (here|to me|back)|over here|regroup|together|help|cover|on me|behind me)\b"),
    ("hold", r"\b(hold|wait|stop|stay|freeze|hang on)\b"),
    ("go", r"\b(go|move|let'?s go|carry on|keep going|onward)\b"),
]
REPLY = {"kill": "On the generator.", "key": "Getting the key.", "door": "Going to the door.", "exit": "Heading for the exit.",
         "follow": "Right with you.", "hold": "Holding.", "go": "Moving.", "yourcall": "Okay, I'll make the calls.", "none": "I see none near."}

def order_of(words):
    w = words.lower().replace("\u2019", "'")
    for key, pat in ORDERS:
        if re.search(pat, w): return key
    return None

def resolve(key, st, sq, leader):
    """the call an order means now, or None when there is nothing for it to act on"""
    me = st.cell(leader if st.alive(leader) else st.group()[0])
    near = lambda cs: min(cs, key=lambda c: abs(c[0] - me[0]) + abs(c[1] - me[1])) if cs else None
    if key == "follow": return ("follow",)
    if key == "kill":
        c = near(sq.alive_gens(st) or sq.alive_gens(st, g.W) or [c for c in sq.gens if c not in sq.dead]); return ("kill", c) if c else None
    if key == "key": c = near(find(st, (g.KEY,))); return ("key", c) if c else None
    if key == "door": c = near(find(st, g.DOORS)); return ("door", c) if c else None
    if key == "exit": c = near(st.exits()); return ("exit", c) if c else None

SAY = {"kill": "Taking out the generator.", "key": "I'll get the key.", "door": "I've got the door.",
       "exit": "To the exit!", "follow": "With you."}

def find(st, codes): return [(r, c) for r in range(g.W) for c in range(g.W) if st.code(r, c) in codes]

def where(me, c):
    dy, dx = c[0] - me[0], c[1] - me[1]
    side = ("down" if dy > 0 else "up" if dy < 0 else "") + ("-" if dy and dx else "") + ("right" if dx > 0 else "left" if dx < 0 else "")
    return "%d cells %s" % (max(abs(dy), abs(dx)), side or "here")

def choices(st, sq, leader=HUMAN):
    """[(call, text)] that make sense now, the standing kinds first. Player 1 is never told what to do"""
    me = st.cell(leader if st.alive(leader) else st.group()[0]); out = []
    for c in sq.alive_gens(st)[:2]: out.append((("kill", c), "KILL the generator making monsters %s" % where(me, c)))
    ex, doors, keys = st.exits(), find(st, g.DOORS), find(st, (g.KEY,))
    near = lambda cs: min(cs, key=lambda c: abs(c[0] - me[0]) + abs(c[1] - me[1]))
    who = [i for i in st.group() if st.keys(i)]
    open_way = bool(ex and g.route(st, me, ex[0]))
    if ex and open_way: out.append((("exit", ex[0]), "EXIT: everyone to the exit, %s" % where(me, ex[0])))
    if doors and who and not open_way:
        c = near(doors); out.append((("door", c), "OPEN the door %s: %s has a key" % (where(me, c), g.PLAYERS[who[0]])))
    if keys and (not open_way or not who):
        c = near(keys); out.append((("key", c), "GET the key %s" % where(me, c)))
    out.append((("follow",), "STAY with the %s (player 1)" % g.PLAYERS[leader]))
    return out[:len(LETTERS)]

def rule(st, sq, leader=HUMAN):
    """the plain call when there is no answer: near generators first, then the way out"""
    return choices(st, sq, leader)[0][0]

def facts(st, sq, order, now, frozen, stood, orders=""):
    lines = ["Gauntlet IV: %d monsters near, %d generators making monsters near you, %d destroyed so far." % (
        len(sq.foes), len(sq.alive_gens(st)), sq.killed)]
    for i in range(4):
        who = "%s (%s)" % (g.PLAYERS[i], "the human" if i == HUMAN and not STANDIN else "yours")
        lines.append("%s: %s." % (who, "out" if not st.alive(i) else "health %d, %d keys" % (st.hp(i), st.keys(i))))
    if frozen > 2:
        lines.append("Nobody has moved for %d s. The screen fills up at %d px tall; the group is %d px tall." % (frozen, g.VIEW_H, st.span()[0]))
        lines += g.describe(st)
    if now: lines.append("Your standing call: %s, for %d s." % (now.upper(), stood))
    if orders: lines.append(orders)
    return "\n".join(lines + ["%s) %s" % (LETTERS[i], t) for i, t in enumerate(order)])

def pick(ans, n):
    m = re.search(r"PICK\s*\(?([A-F])\)?", ans or "")
    i = LETTERS.index(m.group(1)) if m else -1
    return i if 0 <= i < n else None

def ask(text, reply=False):
    if reply: text += "\nReply as: PICK <letter>, then a new line: SAY <a few words back to player 1>"
    return llm.chat(LLM, [{"role": "system", "content": system(HUMAN)}, {"role": "user", "content": text}], 32 if reply else 6,
                    0.3, 120, cache=True)[0]

def still_good(st, sq, call):
    """a standing call that has run its course no longer stands"""
    k = call[0]
    if k == "kill": return call[1] in sq.gens and call[1] not in sq.dead
    if k == "key": return st.code(*call[1]) == g.KEY
    if k == "door": return st.code(*call[1]) in g.DOORS and any(st.keys(i) for i in st.group())
    return True

def save(path, xs):
    if not path or len(xs) < 3: return
    try:
        with open(path + ".tmp", "w") as f: f.write("%.2f\n" % (sum(xs) / len(xs)))
        os.replace(path + ".tmp", path)
    except OSError: pass

if __name__ == "__main__":
    T = float(sys.argv[1]); LOG = open(sys.argv[2], "a") if len(sys.argv) > 2 else None
    ra = RA(timeout=0.2); pads = [Pad(user=g.pad_of(i, HUMAN)) for i in range(4)]
    if "PAUSED" in (ra.cmd("GET_STATUS") or ""): ra.cmd("PAUSE_TOGGLE", reply=False)
    heroes = tuple(i for i in range(4) if STANDIN or i != HUMAN)
    t0 = time.time(); sq = g.Squad(heroes, HUMAN); grid = g.read_maze(ra); call = ("follow",); call_t = t0; worker = None; box = None
    thinks = []; stats = dict(asked=0, model=0, rule=0, order=0, parsed=0, levels=0); gt = ot = last_ask = 0; pp = None; moved = t0
    order = None; held = False; told = []; heard = []; join_t = {}; menu_t = 0
    log = lambda d: LOG and (LOG.write(json.dumps(dict(t=round(time.time() - t0, 1), **d)) + "\n"), LOG.flush())

    if VOICE:
        import talk
        talk.Talk(lambda: heard.append(("listen",)), lambda w, secs, why="": heard.append(("text", w, secs, why))).start()

    def say(line, show=None):
        if TTS: voice.say(line, show=show, ra=ra)
        elif show: ra.cmd("SHOW_MSG " + show, reply=False)

    def orders_text():
        out = []
        if order: out.append("Player 1 has ordered %s: it stands until it is done." % order.upper())
        if told: out.append('Player 1 just said to you: "%s"' % " / ".join(told))
        return "\n".join(out)

    def obey(st, key, words):
        global order, held
        if key is None: told.append(words[:120]); return None
        if key == "yourcall": order = None; held = False; return REPLY[key]
        if key == "hold": held = True; return REPLY[key]
        if key == "go": held = False; return REPLY[key]
        c = resolve(key, st, sq, HUMAN)
        if c is None: return REPLY["none"]
        held = False; order = key; set_call(c, "order"); return REPLY[key]

    def busy(): return worker is not None and worker.is_alive()

    def question(st, now):
        global worker, box, last_ask
        opts = choices(st, sq); random.shuffle(opts)
        text = facts(st, sq, [o[1] for o in opts], call[0], now - moved if now - moved > 2 else 0, now - call_t, orders_text())
        box = dict(opts=opts, t=now, frozen=round(now - moved, 1), told=list(told)); told.clear()
        stats["asked"] += 1; last_ask = now
        if stats["asked"] <= 3 or stats["asked"] % 20 == 0: box["q"] = text
        def think(text=text, b=box):
            t1 = time.time()
            try: b["ans"] = ask(text, reply=bool(b["told"]))
            except Exception as ex: b["ans"] = "ERROR %s" % ex
            b["dt"] = time.time() - t1; thinks.append(b["dt"]); save(CALIB, thinks[1:][-50:])
        worker = threading.Thread(target=think, daemon=True); worker.start()

    def set_call(new, why):
        global call, call_t
        if new == call: return
        call = new; call_t = time.time(); stats[why] += 1
        if why == "model" and TTS and new[0] in SAY: voice.say(SAY[new[0]], show="%s: %s" % (MODEL, SAY[new[0]]), ra=ra)

    try:
        while time.time() - t0 < T:
            st = g.read(ra, grid)
            now = time.time()
            if not st: time.sleep(0.05); continue
            joined = [i for i in range(4) if st.joined(i)]
            if STANDIN and not joined and now - menu_t > 2.5:          # the stand-in presses through the menus
                menu_t = now; pads[HUMAN].tap("start", 0.1)
            if joined:                           # a hero joins with START once Player 1 has, and again when it falls
                for i in heroes:
                    if not st.joined(i) and now - join_t.get(i, 0) > 2: join_t[i] = now; pads[i].tap("start", 0.06)
            if st.alive(HUMAN) or st.group():    # Player 1's C starts the level; each hero then needs its own
                for i in heroes:
                    if st.joined(i) and not st.alive(i) and now - join_t.get(i, 0) > 1: join_t[i] = now; pads[i].tap("a", 0.06)
            if not st.group():
                if STANDIN and joined and now - menu_t > 2.5: menu_t = now; pads[HUMAN].tap("a", 0.1)
                time.sleep(0.05); continue
            if now - gt > 0.3:
                gt = now; ng = g.read_maze(ra)
                if ng and ng != grid:
                    if sum(1 for a, b in zip(ng, grid) if a != b) > 40 and now - stats.get("level_t", 0) > 5:      # written in two goes
                        stats["level_t"] = now; stats["levels"] += 1; log(dict(level=stats["levels"], hp=[st.hp(i) for i in range(4)], killed=sq.killed))
                        sq = g.Squad(heroes, HUMAN); call = ("follow",); box = None; order = None; held = False
                    grid = ng; st = g.State(st.m, grid)
            if now - ot > 0.1:
                ot = now; o = g.read_objects(ra)
                if o: sq.update(o, now)
            pos = [st.pos(i) for i in st.group()]
            if pos != pp: pp = pos; moved = now
            if box and "ans" in box:
                i = pick(box["ans"], len(box["opts"])); stats["parsed"] += i is not None
                c, t = box["opts"][i if i is not None else 0]
                if box["told"]:
                    back = [l for l in box["ans"].splitlines()[1:] if l.strip()]
                    if back: say(re.sub(r"^\W*SAY\W*", "", back[0]).strip().strip('"')[:90], show=MODEL + ": " + back[0][:70])
                log(dict(call=c, text=t, parsed=i is not None, think_s=round(box["dt"], 2), frozen=box["frozen"],
                         stale=not still_good(st, sq, c), **({"q": box["q"]} if "q" in box else {})))
                if still_good(st, sq, c) and not order: set_call(c, "model")
                box = None
            while heard:
                ev = heard.pop(0)
                if ev[0] == "listen": ra.cmd("SHOW_MSG %s is listening... (let go of R1)" % MODEL, reply=False); continue
                _, words, secs, why = ev
                if not words:
                    if why: ra.cmd("SHOW_MSG " + why, reply=False)
                    log(dict(heard="", why=why)); continue
                key = order_of(words); answer = obey(st, key, words)
                log(dict(heard=words, asr_s=round(secs, 2), order=key))
                if answer: say(answer, show='You: "%s"  %s: %s' % (words[:50], MODEL, answer))
                else: ra.cmd('SHOW_MSG You: "%s"' % words[:70], reply=False)
            if order and not still_good(st, sq, call): order = None      # the order is done: the model's again
            if not still_good(st, sq, call) or (call[0] == "follow" and stats["model"] == 0 and not order): set_call(rule(st, sq), "rule")
            if not busy() and (now - last_ask > 2 or now - moved > FROZEN): question(st, now)
            for i, b in sq.step(st, ("hold",) if held else call, now).items(): pads[i].hold(b)
            if LOG and int(now - t0) % 10 == 0 and now - stats.get("beat", 0) > 5:
                stats["beat"] = now; log(dict(beat=call, pos=pos, hp=[st.hp(i) for i in range(4)], foes=len(sq.foes), killed=sq.killed, frozen=round(now - moved, 1)))
    finally:
        for p in pads: p.release_all()
        if LOG: LOG.close()
    print("%d answers in %.0f s, mean think %.1f s, %s" % (len(thinks), time.time() - t0, sum(thinks) / max(len(thinks), 1), stats))
