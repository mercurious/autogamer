#!/usr/bin/env python3
# The model field on autogamer's MangoHud bar (mangohud.conf: exec=cat /dev/shm/autogamer/hud.txt; exec shows
# one line): "E4B 6.1 tok/s · reading 297 tok 4 s". rate() and state() each set their half; written atomically
# (tmp + rename), so MangoHud never reads half a line.
import os
D = "/dev/shm/autogamer"; _now = {"rate": "", "state": ""}

def _write():
    line = " · ".join(x for x in (_now["rate"], _now["state"]) if x)
    try:
        os.makedirs(D, exist_ok=True); t = os.path.join(D, "hud.tmp")
        with open(t, "w") as f: f.write(line + "\n")
        os.replace(t, os.path.join(D, "hud.txt"))
    except OSError: pass

def rate(text): _now["rate"] = text; _write()
def state(text): _now["state"] = text; _write()
def clear(): _now.update(rate="", state=""); _write()
