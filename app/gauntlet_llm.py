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
# AG_GT_STANDIN=1: Player 1 is a fourth hero on the same calls (no human: to watch, and to test).
# Usage: gauntlet_llm.py SECONDS [log.jsonl]   env: TL_CALIB, TL_TTS, AG_MODEL_LABEL, VS_PORT, AG_GT_STANDIN
import json, os, random, re, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from ra import RA; from pad import Pad; import llm, voice
import gauntlet as g
LLM = "http://127.0.0.1:%s" % os.environ.get("VS_PORT", "8099"); TTS = os.environ.get("TL_TTS", "0") == "1"
MODEL = os.environ.get("AG_MODEL_LABEL", "model"); CALIB = os.environ.get("TL_CALIB")
STANDIN = os.environ.get("AG_GT_STANDIN") == "1"
LETTERS = "ABCDEF"
FROZEN = 3.0        # seconds with nobody moving before the model is asked at once
SYSTEM = ("You are the captain of Valkyrie, Wizard and Elf in Gauntlet IV, a maze game, beside a human Player 1, the "
          "Warrior. Your heroes walk, aim and shoot by themselves; you make one call for all three, and it stands until "
          "your next one. All four share one screen, which follows the group, and nobody can walk through anybody. "
          "Health drains all the time, so keep moving. Monsters come from generators: a generator left standing makes "
          "monsters for ever, so destroy one that is making monsters near you, but when none is, head for the way out: "
          "time spent wandering is health lost. Doors need a key, "
          "held by one hero and spent on touching. The level ends only when all four are on the exit. Each turn you get "
          "the situation and lettered choices. Reply exactly as: PICK <letter>")
SAY = {"kill": "Taking out the generator.", "key": "I'll get the key.", "door": "I've got the door.",
       "exit": "To the exit!", "follow": "With you."}

def find(st, codes): return [(r, c) for r in range(g.W) for c in range(g.W) if st.code(r, c) in codes]

def where(me, c):
    dy, dx = c[0] - me[0], c[1] - me[1]
    side = ("down" if dy > 0 else "up" if dy < 0 else "") + ("-" if dy and dx else "") + ("right" if dx > 0 else "left" if dx < 0 else "")
    return "%d cells %s" % (max(abs(dy), abs(dx)), side or "here")

def choices(st, sq, leader=0):
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
    out.append((("follow",), "STAY with player 1"))
    return out[:len(LETTERS)]

def rule(st, sq, leader=0):
    """the plain call when there is no answer: near generators first, then the way out"""
    return choices(st, sq, leader)[0][0]

def facts(st, sq, order, now, frozen, stood):
    lines = ["Gauntlet IV: %d monsters near, %d generators making monsters near you, %d destroyed so far." % (
        len(sq.foes), len(sq.alive_gens(st)), sq.killed)]
    for i in range(4):
        who = "%s (%s)" % (g.PLAYERS[i], "the human" if i == 0 and not STANDIN else "yours")
        lines.append("%s: %s." % (who, "out" if not st.alive(i) else "health %d, %d keys" % (st.hp(i), st.keys(i))))
    if frozen > 2:
        lines.append("Nobody has moved for %d s. The screen fills up at %d px tall; the group is %d px tall." % (frozen, g.VIEW_H, st.span()[0]))
        lines += g.describe(st)
    if now: lines.append("Your standing call: %s, for %d s." % (now.upper(), stood))
    return "\n".join(lines + ["%s) %s" % (LETTERS[i], t) for i, t in enumerate(order)])

def pick(ans, n):
    m = re.search(r"PICK\s*\(?([A-F])\)?", ans or "")
    i = LETTERS.index(m.group(1)) if m else -1
    return i if 0 <= i < n else None

