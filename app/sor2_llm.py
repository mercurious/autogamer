#!/usr/bin/env python3
# Runs on the handheld: the language model is Player 2 in Streets of Rage 2 (Sega, 1992; genesis_plus_gx), fighting
# beside a human Player 1 on the handheld's own controls. A reflex fighter (sor2.py) plays P2 frame by frame from RAM:
# it lines up with its target, combos, turns, throws a special when boxed in, and picks things up. The model makes
# the calls a partner makes, a few seconds apart, each standing until the next: HELP (go to player 1 and fight
# whoever is on them), SPLIT (take on the punks away from player 1 and draw them off), FOCUS (gang up with player 1
# on the toughest one); with food on the ground, EAT it (else it is left for player 1); and when P2 is out of lives,
# CONTINUE (the game's own continue) or SIT OUT. Each question carries the human's state (health, lives, health lost
# lately), the punks and who they are on, and the model's record with each call this stage: health both players lost
# while it stood, and the punks put away.
# The human picks 2 PLAYERS (or 1 PLAYER: P2 joins with START); at the character screen P2 takes the fighter its
# cursor is on once P1 has chosen. Player 1 can talk to P2 (AG_SR_VOICE=1, talk.py): hold R1, say an order, let go.
# "help me" / "cover me", "split up" / "take the others", "the big guy" / "focus", "eat it" / "that's mine", "hang
# back" / "wait" (then "go"), "continue" / "don't continue", "your call". An order stands until P1 changes it; P2
# answers out loud. Anything else goes to the model with its next question, and it answers in a few words.
# AG_SR_STANDIN=1: a reflex fighter plays P1 too (no human: to watch, and to test). AG_SR_RECORD: a JSON file that
# keeps the record across games, per kind of partner, stage and call, given to the model as rates.
# Usage: sor2_llm.py SECONDS [log.jsonl]   env: TL_CALIB, TL_TTS, TL_THINK0, AG_MODEL_LABEL, VS_PORT,
#   AG_SR_STANDIN, AG_SR_RECORD, AG_SR_VOICE
import json, os, random, re, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from ra import RA; from pad import Pad; import llm, voice
import sor2
LLM = "http://127.0.0.1:%s" % os.environ.get("VS_PORT", "8099"); TTS = os.environ.get("TL_TTS", "0") == "1"
MODEL = os.environ.get("AG_MODEL_LABEL", "model"); CALIB = os.environ.get("TL_CALIB")
STANDIN = os.environ.get("AG_SR_STANDIN") == "1"; RECORD = os.environ.get("AG_SR_RECORD")
VOICE = os.environ.get("AG_SR_VOICE") == "1"
PARTNER = "standin" if STANDIN else "human"
ME, HUMAN = 1, 0
ROLES = ("help", "split", "focus")
TEXT = {"help": "HELP: go to player 1 and fight whoever is on them",
        "split": "SPLIT: take on the punks away from player 1 and draw them off",
        "focus": "FOCUS: gang up with player 1 on the toughest punk (%s)",
        "eat": "EAT the %s yourself (else it is left for player 1)",
        "continue": "CONTINUE: use a continue and come back in",
        "sitout": "SIT OUT: leave the continues to player 1"}
SAY = {"help": "I'm coming!", "split": "I'll take these guys.", "focus": "Let's take him down together.",
       "eat": "I'll grab the %s.", "leave": "The %s is yours.", "continue": "I'm back!", "sitout": "I'll sit this one out."}
SYSTEM = ("You are Player 2 in Streets of Rage 2 (Sega Genesis, 1992), a street brawler, fighting beside a human "
          "Player 1. Your fighter walks, punches, grabs and dodges by itself; you make a partner's calls, and each "
          "call stands until your next one: HELP (go to player 1 and fight whoever is on them), SPLIT (take on the "
          "punks away from player 1 and draw them off, so player 1 is not surrounded), FOCUS (gang up with player 1 on "
          "the toughest punk). When food lies on the ground you may EAT it; otherwise you leave it for player 1. Food "
          "heals whoever eats it: give it to whoever needs it more. Player 1 is a person: keep them alive and the "
          "fight moving forward. If you run out of lives you may CONTINUE or SIT OUT. Player 1 can talk to you; their "
          "orders stand until they change them, so follow them. Each turn you get the stage, both players, the punks, "
          "your record with each call this stage, and lettered choices. Reply exactly as: PICK <letter>")

