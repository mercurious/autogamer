#!/usr/bin/env python3
# Runs on the handheld next to play.py: a commentator. Watches RAM at 20 Hz; when a point ends it calls it at once with a
# text-only line (score, who won, rally length). Every line is shown on the game screen (RetroArch SHOW_MSG) the
# moment its speech starts (Pocket TTS on 8093 -> pacat); a WAV of each is kept. The score going back to 0-0 after a
# set is a new set, not a game won.
# Looks (experimental, off): with NR_VGAP > 0 it also looks at the screen when nothing has been said for that many
# seconds, through a vision model's projector. That needs a GPU encoder (a look is ~160 s on the CPU) and models
# autogamer does not install; a point that ends during a look is called at once from a template, the look dropped.
# Usage: narrate.py SECONDS [OUTDIR]     env: NR_VGAP (default 0: never look), NR_TTS=0 (no voice), VS_PORT (default 8099)
import base64, json, os, re, subprocess, sys, threading, time, urllib.request, wave
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from ra import RA; import hud, llm
T = float(sys.argv[1]); OUT = sys.argv[2] if len(sys.argv) > 2 else "narr"; os.makedirs(OUT, exist_ok=True)
LLM = "http://127.0.0.1:%s" % os.environ.get("VS_PORT", "8099"); TTS = "http://127.0.0.1:8093"
MODEL = os.environ.get("AG_MODEL_LABEL", "E2B")
VGAP = float(os.environ.get("NR_VGAP", "0")); SPEAK = os.environ.get("NR_TTS", "1") != "0"
ENV = dict(os.environ, XDG_RUNTIME_DIR="/run/0-runtime-dir", WAYLAND_DISPLAY="wayland-1")
CALL = ["love", "15", "30", "40"]
WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]
SYSTEM = ("You are an excitable TV sports commentator calling a match of the 1981 Atari 2600 game Tennis, played live "
          "on a handheld. The pink player is an AI running on the handheld itself; the blue player is the game's "
          "built-in computer. A set is won by the first to six games. Speak ONE short sentence of live commentary, "
          "at most 18 words, no lists, no emojis. Use only the facts given; never claim a set or match is won "
          "unless the facts say so.")

def score_text(r):
    p, b, gp, gb = r[0x45], r[0x46], r[0x47], r[0x48]
    games = ("Games are level at %d all" % gp if gp == gb else
             "%s leads %d games to %d" % (("Pink", gp, gb) if gp > gb else ("Blue", gb, gp)))
    if p == b == 0: pts = "a new game is starting"
    elif p >= 3 and b >= 3: pts = "it is deuce" if p == b else "it is advantage %s" % ("Pink" if p > b else "Blue")
    elif p == b: pts = "it is %s all in this game" % CALL[p]
    else: pts = "in this game it is %s-%s to %s" % ((CALL[p], CALL[b], "Pink") if p > b else (CALL[b], CALL[p], "Blue"))
    return "%s; %s." % (games, pts)

def leader(r):
    gp, gb = r[0x47], r[0x48]
    return "pink" if gp > gb else "blue" if gb > gp else None

def faithful(line, winner, lead=None, set_won=False):
    """the line names the winner and not the loser; says "set" when the set was won (and only then); and credits a
    lead in games only to the player who has it"""
    l = line.lower(); loser = "blue" if winner == "pink" else "pink"
    if winner not in l or loser in l: return False
    if bool(re.search(r"\b(set|match)\b", l)) != set_won: return False
    return not (re.search(r"\b(lead|leads|leading|ahead|in front)\b", l) and lead != winner)

def ask(facts, img=None, winner=None, temp=0.9):
    text = "Facts: %s\n%s" % (facts, "Commentate on what you see in this moment." if img else
                              "Call this moment. Start your sentence with %s." % winner.capitalize())
    content = ([{"type": "image_url", "image_url": {"url": "data:image/png;base64," + img}}] if img else []) + [{"type": "text", "text": text}]
    line, tm = llm.chat(LLM, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}], 48, temp, 180)
    return line.split("\n")[0].strip('"'), tm

speech = threading.Lock()

def speak(text, wav_path):
    """caption and voice together: synthesize first (1-3 s), then SHOW_MSG and play. Returns seconds of audio."""
    with speech:
        pcm = b""
        if SPEAK:
            try:
                req = urllib.request.Request(TTS + "/v1/audio/speech", json.dumps({"input": text, "response_format": "pcm"}).encode(),
                                             {"Content-Type": "application/json"})
                pcm = urllib.request.urlopen(req, timeout=120).read()
                with wave.open(wav_path, "wb") as w: w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(pcm)
            except Exception: pcm = b""
        ra.cmd("SHOW_MSG " + text, reply=False)
        if pcm: subprocess.run(["pacat", "--raw", "--format=s16le", "--rate=24000", "--channels=1"], input=pcm, env=ENV)
        return len(pcm) / 48000

ra = RA(timeout=0.3); t0 = time.time(); log = open(os.path.join(OUT, "narrate.log"), "a")
busy = threading.Event(); n = [0]; last_said = [time.time() - VGAP + 3]; points = [0]   # points: ended so far

