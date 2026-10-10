#!/usr/bin/env python3
# Runs on the handheld beside RetroArch (run.sh tetris-model, tennis-model): SELECT pauses the game and shows the level
# menu over it (picker.py, the launch menu); the same level resumes the game where it was, another one saves the
# state (SAVE_STATE into RUN/states, run.sh's per-launch savestate folder), writes RUN/restart and ends RetroArch, and
# run.sh starts it again at the new speed and loads the state: RetroArch reads slowmotion_ratio only at start. run.sh
# writes RUN/levels ("NAME RATIO HUMAN_S" a line), RUN/level (the index) and TL_MENU_TITLE/TL_MENU_INFO for the
# menu. After every start this turns slow motion on (a toggle, ignored while paused) and announces the level.
# NES Tetris also gets SELECT (it toggles the next-piece box): harmless here. So does Punch-Out!! (between rounds it
# refills some of Mac's health, once a fight). AG_BULLET=1: the player turns slow motion on for each call itself
# (bullet time).
# Usage: level.py RUN
import glob, os, select, signal, struct, subprocess, sys, threading, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); from ra import RA; import voice
from home import pads, EV_KEY, BTN_MODE
RUN = sys.argv[1]; BTN_SELECT = 314; TTS = os.environ.get("TL_TTS", "0") == "1"
BULLET = os.environ.get("AG_BULLET") == "1"     # Punch-Out!!: slow motion only while the model decides
WORDS = {2: "twice as slow", 3: "three times slower", 4: "four times slower", 5: "five times slower", 6: "six times slower",
         7: "seven times slower", 8: "eight times slower", 9: "nine times slower", 10: "ten times slower",
         11: "eleven times slower", 12: "twelve times slower"}
ra = RA(timeout=0.3)

def levels(): return [l.split() for l in open(os.path.join(RUN, "levels")) if l.strip()]
def current(): return int(open(os.path.join(RUN, "level")).read())
def ra_pid():
    try: return int(subprocess.run(["pidof", "retroarch"], capture_output=True, text=True).stdout.split()[0])
    except (IndexError, ValueError): return None

def apply():
    """RetroArch has just started (or the game just began): slow motion on (unless BULLET), say the level."""
    t = time.time()
    while "PLAYING" not in (ra.cmd("GET_STATUS") or ""):
        if time.time() - t > 120: return
        time.sleep(0.3)
    name, r, h = levels()[current()]; r = float(r)
    if r > 1 and BULLET:                                  # the player turns slow motion on and off itself
        said = "%s. A human's %s seconds to decide: for each call, the game runs %s." % (
            name, h, WORDS.get(round(r), "%.0f times slower" % r))
        show = "%s: bullet time at 1/%.1f for each call (a human's %s s to decide)" % (name, r, h)
    elif r > 1:
        ra.cmd("SLOWMOTION", reply=False)
        said = "%s. %s, the game runs %s." % (name, "A human's second to think" if h == "1" else "A human's %s seconds to think" % h,
                                             WORDS.get(round(r), "%.0f times slower" % r) if abs(r - round(r)) < 0.25 else "%.1f times slower" % r)
        show = "%s: the model gets a human's %s s to think, so the game runs at 1/%.1f speed" % (name, h, r)
    else: said = show = "%s: real time. No help." % name
    if TTS: voice.say(said, show=show, ra=ra)
    else: ra.cmd("SHOW_MSG " + show, reply=False)
    print("%.1f %s 1/%.1f" % (time.time(), name, r), flush=True)

def onscreen(*cmd):
    """a fullscreen foot window over RetroArch, as run.sh's onscreen()"""
    def full():
        for _ in range(10):
            time.sleep(0.3)
            if subprocess.run(["swaymsg", '[app_id="autogamer"] fullscreen enable'], capture_output=True).returncode == 0: return
    threading.Thread(target=full, daemon=True).start()
    subprocess.run(["foot", "--app-id=autogamer", "-f", "monospace:size=20", "-o", "colors.background=030a03",
                    "-o", "colors.foreground=33ff66"] + list(cmd), stderr=subprocess.DEVNULL)

def menu():
    """SELECT: pause, the level menu over the game, then resume at the same level or restart RetroArch at the new one"""
    pid = ra_pid()
    if not pid: return
    if "PLAYING" in (ra.cmd("GET_STATUS") or ""): ra.cmd("PAUSE_TOGGLE", reply=False)
    old = current()
    onscreen("python3", os.path.join(HERE, "picker.py"), RUN, os.environ.get("TL_MENU_TITLE", "LEVEL"),
             os.environ.get("TL_MENU_INFO", ""), "60", "resume")
    if os.path.exists(os.path.join(RUN, "quit")): os.kill(pid, signal.SIGTERM); return     # HOME in the menu: the end
    i = current()
    if i == old:                                          # same level: back to the game where it was
        subprocess.run(["swaymsg", "[pid=%d] fullscreen enable, focus" % pid], capture_output=True)
        ra.cmd("PAUSE_TOGGLE", reply=False); return
    sd = os.path.join(RUN, "states"); os.makedirs(sd, exist_ok=True)
    f = None
    for paused in (True, False):                          # a save while paused, else a frame of play and save
        if not paused: ra.cmd("PAUSE_TOGGLE", reply=False)
        t = time.time() - 0.5; last = -1
        ra.cmd("SHOW_MSG Changing to %s..." % levels()[i][0], reply=False); ra.cmd("SAVE_STATE", reply=False)
        for _ in range(40):                               # the save lands within a frame (up to ~0.35 s at 1/20)
            time.sleep(0.15)
            new = [p for p in glob.glob(os.path.join(sd, "*.state*")) if os.path.getmtime(p) >= t]
            if new:
                size = os.path.getsize(new[0])
                if size == last and size > 0: f = new[0]; break
                last = size
        if f: break
    if not f:
        open(os.path.join(RUN, "level"), "w").write("%d\n" % old)
        ra.cmd("SHOW_MSG Level change failed: no save state", reply=False)
        if "PAUSED" in (ra.cmd("GET_STATUS") or ""): ra.cmd("PAUSE_TOGGLE", reply=False)
        return
    open(os.path.join(RUN, "restart"), "w").close()
    os.kill(pid, signal.SIGTERM)
    t = time.time()
    while ra_pid() in (pid, None):                        # run.sh starts the next one and loads the state
        if time.time() - t > 60: return
        time.sleep(0.3)
    apply()

if __name__ == "__main__":
    apply()
    fds, seen, home = {}, 0, False
    while True:
        if time.time() - seen > 5:
            for p in pads():
                if p not in fds.values():
                    try: fds[os.open(p, os.O_RDONLY | os.O_NONBLOCK)] = p
                    except OSError: pass
            seen = time.time()
        r, _, _ = select.select(list(fds), [], [], 1.0)
        pressed = False
        for fd in r:
            try: data = os.read(fd, 24 * 64)
            except OSError: os.close(fd); fds.pop(fd, None); continue
            for k in range(0, len(data) - 23, 24):
                _, _, typ, code, val = struct.unpack("qqHHi", data[k:k + 24])
                if typ != EV_KEY: continue
                if code == BTN_MODE: home = val != 0          # HOME+SELECT is RetroArch's, not ours
                elif code == BTN_SELECT and val == 1 and not home: pressed = True
        if pressed:
            menu()
            for fd in fds:
                try: os.read(fd, 24 * 256)                 # presses in the menu or during the restart do not queue up
                except OSError: pass