def ask(text):
    return llm.chat(LLM, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}], 6, 0.3, 120, cache=True)[0]

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
    ra = RA(timeout=0.2); pads = [Pad(user=i) for i in range(4)]
    if "PAUSED" in (ra.cmd("GET_STATUS") or ""): ra.cmd("PAUSE_TOGGLE", reply=False)
    heroes = (0, 1, 2, 3) if STANDIN else (1, 2, 3)
    t0 = time.time(); sq = g.Squad(heroes); grid = g.read_maze(ra); call = ("follow",); call_t = t0; worker = None; box = None
    thinks = []; stats = dict(asked=0, model=0, rule=0, parsed=0, levels=0); gt = ot = last_ask = 0; pp = None; moved = t0
    log = lambda d: LOG and (LOG.write(json.dumps(dict(t=round(time.time() - t0, 1), **d)) + "\n"), LOG.flush())

    def busy(): return worker is not None and worker.is_alive()

    def question(st, now):
        global worker, box, last_ask
        opts = choices(st, sq); random.shuffle(opts)
        text = facts(st, sq, [o[1] for o in opts], call[0], now - moved if now - moved > 2 else 0, now - call_t)
        box = dict(opts=opts, t=now, frozen=round(now - moved, 1))
        stats["asked"] += 1; last_ask = now
        if stats["asked"] <= 3 or stats["asked"] % 20 == 0: box["q"] = text
        def think(text=text, b=box):
            t1 = time.time()
            try: b["ans"] = ask(text)
            except Exception as ex: b["ans"] = "ERROR %s" % ex
            b["dt"] = time.time() - t1; thinks.append(b["dt"]); save(CALIB, thinks[1:][-50:])
        worker = threading.Thread(target=think, daemon=True); worker.start()

    def set_call(new, why):
        global call, call_t
        if new == call: return
        call = new; call_t = time.time(); stats[why] += 1
        if why == "model" and TTS: voice.say(SAY[new[0]], show="%s: %s" % (MODEL, SAY[new[0]]), ra=ra)

    try:
        while time.time() - t0 < T:
            st = g.read(ra, grid)
            if not st or not st.group(): time.sleep(0.05); continue
            now = time.time()
            if now - gt > 0.3:
                gt = now; ng = g.read_maze(ra)
                if ng and ng != grid:
                    if sum(1 for a, b in zip(ng, grid) if a != b) > 40:
                        stats["levels"] += 1; log(dict(level=stats["levels"], hp=[st.hp(i) for i in range(4)], killed=sq.killed))
                        sq = g.Squad(heroes); call = ("follow",); box = None
                    grid = ng; st = g.State(st.m, grid)
            if now - ot > 0.1:
                ot = now; o = g.read_objects(ra)
                if o: sq.update(o, now)
            pos = [st.pos(i) for i in st.group()]
            if pos != pp: pp = pos; moved = now
            if box and "ans" in box:
                i = pick(box["ans"], len(box["opts"])); stats["parsed"] += i is not None
                c, t = box["opts"][i if i is not None else 0]
                log(dict(call=c, text=t, parsed=i is not None, think_s=round(box["dt"], 2), frozen=box["frozen"],
                         stale=not still_good(st, sq, c), **({"q": box["q"]} if "q" in box else {})))
                if still_good(st, sq, c): set_call(c, "model")
                box = None
            if not still_good(st, sq, call) or (call[0] == "follow" and stats["model"] == 0): set_call(rule(st, sq), "rule")
            if not busy() and (now - last_ask > 2 or now - moved > FROZEN): question(st, now)
            for i, b in sq.step(st, call, now).items(): pads[i].hold(b)
            if LOG and int(now - t0) % 10 == 0 and now - stats.get("beat", 0) > 5:
                stats["beat"] = now; log(dict(beat=call, pos=pos, hp=[st.hp(i) for i in range(4)], foes=len(sq.foes), killed=sq.killed, frozen=round(now - moved, 1)))
    finally:
        for p in pads: p.release_all()
        if LOG: LOG.close()
    print("%d answers in %.0f s, mean think %.1f s, %s" % (len(thinks), time.time() - t0, sum(thinks) / max(len(thinks), 1), stats))