def record(rec):
    rec["wall"] = round(rec["t"], 2); rec["t"] = round(rec["t"] - t0, 1); log.write(json.dumps(rec) + "\n"); log.flush(); print(json.dumps(rec), flush=True)

def say(kind, facts, look, winner=None, fallback=None, lead=None, set_won=False):
    try:
        t1 = time.time(); img = None; p0 = points[0]
        if look:
            png = os.path.join(OUT, "look.png")
            subprocess.run(["grim", "-g", "375,71 1234x1009", "-s", "0.6224", png], env=ENV, check=True)
            img = base64.b64encode(open(png, "rb").read()).decode()
        try:
            line, tm = ask(facts, img, winner)
            if winner and not faithful(line, winner, lead, set_won):
                tm["rejected"] = line; line, tm2 = ask(facts, img, winner, 0.3)
                if not faithful(line, winner, lead, set_won): tm["rejected"] += " | " + line; line = fallback
        except Exception as e: line, tm = fallback, {"error": str(e)}
        t2 = time.time(); secs = 0
        if look and points[0] != p0: tm["dropped"] = line; line = None       # a point ended while it looked: stale
        if line:
            try: secs = speak(line, os.path.join(OUT, "line%03d.wav" % n[0]))
            except Exception as e: tm["tts_error"] = str(e)
        record({"t": t1, "kind": kind, "facts": facts, "line": line, "think_s": round(t2 - t1, 1),
                "speak_s": round(time.time() - t2, 1), "audio_s": round(secs, 1), "prompt_n": tm.get("prompt_n"),
                "rejected": tm.get("rejected"), "dropped": tm.get("dropped"), "err": tm.get("error") or tm.get("tts_error")})
        n[0] += 1
    finally:
        last_said[0] = time.time(); busy.clear()

def quick(kind, facts, line):
    """a template line, no model: for points that end while the model is busy, and for a new set"""
    t1 = time.time(); secs = speak(line, os.path.join(OUT, "line%03d.wav" % n[0])); n[0] += 1; last_said[0] = time.time()
    record({"t": t1, "kind": kind, "facts": facts, "line": line, "think_s": 0, "speak_s": round(time.time() - t1, 1),
            "audio_s": round(secs, 1), "prompt_n": None, "rejected": None, "dropped": None, "err": None})

def games_words(r):
    gp, gb = r[0x47], r[0x48]
    if gp == gb: return "%s games all." % WORDS[gp].capitalize()
    return "%s leads %s games to %s." % (("Pink", WORDS[gp], WORDS[gb]) if gp > gb else ("Blue", WORDS[gb], WORDS[gp]))

prev = None; shots = 0; last_dir = 0; last_d = None
while time.time() - t0 < T:
    r = ra.ram(0x80, 128)
    if not r: time.sleep(0.05); continue
    d = r[0x37]
    if d != 255 and r[0x10] > 5 and last_d is not None and abs(d - last_d) < 10:
        dirn = (d > last_d) - (d < last_d)
        if dirn and last_dir and dirn != last_dir: shots += 1
        if dirn: last_dir = dirn
    last_d = d
    score = (r[0x45], r[0x46], r[0x47], r[0x48])
    if prev is not None and score != prev and score[2] + score[3] < prev[2] + prev[3]:   # games went down: a new set
        threading.Thread(target=quick, args=("newset", "A new set begins.", "A new set begins. Love all."), daemon=True).start()
        shots = 0; last_dir = 0
    elif prev is not None and score != prev:
        if score[2] != prev[2] or score[3] != prev[3]: pink_won = score[2] > prev[2]
        elif score[0] > prev[0] or score[1] > prev[1]: pink_won = score[0] > prev[0]
        else: pink_won = score[1] < prev[1]          # an advantage falls back to deuce: the other player won it
        game = score[2] != prev[2] or score[3] != prev[3]
        win = "pink" if pink_won else "blue"; W = win.capitalize(); points[0] += 1
        set_won = game and max(score[2], score[3]) >= 6 and abs(score[2] - score[3]) >= 2
        what = "%s won the %s. The rally lasted %d shots." % (W, "game" if game else "point", shots + 1)
        if set_won:
            what += " That wins the set!"
            fb = "Game and set, %s, %s games to %s!" % (W, WORDS[max(score[2:])], WORDS[min(score[2:])])
        elif game: fb = "Game, %s! %s" % (W, games_words(r))
        else: fb = "Point to %s, after %s shot%s." % (W, WORDS[shots + 1] if shots < 10 else shots + 1, "" if shots == 0 else "s")
        if not busy.is_set():
            busy.set(); threading.Thread(target=say, args=("point", what + " " + score_text(r), False, win, fb, leader(r), set_won), daemon=True).start()
        else:                                        # the model is busy (a look): call it now from the template
            threading.Thread(target=quick, args=("quick", what, fb), daemon=True).start()
        shots = 0; last_dir = 0
    prev = score
    if VGAP > 0 and not busy.is_set() and not speech.locked() and time.time() - last_said[0] > VGAP and d != 255:
        busy.set(); threading.Thread(target=say, args=("look", score_text(r) + " A rally is under way, %d shots so far." % shots, True), daemon=True).start()
    time.sleep(0.05)