ORDERS = [
    ("nocontinue", r"\b(don'?t|do not|no|never|stop)\b.{0,12}\bcontinu\w*"),
    ("continue", r"\bcontinu\w*|\bcome back\b|\bget back in\b|\bjoin\b"),
    ("leave", r"\b(leave|skip)\b.{0,10}\b(it|that|the|this|food|apple|chicken)\b|\b(that'?s|it'?s|that is|it is)\s+mine\b|"
              r"\b(don'?t|do not)\b.{0,8}\b(eat|take|grab|get)\b|\bi'?(ll| will)\s+(eat|get|take|grab)\b|^\W*mine\b|\bi need (it|that|the)\b"),
    ("eat", r"\b(eat|grab|get|take|pick up|have)\b\s+(the |that |this |some |a )?(it|that|this|food|apple|chicken|meat|turkey|health)\b|"
            r"\b(you eat|you take it|it'?s (all )?yours|you have it|all yours|you need it)\b"),
    ("yourcall", r"\b(your call|you decide|up to you|do your thing|your choice|play (it )?your way)\b"),
    ("focus", r"\b(focus|big (guy|one|man)|boss|the tough|gang up|together on|double team|all on (him|her|that)|the strong)\w*"),
    ("split", r"\b(split( up)?|spread out|take (the )?(others|other ones|rest|ones on the)|draw them|divide|the ones behind|"
              r"you take (those|them|that side)|left side|right side|on the left|on the right|your own)\b"),
    ("help", r"\b(help|cover|back me up|on me|with me|behind me|save me|get (him|them|these guys) off|protect|"
             r"come here|over here|i'?m (surrounded|dying|in trouble))\w*"),
    ("hold", r"\b(hold|wait|stop|stay|hang back|fall back|back off|stay back|easy|freeze)\b"),
    ("go", r"\b(go|move|let'?s go|come on|onward|forward|attack|fight|get (him|them|'em))\b"),
]
REPLY = {"help": "On my way!", "split": "I'll take the others.", "focus": "Together, then!", "hold": "Hanging back.",
         "go": "Let's go!", "eat": "Thanks, I'll eat it.", "eat_later": "I'll eat the next one.", "leave": "It's all yours.",
         "continue": "I'll come back in if I go down.", "continue_now": "Coming back in!",
         "nocontinue": "Okay, I won't use a continue.", "yourcall": "Okay, I'll make the calls."}

def order_of(words):
    w = words.lower().replace("’", "'")
    for key, pat in ORDERS:
        if re.search(pat, w): return key
    return None

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

def load_hist():
    try: return json.load(open(RECORD))
    except (TypeError, OSError, ValueError): return {}

def save_hist(hist):
    if not RECORD: return
    try:
        with open(RECORD + ".tmp", "w") as f: json.dump(hist, f)
        os.replace(RECORD + ".tmp", RECORD)
    except OSError: pass

def new_rec(): return dict(n=0, secs=0.0, p1=0, p2=0, kos=0)

def hist_text(hist, stage):
    h = hist.get(PARTNER, {}).get(str(stage), {}); parts = []
    for r in ROLES:
        x = h.get(r)
        if not x or x["secs"] < 30: continue
        m = x["secs"] / 60
        parts.append("%s %.0f min: player 1 lost %.0f health a minute, you %.0f, %.1f punks down a minute" % (
            r.upper(), m, x["p1"] / m, x["p2"] / m, x["kos"] / m))
    return "; ".join(parts)

def pct(hp): return "%d%%" % round(100 * hp / sor2.FULL)

def toughest(st, foes):
    return max(foes, key=lambda o: (st.stars(o), st.hp(o))) if foes else None

def crowd_text(st, foes):
    """who the punks are and whom they are on"""
    if not foes: return "No punks on the screen."
    h, m = st.p(HUMAN), st.p(ME); on1 = on2 = 0; names = {}
    for o in foes:
        d1 = abs(st.x(o) - st.x(h)) + 2 * abs(st.y(o) - st.y(h)) if st.alive(HUMAN) else 999
        d2 = abs(st.x(o) - st.x(m)) + 2 * abs(st.y(o) - st.y(m)) if st.alive(ME) else 999
        if min(d1, d2) < 70: on1 += d1 <= d2; on2 += d2 < d1
        names[st.name(o)] = names.get(st.name(o), 0) + 1
    t = toughest(st, foes)
    return "Punks on the screen: %s; %d on player 1, %d on you. Toughest: %s (%s health%s)." % (
        ", ".join("%d %s" % (v, n) for n, v in names.items()), on1, on2, st.name(t), pct(st.hp(t)),
        ", %d more bars" % st.stars(t) if st.stars(t) else "")

