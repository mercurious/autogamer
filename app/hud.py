#!/usr/bin/env python3
# The model field on autogamer's MangoHud bar (mangohud.conf: exec=cat /dev/shm/autogamer/hud.txt; exec shows one
# line, Latin-1 only, so the bars are ASCII): "7.4t/s |||:.... read [====--]". rate() sets the speedo, the
# writing speed on a fixed scale (a cell is 2 tok/s, ':' half a cell, full at 16: E4B fills 3.5, E2B 7); state() the
# work: the prompt read (a bar when the read speed is known), tokens written, then the think time. Written atomically
# (tmp + rename), so MangoHud never reads half a line. The longest field, 30 characters, still fits after the longest
# label ("E4B HARDEST 1/1.5") on the 1920 px screen.
# `hud.py load PID GGUF`: the model's load bar until PID ends (run.sh kills it when the model is up). llama-server
# maps the gguf and pages all of it in as it loads (from the SD card cold, ~60 MB/s), so its RssFile is the progress.
import os, sys, time
D = "/dev/shm/autogamer"; _now = {"rate": "", "state": ""}

def _write(line=None):
    if line is None: line = " ".join(x for x in (_now["rate"], _now["state"]) if x)
    try:
        os.makedirs(D, exist_ok=True); t = os.path.join(D, "hud.tmp")
        with open(t, "w") as f: f.write(line + "\n")
        os.replace(t, os.path.join(D, "hud.txt"))
    except OSError: pass

def bar(frac, n):
    k = int(round(max(0.0, min(frac, 1.0)) * n)); return "[" + "=" * k + "-" * (n - k) + "]"

def speedo(tps, n=8, per=2.0):
    h = int(round(max(0.0, min(tps / per, n)) * 2)); return "%.1ft/s %s" % (tps, ("|" * (h // 2) + ":" * (h % 2)).ljust(n, "."))

def rate(tps): _now["rate"] = speedo(tps) if tps else ""; _write()
def state(text): _now["state"] = text; _write()
def clear(): _now.update(rate="", state=""); _write()

def load(pid, gguf):
    size = os.path.getsize(gguf); best = 0.0
    while os.path.exists("/proc/%s" % pid):
        try:
            with open("/proc/%s/status" % pid) as f:
                kb = next((int(l.split()[1]) for l in f if l.startswith("RssFile:")), 0)
        except OSError: break
        best = max(best, min(kb * 1024 / size, 0.99))      # 100% is the server answering, not the pages
        _write("loading %s %d%%" % (bar(best, 14), best * 100)); time.sleep(0.5)

if __name__ == "__main__" and sys.argv[1:2] == ["load"]: load(*sys.argv[2:4])