def facts(st, rec, order, now, food, lost, past="", orders=""):
    foes = [o for o in st.enemies() if st.onscreen(o, 8)]
    lines = ["Streets of Rage 2, 2 players. Stage %d of 8: %s." % (st.stage() + 1, sor2.STAGES[st.stage()])]
    recent = sum(v for t, v in lost if time.time() - t < 60)
    if not st.joined(HUMAN): lines.append("Player 1 (the human) is out of lives.")
    else: lines.append("Player 1 (the human, %s): %s health, %d lives left, lost %s health in the last minute%s." % (
        st.who(HUMAN), pct(st.php(HUMAN)), st.lives(HUMAN), pct(recent), ", holds a %s" % st.weapon(HUMAN) if st.weapon(HUMAN) else ""))
    lines.append("You (player 2, %s): %s." % (st.who(ME), "out of lives" if not st.joined(ME) else
                 "%s health, %d lives left" % (pct(st.php(ME)), st.lives(ME))))
    lines.append(crowd_text(st, foes))
    if food: lines.append("Food on the ground: %s." % food[2])
    parts = []
    for r in ROLES:
        x = rec.get(r)
        parts.append("%s never called" % r.upper() if not x else "%s %d calls, %.0f s, player 1 lost %s, you lost %s, "
                     "%d punks down" % (r.upper(), x["n"], x["secs"], pct(x["p1"]), pct(x["p2"]), x["kos"]))
    lines.append("Your record this stage: %s." % "; ".join(parts))
    if past: lines.append("Past games with %s on this stage: %s." % ("this partner" if PARTNER == "human" else "a bot partner", past))
    if now: lines.append("Your standing call: %s." % now.upper())
    if orders: lines.append(orders)
    return "\n".join(lines + ["%s) %s" % ("ABCDE"[i], c) for i, c in enumerate(order)])

def chat_facts(st, order, now, orders=""):
    lines = ["Streets of Rage 2, 2 players. Stage %d of 8: %s." % (st.stage() + 1, sor2.STAGES[st.stage()]),
             "Player 1 (the human): %s." % ("out of lives" if not st.joined(HUMAN) else "%s health, %d lives" % (pct(st.php(HUMAN)), st.lives(HUMAN))),
             "You (player 2): %s." % ("out of lives" if not st.joined(ME) else "%s health, %d lives" % (pct(st.php(ME)), st.lives(ME)))]
    if now: lines.append("Your standing call: %s." % now.upper())
    if orders: lines.append(orders)
    return "\n".join(lines + ["%s) %s" % ("ABCDE"[i], c) for i, c in enumerate(order)])

def options(st, food, keep=None, may_continue=True):
    if not st.joined(ME):
        keys = ["continue", "sitout"] if may_continue else ["sitout"]
        txt = dict(TEXT)
    else:
        foes = [o for o in st.enemies() if st.onscreen(o, 8)]
        keys = list(ROLES) + (["eat"] if food else []) + (["keep"] if keep else [])
        txt = dict(TEXT); t = toughest(st, foes)
        txt["focus"] = TEXT["focus"] % (st.name(t) if t else "none on the screen")
        txt["eat"] = TEXT["eat"] % (food[2] if food else "food")
        if keep: txt["keep"] = "KEEP your standing call (%s)" % keep.upper()
    random.shuffle(keys)
    return keys, [txt[k] for k in keys]

def picker(role, hold):
    """the fighter's choice of target under a call"""
    def pick(st, foes):
        h, m = st.p(HUMAN), st.p(ME)
        mx, my = st.x(m), st.y(m)
        if not st.alive(HUMAN): return sor2.nearest(st, foes, mx, my)
        hx, hy = st.x(h), st.y(h)
        if hold[0]:      # hold: only what comes to it
            near = [o for o in foes if abs(st.x(o) - mx) < 50 and abs(st.y(o) - my) < 14]
            return sor2.nearest(st, near, mx, my)
        if role[0] == "focus":
            return toughest(st, foes)
        if role[0] == "split":
            away = [o for o in foes if abs(st.x(o) - hx) + 2 * abs(st.y(o) - hy) > 60]
            return sor2.nearest(st, away or foes, mx, my) if away else max(foes, key=lambda o: abs(st.x(o) - hx))
        return sor2.nearest(st, foes, hx, hy)          # help: whoever is on P1
    return pick

if __name__ == "__main__":
    T = float(sys.argv[1]); LOG = open(sys.argv[2], "a") if len(sys.argv) > 2 else None
    ra = RA(timeout=0.2); pads = [Pad(user=0), Pad(user=1)]
    if "PAUSED" in (ra.cmd("GET_STATUS") or ""): ra.cmd("PAUSE_TOGGLE", reply=False)
    log = lambda d: LOG and (LOG.write(json.dumps(dict(t=round(time.time() - t0, 1), **d)) + "\n"), LOG.flush())
    t0 = time.time(); worker = None; thinks = []; pending = []; n = 0; mem = {}; prev = None
    role = [None]; hold = [False]; me = sor2.Fighter(ME); me.pick = picker(role, hold)
    stand = sor2.Fighter(HUMAN) if STANDIN else None
    last_frame = [None, None]; held = [[], []]
    role_t = time.time(); stage = None; rec = {}; lost = []; food_said = set(); last_ask = 0
    hist = load_hist(); hist_t = time.time(); kos = 0
    order = dict(role=None, said="", said_t=0, food=None, food_t=0, cont=True)
    told = []; heard = []
    if VOICE:
        import talk
        talk.Talk(lambda: heard.append(("listen",)), lambda w, secs, why="": heard.append(("text", w, secs, why))).start()

    def orders_text():
        out = []
        if order["role"]: out.append('Player 1\'s standing order: %s (they said "%s" %d s ago).' % (
            order["role"].upper(), order["said"], time.time() - order["said_t"]))
        if order["food"] == "eat": out.append("Player 1 told you to eat the food.")
        if order["food"] == "leave": out.append("Player 1 wants the food for themselves.")
        if not order["cont"]: out.append("Player 1 told you not to use a continue.")
        if told: out.append('Player 1 just said to you: "%s"' % " / ".join(told))
        return "\n".join(out)

    def bump(key, **kw):
        if stage is None or key not in ROLES: return
        r = hist.setdefault(PARTNER, {}).setdefault(str(stage), {}).setdefault(key, dict(secs=0.0, p1=0, p2=0, kos=0))
        for k, v in kw.items(): r[k] += v

    def close_role():
        global role_t
        if role[0] in ROLES:
            r = rec.setdefault(role[0], new_rec()); r["secs"] += time.time() - role_t; bump(role[0], secs=time.time() - role_t)
        role_t = time.time()

    def set_role(new):
        if new != role[0]: close_role(); role[0] = new

    def obey(st, key, words):
        now = time.time()
        if key is None: told.append(words[:120]); return None
        if key in ROLES:
            hold[0] = False; set_role(key); order.update(role=key, said=words[:60], said_t=now); return REPLY[key]
        if key == "hold": hold[0] = True; order.update(said=words[:60], said_t=now); return REPLY["hold"]
        if key == "go": hold[0] = False; return REPLY["go"]
        if key == "eat":
            order.update(food="eat", food_t=now); return REPLY["eat"] if st.items() else REPLY["eat_later"]
        if key == "leave": order.update(food="leave", food_t=now); me.want = None; return REPLY["leave"]
        if key == "nocontinue": order["cont"] = False; return REPLY["nocontinue"]
        if key == "continue":
            order["cont"] = True
            if not st.joined(ME): pads[ME].tap("start", 0.08); return REPLY["continue_now"]
            return REPLY["continue"]
        if key == "yourcall": hold[0] = False; order.update(role=None, food=None); return REPLY["yourcall"]

    def busy(): return worker is not None and worker.is_alive()

    def ask_now(st, food):
        global worker, last_ask
        keys, texts = options(st, food, keep=role[0] if told and role[0] else None, may_continue=order["cont"])
        box = dict(keys=keys, food=food, t=time.time(), told=list(told)); pending.append(box); last_ask = time.time()
        mem["asked"] = mem.get("asked", 0) + 1
        if told: text = chat_facts(st, texts, role[0], orders_text())
        else: text = facts(st, rec, texts, role[0], food, lost, hist_text(hist, st.stage()), orders_text())
        told.clear()
        if mem["asked"] <= 3 or mem["asked"] % 20 == 0: box["q"] = text
        def think(text=text, box=box):
            t1 = time.time()
            try: box["ans"] = ask(text, reply=bool(box["told"]))
            except Exception as ex: box["ans"] = "ERROR %s" % ex
            box["dt"] = time.time() - t1
            if not box["told"]: thinks.append(box["dt"]); save(CALIB, thinks[1:][-50:])
        worker = threading.Thread(target=think, daemon=True); worker.start()

    def press(i, btn, frame):
        """one change a frame (RetroArch's network remote reads one message per user per frame)"""
        if frame == last_frame[i]: return
        last_frame[i] = frame
        pads[i].nudge(btn, order=("b", "y", "a", "left", "right", "up", "down", "start")); held[i] = sorted(pads[i].held)

    try:
        while time.time() - t0 < T:
            if time.time() - t0 < 20 and time.time() - mem.get("unpause", 0) > 2:
                mem["unpause"] = time.time()
                if "PAUSED" in (ra.cmd("GET_STATUS") or ""): ra.cmd("PAUSE_TOGGLE", reply=False)
            st = sor2.read(ra)
            if not st: continue
            if prev and (st.mode() != prev.mode() or st.joined(ME) != prev.joined(ME) or st.joined(HUMAN) != prev.joined(HUMAN)):
                log(dict(mode="%02x" % st.mode(), was="%02x" % prev.mode(), joined=[st.joined(0), st.joined(1)],
                         lives=[st.lives(0), st.lives(1)], hp=[st.php(0), st.php(1)], r2="%02x" % st.routine(st.p(ME))))
            if st.selecting():                       # the character screen: P2 takes its cursor's fighter
                if time.time() - mem.get("sel", 0) > 1.5:
                    pads[ME].tap("start", 0.08); mem["sel"] = time.time()
                    if STANDIN: pads[HUMAN].tap("start", 0.08)
                prev = st; time.sleep(0.05); continue
            if not st.in_stage(): prev = st; time.sleep(0.05); continue
            if not st.joined(ME) and st.joined(HUMAN) and not mem.get("joined_once") and time.time() - mem.get("join", 0) > 3:
                pads[ME].tap("start", 0.08); mem["join"] = time.time()     # a 1-player game: P2 joins with START
            if st.joined(ME): mem["joined_once"] = True

            if time.time() - hist_t > 30:
                close_role(); save_hist(hist); hist_t = time.time()
            if stage != st.stage():
                if stage is not None: close_role(); say("Stage clear!", show="%s: stage %d clear" % (MODEL, stage + 1))
                stage = st.stage(); rec = {}; food_said = set()
                log(dict(stage=stage, name=sor2.STAGES[stage], lives=[st.lives(0), st.lives(1)], hp=[st.php(0), st.php(1)]))

            # health lost and punks put away, under which call
            if prev and prev.in_stage():
                for i in (0, 1):
                    d = prev.php(i) - st.php(i)
                    if st.joined(i) and prev.joined(i) and 0 < d < sor2.FULL and st.lives(i) == prev.lives(i):
                        if i == HUMAN: lost.append((time.time(), d))
                        if role[0] in ROLES: rec.setdefault(role[0], new_rec())["p%d" % (i + 1)] += d
                        bump(role[0], **{"p%d" % (i + 1): d})
                    if prev.joined(i) and st.lives(i) < prev.lives(i) or prev.joined(i) and not st.joined(i):
                        log(dict(lost="P%d" % (i + 1), stage=stage, role=role[0], lives=st.lives(i),
                                 x=prev.x(prev.p(i)), y=prev.y(prev.p(i)), note=(me if i == ME else stand).note if (i == ME or stand) else ""))
                gone = [o for o in prev.enemies() if o not in st.enemies() or st.oid(o) != prev.oid(o)]
                if gone:
                    kos += len(gone)
                    if role[0] in ROLES: rec.setdefault(role[0], new_rec())["kos"] += len(gone)
                    bump(role[0], kos=len(gone))

            while heard:
                ev = heard.pop(0)
                if ev[0] == "listen": ra.cmd("SHOW_MSG %s is listening... (let go of R1)" % MODEL, reply=False); continue
                _, words, secs, why = ev
                if not words:
                    if why: ra.cmd("SHOW_MSG " + why, reply=False)
                    log(dict(heard="", why=why)); continue
                key = order_of(words); answer = obey(st, key, words)
                log(dict(heard=words, asr_s=round(secs, 2), order=key, stage=stage, role=role[0]))
                if answer: say(answer, show='You: "%s"  %s: %s' % (words[:50], MODEL, answer))
                else: ra.cmd('SHOW_MSG You: "%s"' % words[:70], reply=False)

            # food on the ground: the first piece on the screen
            foods = [f for f in st.items() if f[1] == "food" and st.onscreen(f[0], -8)]
            food = foods[0] if foods else None

            for b in [b for b in pending if "ans" in b]:
                pending.remove(b); mm = re.search(r"PICK\s*\(?([A-E])\)?", b["ans"])
                idx = "ABCDE".index(mm.group(1)) if mm else -1
                pick = b["keys"][idx] if 0 <= idx < len(b["keys"]) else b["keys"][0]
                n += 1; f = b["food"]; spoken = None
                if pick == "continue":
                    if not st.joined(ME): pads[ME].tap("start", 0.08); spoken = SAY["continue"]
                elif pick == "sitout": spoken = SAY["sitout"] if mem.get("sat") != stage else None; mem["sat"] = stage
                else:
                    eat = pick == "eat" if not order["food"] else order["food"] == "eat"
                    me.want = f[0] if eat and f and st.on(f[0]) else None
                    new = role[0] if pick in ("keep", "eat") else pick
                    if b["told"] and pick in ROLES and order["said_t"] <= b["t"]:
                        order.update(role=pick, said=" / ".join(b["told"])[:60], said_t=time.time())
                    elif order["role"]: new = role[0]
                    if f and f[0] not in food_said and st.on(f[0]):
                        spoken = (SAY["eat"] if me.want else SAY["leave"]) % f[2]; food_said.add(f[0])
                    if new and new != role[0]: set_role(new); spoken = spoken or SAY[new]
                    if role[0] in ROLES and pick != "keep": rec.setdefault(role[0], new_rec())["n"] += 1
                back = [l for l in b["ans"].splitlines()[1:] if l.strip()] if b["told"] else []
                if back: spoken = re.sub(r"^\W*SAY\W*", "", back[0]).strip().strip('"')[:90] or spoken
                if spoken: say(spoken, show="%s: %s" % (MODEL, spoken))
                log(dict(call=pick, parsed=bool(mm), think_s=round(b["dt"], 2), answer=b["ans"], stage=stage,
                         **dict((k, b[k]) for k in ("told", "q") if b.get(k))))

            food_said = {k for k in food_said if st.on(k)}
            if order["food"] and time.time() - order["food_t"] > 30: order["food"] = None
            if order["food"] == "eat" and food and me.want is None: me.want = food[0]
            if me.want is not None and not st.on(me.want): me.want = None
            if role[0] is None: role[0] = "help"
            if not busy() and (time.time() - last_ask > 2 or told or food and food[0] not in food_said and not pending):
                if st.joined(ME) or st.joined(HUMAN): ask_now(st, food)

            for i, sd in ((ME, me), (HUMAN, stand)):
                if not sd: continue
                btn = sd.step(st)
                if hold[0] and i == ME and sd.note in ("follow",):     # hold: stay put behind P1
                    btn = sd.walk(st, st.x(st.p(HUMAN)) - 40, st.y(st.p(HUMAN)), slack=12) if st.alive(HUMAN) else []
                press(i, btn, st.frame())
                if sd.stall: log(dict(sd.stall, who="P%d" % (i + 1), role=role[0])); sd.stall = None
            if time.time() - mem.get("status", 0) > 0.5:
                mem["status"] = time.time()
                try:
                    with open("/dev/shm/autogamer/sor2.tmp", "w") as fo:
                        for i, sd in ((ME, me), (HUMAN, stand)):
                            if sd: fo.write("P%d x %d y %d hp %d r %02x btn %s note %s target %s\n" % (
                                i + 1, st.x(st.p(i)), st.y(st.p(i)), st.php(i), st.routine(st.p(i)), held[i], sd.note,
                                sd.target and st.name(sd.target)))
                        fo.write("role %s hold %s want %s order %s kos %d\n" % (role[0], hold[0], me.want, order, kos))
                    os.replace("/dev/shm/autogamer/sor2.tmp", "/dev/shm/autogamer/sor2.txt")
                except OSError: pass
            prev = st
    finally:
        for p in pads: p.release_all()
        save_hist(hist)
        if LOG: LOG.close()
    print("%d calls in %.0f s, mean think %.1f s" % (n, time.time() - t0, sum(thinks) / max(len(thinks), 1)))
